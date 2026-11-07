"""Расходы (Expense) и их распределения (ExpenseAllocation).

Расход - одна запись; доли (ExpenseAllocation) раскладывают его на заказы и рейсы. Одна доля -
один срез анализа и считается один раз: у доли расхода перевозчика заполнены и заказ, и рейс, это
ОДНА строка, а не две. Σ долей <= суммы расхода; при requires_full_allocation Σ == сумме;
нераспределённые общие расходы допустимы. Платёж и счёт расходов не создают.

Порядок блокировок: Order -> Trip -> Expense -> доли -> Invoice -> Payment. Engine сервисы не
проверяют (хуки: hooks.py). Права и причины приходят параметрами от API-слоя.
"""

from datetime import date
from decimal import ROUND_DOWN, Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.audit import services as audit
from apps.core.handbooks.models import HandbookValue
from apps.core.tenancy import tenant_context
from apps.forwarding.finance_lines.models import company_today
from apps.forwarding.models import Order, Trip

from . import periods
from .engine import current_cid
from .errors import FinanceError
from .fx import fx_snapshot
from .income import cid_company, get_settings_for
from .models import Expense, ExpenseAllocation, ExpenseInvoiceAllocation
from .money import CENT, quantize_money
from .trip_expense import split_evenly

UNIQUE_CARRIER = "expense_one_active_carrier_per_trip"
DEFAULT_CATEGORY = "OTHER"


def _money(value, field="amount", *, positive=False) -> Decimal:
    try:
        amount = quantize_money(Decimal(str(value)))
    except Exception:  # noqa: BLE001
        raise FinanceError("amount_invalid", f"{field}: некорректная сумма") from None
    if amount < 0 or (positive and amount == 0):
        raise FinanceError("amount_invalid", f"{field}: сумма должна быть положительной")
    return amount


def split_proportionally(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Делит total пропорционально weights до копейки (наибольший остаток); Σ == total."""
    total = quantize_money(total)
    weight_sum = sum(weights, Decimal("0"))
    if not weights:
        return []
    if weight_sum <= 0:
        raise FinanceError("allocation_mismatch", "Нечего распределять пропорционально")
    exact = [total * w / weight_sum for w in weights]
    parts = [e.quantize(CENT, rounding=ROUND_DOWN) for e in exact]
    cents = int((total - sum(parts, Decimal("0"))) / CENT)
    order = sorted(range(len(parts)), key=lambda i: (-(exact[i] - parts[i]), i))
    for i in order[:cents]:
        parts[i] += CENT
    return parts


def alloc_state(expense: Expense) -> list[dict]:
    return [
        {"order": a.order_id, "trip": a.trip_id, "amount": str(a.amount)}
        for a in ExpenseAllocation.objects.filter(expense=expense).order_by("id")
    ]


def trip_order_ids(trip: Trip) -> list[int]:
    return sorted(
        set(
            trip.consignments.filter(order__deleted_at__isnull=True).values_list(
                "order_id", flat=True
            )
        )
    )


def active_link_total(expense: Expense) -> Decimal:
    return ExpenseInvoiceAllocation.objects.filter(
        expense=expense, released_at__isnull=True
    ).aggregate(t=Sum("amount"))["t"] or Decimal("0.00")


def refresh_invoice_variance(expense: Expense, user=None) -> Expense:
    """Ставит/снимает needs_review по расхождению с активными связями со счетами.

    Ничего не блокирует и не меняет счета/платежи."""
    with tenant_context(current_cid(expense.company_id)):
        return _refresh_variance(expense, user)


def _refresh_variance(expense: Expense, user) -> Expense:
    links = ExpenseInvoiceAllocation.objects.filter(expense=expense, released_at__isnull=True)
    variance = links.exists() and active_link_total(expense) != expense.amount
    if variance and not (expense.needs_review and expense.review_reason == "invoice_variance"):
        expense.needs_review, expense.review_reason = True, "invoice_variance"
        expense.save(update_fields=["needs_review", "review_reason", "updated_at"])
        audit.log(
            "update",
            expense,
            user,
            {"needs_review": [False, True], "review_reason": "invoice_variance"},
        )
    elif not variance and expense.needs_review and expense.review_reason == "invoice_variance":
        expense.needs_review, expense.review_reason = False, ""
        expense.save(update_fields=["needs_review", "review_reason", "updated_at"])
        audit.log("update", expense, user, {"needs_review": [True, False]})
    return expense


def _normalize(expense: Expense, items) -> list[tuple[int | None, int | None, Decimal]]:
    """Проверяет доли; возвращает [(order_id, trip_id, amount)]."""
    out, seen = [], set()
    allowed_orders = None
    if expense.kind == "carrier_transport":
        allowed_orders = set(trip_order_ids(expense.trip))
    for item in items or []:
        order = item.get("order", item.get("order_id"))
        trip = item.get("trip", item.get("trip_id"))
        order_id = getattr(order, "pk", order)
        trip_id = getattr(trip, "pk", trip)
        if order_id is None and trip_id is None:
            raise FinanceError("allocation_target", "Доля должна указывать заказ или рейс")
        amount = _money(item.get("amount"), "доля", positive=True)
        if order_id is not None and not Order.objects.filter(pk=order_id).exists():
            raise FinanceError("allocation_target", "Заказ не найден")
        if trip_id is not None and not Trip.objects.filter(pk=trip_id).exists():
            raise FinanceError("allocation_target", "Рейс не найден")
        if expense.kind == "carrier_transport":
            if order_id is not None and order_id not in allowed_orders:
                raise FinanceError("order_not_in_trip", "Заказ не входит в рейс расхода")
            if trip_id is not None and trip_id != expense.trip_id:
                raise FinanceError("allocation_target", "Доля расхода перевозчика - на его рейс")
            trip_id = expense.trip_id
        if (order_id, trip_id) in seen:
            raise FinanceError("allocation_duplicate", "Доля с таким заказом и рейсом уже есть")
        seen.add((order_id, trip_id))
        out.append((order_id, trip_id, amount))
    total = sum((a for _, _, a in out), Decimal("0"))
    if total > expense.amount:
        raise FinanceError("allocation_exceeds", "Сумма долей больше суммы расхода")
    if expense.requires_full_allocation and total != expense.amount:
        raise FinanceError("allocation_mismatch", "Сумма долей должна равняться сумме расхода")
    return out


def _write_allocations(expense: Expense, rows) -> None:
    """Приводит доли к rows по разности: неизменные доли сохраняются (с legacy_line)."""
    pool: dict[tuple, list[ExpenseAllocation]] = {}
    for alloc in ExpenseAllocation.objects.filter(expense=expense).order_by("id"):
        pool.setdefault((alloc.order_id, alloc.trip_id), []).append(alloc)
    keep, new = set(), []
    for order_id, trip_id, amount in rows:
        candidates = pool.get((order_id, trip_id))
        if candidates:
            alloc = candidates.pop(0)
            keep.add(alloc.pk)
            if alloc.amount != amount:
                alloc.amount = amount
                alloc.save(update_fields=["amount"])
        else:
            new.append(
                ExpenseAllocation(
                    company_id=expense.company_id,
                    expense=expense,
                    order_id=order_id,
                    trip_id=trip_id,
                    amount=amount,
                )
            )
    ExpenseAllocation.objects.filter(expense=expense).exclude(pk__in=keep).delete()
    ExpenseAllocation.objects.bulk_create(new)


def _handbook(value, code: str, field: str, *, active=True) -> HandbookValue:
    pk = getattr(value, "pk", value)
    found = HandbookValue.objects.filter(pk=pk, handbook__code=code)
    if active:
        found = found.filter(is_active=True)
    row = found.first() if isinstance(pk, int) and not isinstance(pk, bool) else None
    if row is None:
        raise FinanceError("handbook_invalid", f"{field}: нужно значение справочника {code}")
    return row


def _default_category() -> HandbookValue:
    return HandbookValue.objects.get(handbook__code="expense_category", code=DEFAULT_CATEGORY)


# --- создание ----------------------------------------------------------------------------


@transaction.atomic
def create_expense(
    company,
    *,
    title,
    category,
    amount,
    currency,
    expense_date: date,
    user,
    perms=(),
    adjust_reason: str | None = None,
    trip=None,
    carrier=None,
    kind: str = "other",
    requires_full_allocation: bool = False,
    allocations=None,
) -> Expense:
    """Ручной расход. Платёж и счёт расход не создают. Дата - ввод пользователя (1.4.3)."""
    if kind != "other":
        raise FinanceError("expense_kind_invalid", "Расход перевозчику создаётся из цены рейса")
    title = (title or "").strip()
    if not title:
        raise FinanceError("title_required", "Укажите название расхода")
    cid = company.pk
    amount = _money(amount)
    with tenant_context(cid):
        category = _handbook(category, "expense_category", "category")
        currency = _handbook(currency, "currency", "currency")
        adjusted = periods.check_user_date(cid, expense_date, perms, adjust_reason)
        snapshot = fx_snapshot(company, amount, currency, expense_date, get_settings_for(cid))
        expense = Expense(
            company_id=cid,
            kind="other",
            title=title,
            category=category,
            amount=amount,
            currency=currency,
            expense_date=expense_date,
            source="manual",
            trip=trip,
            carrier=carrier,
            requires_full_allocation=bool(requires_full_allocation),
            created_by=user if getattr(user, "pk", None) else None,
            **snapshot,
        )
        expense.save()
        if allocations is not None:  # без долей расход ждёт распределения (set_allocations)
            _write_allocations(expense, _normalize(expense, allocations))
        changes = audit.diff({}, audit.snapshot(expense))
        changes["allocations"] = [[], alloc_state(expense)]
        if adjusted:
            changes.update(periods.adjustment_changes(adjust_reason, None, {"amount": str(amount)}))
        audit.log("create", expense, user, changes)
        return expense


@transaction.atomic
def create_carrier_expense(
    trip: Trip,
    *,
    user,
    perms=(),
    allocations=None,
    expense_date: date | None = None,
    adjust_reason: str | None = None,
    category=None,
) -> Expense:
    """Ручное действие «Создать расход из цены рейса» (автоматически не вызывается)."""
    cid = current_cid(trip.company_id)
    with tenant_context(cid):
        # Order -> Trip: заказы рейса блокируются по возрастанию pk, затем сам рейс
        probe = Trip.objects.get(pk=trip.pk)
        order_ids = trip_order_ids(probe)
        orders = list(Order.all_objects.select_for_update().filter(pk__in=order_ids).order_by("pk"))
        trip = Trip.objects.select_for_update().get(pk=trip.pk)
        if trip.carrier_id is None:
            raise FinanceError("trip_without_carrier", "У рейса не указан перевозчик")
        if Expense.objects.filter(trip=trip, kind="carrier_transport", status="active").exists():
            raise FinanceError(
                "expense_exists", "Расход по этому рейсу уже создан", status_code=409
            )
        for order in orders:
            if order.currency_id != trip.currency_id:
                raise FinanceError("currency_mismatch", "Валюта рейса отличается от валюты заказа")
        amount = quantize_money(trip.carrier_price)
        if expense_date is None:
            day = company_today(cid)
            adjusted = periods.check_system_date(cid, day, perms, adjust_reason)
        else:
            day = expense_date
            adjusted = periods.check_user_date(cid, day, perms, adjust_reason)
        company = cid_company(cid)
        snapshot = fx_snapshot(company, amount, trip.currency, day, get_settings_for(cid))
        cat = (
            _handbook(category, "expense_category", "category") if category else _default_category()
        )
        expense = Expense(
            company_id=cid,
            kind="carrier_transport",
            title=f"Перевозка {trip.number}",
            category=cat,
            amount=amount,
            currency_id=trip.currency_id,
            expense_date=day,
            source="carrier_price_sync",
            trip=trip,
            carrier_id=trip.carrier_id,
            carrier_price_snapshot=amount,
            requires_full_allocation=True,
            created_by=user if getattr(user, "pk", None) else None,
            **snapshot,
        )
        try:
            with transaction.atomic():
                expense.save()
        except IntegrityError as exc:
            constraint = getattr(getattr(exc.__cause__, "diag", None), "constraint_name", "")
            if constraint != UNIQUE_CARRIER:
                raise
            raise FinanceError(
                "expense_exists", "Расход по этому рейсу уже создан", status_code=409
            ) from None
        if allocations is None:
            rows = _default_rows(trip, orders, amount)
            allocations = [{"order": o, "trip": t, "amount": a} for o, t, a in rows]
        _write_allocations(expense, _normalize(expense, allocations))
        changes = audit.diff({}, audit.snapshot(expense))
        changes["allocations"] = [[], alloc_state(expense)]
        if adjusted:
            changes.update(periods.adjustment_changes(adjust_reason, None, {"amount": str(amount)}))
        audit.log("create", expense, user, changes)
        return expense


def _default_rows(trip: Trip, orders: list[Order], amount: Decimal):
    """Доли по умолчанию: поровну по заказам рейса (копейки первому); без заказов - рейс."""
    if amount == 0:
        return []
    if not orders:
        return [(None, trip.pk, amount)]
    return [(o.pk, trip.pk, a) for o, a in zip(orders, split_evenly(amount, len(orders)))]


# --- синхронизация с ценой рейса -----------------------------------------------------------


def _rebalanced(expense: Expense, old_rows: list[ExpenseAllocation], new_amount: Decimal):
    """Новые суммы долей: пропорционально прежним; при полном распределении Σ == new_amount."""
    if new_amount == 0:
        return []
    old_total = sum((a.amount for a in old_rows), Decimal("0"))
    if not old_rows or old_total == 0:
        return None  # решает вызывающий (создать по умолчанию)
    if expense.requires_full_allocation:
        target = new_amount
    else:
        target = (
            quantize_money(old_total * new_amount / expense.amount)
            if expense.amount
            else new_amount
        )
    return split_proportionally(target, [a.amount for a in old_rows])


@transaction.atomic
def sync_trip_expense(
    trip: Trip, *, user, can_adjust: bool = False, reason: str | None = None
) -> Expense | None:
    """Приводит активный расход перевозчика к цене рейса (одним расходом, без второго)."""
    cid = current_cid(trip.company_id)
    with tenant_context(cid):
        trip = Trip.objects.select_for_update().get(pk=trip.pk)
        expense = (
            Expense.objects.select_for_update()
            .filter(trip=trip, kind="carrier_transport", status="active")
            .first()
        )
        if expense is None:
            return None  # автосоздания нет
        new_amount = quantize_money(trip.carrier_price)
        if expense.amount == new_amount:
            return expense
        adjusted = periods.assert_period_open(
            cid, expense.expense_date, can_adjust=can_adjust, reason=reason
        )
        old_rows = list(
            ExpenseAllocation.objects.select_for_update().filter(expense=expense).order_by("id")
        )
        old_alloc = alloc_state(expense)
        before = audit.snapshot(expense)
        new_parts = _rebalanced(expense, old_rows, new_amount)
        expense.amount = new_amount
        expense.carrier_price_snapshot = new_amount
        if expense.fx_rate is not None:  # курс снимка не меняется
            expense.base_amount = quantize_money(new_amount * expense.fx_rate)
        expense.save()
        if new_parts is None:
            orders = list(Order.all_objects.filter(pk__in=trip_order_ids(trip)).order_by("pk"))
            if expense.requires_full_allocation:
                rows = _default_rows(trip, orders, new_amount)
                _write_allocations(
                    expense,
                    _normalize(expense, [{"order": o, "trip": t, "amount": a} for o, t, a in rows]),
                )
        elif not new_parts:
            ExpenseAllocation.objects.filter(expense=expense).delete()
        else:
            for row, part in zip(old_rows, new_parts):
                if part <= 0:  # доля обнулилась: убираем (суммы долей > 0 по ограничению БД)
                    row.delete()
                elif row.amount != part:
                    row.amount = part
                    row.save(update_fields=["amount"])
        changes = audit.diff(before, audit.snapshot(expense))
        changes["allocations"] = [old_alloc, alloc_state(expense)]
        if reason:
            changes["reason"] = reason.strip()
        if adjusted:
            changes.update(
                periods.adjustment_changes(
                    reason, {"amount": str(before["amount"])}, {"amount": str(new_amount)}
                )
            )
        audit.log("update", expense, user, changes)
        refresh_invoice_variance(expense, user)
        return expense


# --- распределение и аннулирование -------------------------------------------------------


@transaction.atomic
def set_allocations(
    expense: Expense, items, *, user, perms=(), reason: str | None = None
) -> Expense:
    """Заменяет доли расхода (под блокировкой расхода)."""
    cid = current_cid(expense.company_id)
    with tenant_context(cid):
        locked = Expense.objects.select_for_update().get(pk=expense.pk)
        if locked.status != "active":
            raise FinanceError("expense_void", "Расход аннулирован", status_code=409)
        rows = _normalize(locked, items)
        old = alloc_state(locked)
        new = [{"order": o, "trip": t, "amount": str(a)} for o, t, a in rows]
        if sorted(map(str, old)) == sorted(map(str, new)):
            return locked
        adjusted = periods.assert_period_open(
            cid, locked.expense_date, can_adjust=periods.ADJUST_PERMISSION in perms, reason=reason
        )
        _write_allocations(locked, rows)
        changes = {"allocations": [old, alloc_state(locked)]}
        if adjusted:
            changes.update(periods.adjustment_changes(reason, old, alloc_state(locked)))
        audit.log("update", locked, user, changes)
        return locked


@transaction.atomic
def void_expense(expense: Expense, *, user, reason: str, can_adjust: bool = False) -> Expense:
    """Аннулирует расход: доли остаются историей, платежи и счета не меняются."""
    reason = (reason or "").strip()
    if not reason:
        raise FinanceError("reason_required", "Укажите причину аннулирования расхода")
    cid = current_cid(expense.company_id)
    with tenant_context(cid):
        locked = Expense.objects.select_for_update().get(pk=expense.pk)
        if locked.status == "void":
            return locked
        adjusted = periods.assert_period_open(
            cid, locked.expense_date, can_adjust=can_adjust, reason=reason
        )
        locked.status = "void"
        locked.voided_by = user if getattr(user, "pk", None) else None
        locked.voided_at = timezone.now()
        locked.void_reason = reason
        locked.save()
        changes = {"status": ["active", "void"], "reason": reason}
        if adjusted:
            changes.update(
                periods.adjustment_changes(reason, {"status": "active"}, {"status": "void"})
            )
        audit.log("update", locked, user, changes)
        return locked
