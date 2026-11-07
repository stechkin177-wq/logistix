# ruff: noqa: E501
"""Перенос строк OrderService в Income / Expense / ExpenseAllocation (идемпотентно).

OrderService НЕ меняется и не удаляется. Ключи идемпотентности: Income.legacy_line,
ExpenseAllocation.legacy_line, Expense.legacy_group_key. Перенос истории: закрытые периоды и
обратное датирование не применяются (recognized_on = дата строки), но пишется аудит.

Классификация расходов (решение заказчика №2): расход перевозчика переносится как ОДИН Expense на
группу строк рейса только если ВСЕ проверки пройдены; любое сомнение -> FinanceMigrationIssue
(ambiguous_trip_expense) и строка НЕ переносится и НЕ превращается в ручной расход.
Курс на дату строки не найден или нет базовой валюты -> снимок legacy_missing (курс не
придумывается, сумма в исходной валюте сохраняется).
"""

import re
from collections import Counter, defaultdict
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.audit import services as audit
from apps.core.handbooks.models import HandbookValue
from apps.core.tenancy import tenant_context
from apps.forwarding.finance_lines.models import OrderService
from apps.forwarding.models import Order, Trip, TripConsignment

from .engine import current_cid
from .errors import FinanceError
from .fx import fx_snapshot, legacy_missing_snapshot
from .income import cid_company, get_settings_for
from .models import (
    Expense,
    ExpenseAllocation,
    ExpenseInvoiceAllocation,
    FinanceMigrationIssue,
    Income,
    Invoice,
    InvoiceItem,
)
from .money import quantize_money

CARRIER_CATEGORY = "Перевозка"
TRIP_TITLE = re.compile(r"^Перевозка\s+(\S+)")
SOURCE_MODEL = "forwarding.orderservice"
ISSUE_TRIP = "ambiguous_trip_expense"
MIGRATION_ISSUE_TYPES = (ISSUE_TRIP, "migrate_error")


class Result:
    """Счётчики, суммы-источники и спорные строки одного прогона."""

    def __init__(self):
        self.counters: Counter = Counter()
        self.sources: dict = defaultdict(lambda: {"income": Decimal("0"), "expense": Decimal("0")})
        self.issues: list[dict] = []

    def merge(self, other: "Result") -> "Result":
        self.counters.update(other.counters)
        for key, value in other.sources.items():
            self.sources[key]["income"] += value["income"]
            self.sources[key]["expense"] += value["expense"]
        self.issues += other.issues
        return self

    def sources_json(self) -> dict:
        out: dict = {}
        for (ccy, month), v in sorted(self.sources.items()):
            out.setdefault(ccy, {})[month] = {
                "income": str(v["income"]),
                "expense": str(v["expense"]),
            }
        return out


def is_trip_candidate(line: OrderService) -> bool:
    return line.expense > 0 and (
        line.category == CARRIER_CATEGORY or bool(TRIP_TITLE.match(line.title))
    )


def _category_other() -> HandbookValue:
    return HandbookValue.objects.get(handbook__code="expense_category", code="OTHER")


def _snapshot(company, amount, currency, day, settings) -> dict:
    try:
        return fx_snapshot(company, amount, currency, day, settings)
    except FinanceError:
        return legacy_missing_snapshot(company, currency)


class _Ctx:
    def __init__(self, cid, run, overwrite, dry):
        self.cid, self.run, self.overwrite, self.dry = cid, run, overwrite, dry
        self.company = cid_company(cid)
        self.settings = get_settings_for(cid)
        self.result = Result()
        self.category = _category_other()

    def count(self, key, n=1):
        self.result.counters[key] += n

    def issue(self, line, message, details=None, issue_type=ISSUE_TRIP):
        """Спорная строка: Issue (один на строку) и запись в отчёт.

        Разрешённая проблема НЕ открывается заново: сохранённое решение применяется идемпотентно
        (carrier_expense / manual_expense) либо строка пропускается (justified_exclusion)."""
        self.result.issues.append(
            {"line": line.pk, "order": line.order_id, "title": line.title, "message": message}
        )
        qs = FinanceMigrationIssue.objects.filter(
            issue_type=issue_type, source_model=SOURCE_MODEL, source_id=line.pk
        )
        existing = qs.filter(status="open").first() or qs.first()
        if existing is not None and existing.status == "open":
            self.count("issues_existing")
            return
        if existing is not None and issue_type == ISSUE_TRIP:
            if existing.resolution == "justified_exclusion":
                self.result.issues.pop()  # решено человеком: не спорная
                self.count("issues_justified_skipped")
            elif existing.resolution in ("carrier_expense", "manual_expense"):
                self.result.issues.pop()
                apply_resolution(self, line, existing)
            else:  # разрешена без решения: возвращаем в работу, а не теряем сумму
                self.count("issues_reopened")
                if not self.dry:
                    existing.status, existing.resolved_at, existing.resolved_by = "open", None, None
                    existing.save()
            return
        self.count("issues_new")
        if self.dry:
            return
        FinanceMigrationIssue.objects.create(
            company_id=self.cid,
            run=self.run,
            issue_type=issue_type,
            severity="error",
            source_model=SOURCE_MODEL,
            source_id=line.pk,
            message=message,
            details={"title": line.title, "category": line.category, "order": line.order_id,
                     "expense": str(line.expense), **(details or {})},
        )  # fmt: skip


# --- доходы ---------------------------------------------------------------------------------


def _income_fields(ctx, line, order) -> dict:
    snap = _snapshot(ctx.company, line.income, order.currency, line.date, ctx.settings)
    return {
        "kind": "freight" if line.is_base else "service",
        "title": line.title[:255],
        "category": (line.category or "")[:64],
        "amount": quantize_money(line.income),
        "currency_id": order.currency_id,
        "status": "recognized",
        "recognized_on": line.date,
        "recognition_basis": "legacy_line_date",
        **snap,
    }


def _same(obj, fields: dict) -> bool:
    for key, value in fields.items():
        if key == "fx_base_currency":
            if obj.fx_base_currency_id != (value.pk if value is not None else None):
                return False
        elif getattr(obj, key) != value:
            return False
    return True


def _migrate_income(ctx: _Ctx, line, order) -> None:
    income = Income.objects.filter(legacy_line=line).first()
    if line.income <= 0:
        if income is not None and ctx.overwrite and income.status != "void" and not ctx.dry:
            income.status, income.void_reason, income.legacy_line = (
                "void",
                "legacy_line_zeroed",
                None,
            )
            income.save()
            audit.log(
                "update",
                income,
                None,
                {"status": ["recognized", "void"], "reason": "legacy_line_zeroed"},
            )
            ctx.count("income_voided")
        return
    fields = _income_fields(ctx, line, order)
    if income is None:
        ctx.count("income_created")
        if not ctx.dry:
            income = Income(company_id=ctx.cid, order=order, legacy_line=line, **fields)
            income.save()
            audit.log("create", income, None, audit.diff({}, audit.snapshot(income)))
        return
    if ctx.overwrite and not _same(income, fields):
        ctx.count("income_updated")
        if not ctx.dry:
            before = audit.snapshot(income)
            for key, value in fields.items():
                setattr(income, key, value)
            income.save()
            audit.log("update", income, None, audit.diff(before, audit.snapshot(income)))
        return
    ctx.count("income_existing")


# --- расходы -------------------------------------------------------------------------------


def _migrate_manual(ctx: _Ctx, line, order) -> None:
    key = f"line:{line.pk}"
    expense = Expense.objects.filter(legacy_group_key=key).first()
    alloc = ExpenseAllocation.objects.filter(legacy_line=line).first()
    if expense is None and alloc is None:
        ctx.count("manual_expense_created")
        if ctx.dry:
            return
        snap = _snapshot(ctx.company, line.expense, order.currency, line.date, ctx.settings)
        expense = Expense(
            company_id=ctx.cid, kind="other", title=line.title[:255], category=ctx.category,
            amount=quantize_money(line.expense), currency_id=order.currency_id,
            expense_date=line.date, status="active", source="migrated", legacy_group_key=key,
            requires_full_allocation=False, **snap,
        )  # fmt: skip
        expense.save()
        ExpenseAllocation.objects.create(
            company_id=ctx.cid,
            expense=expense,
            order=order,
            amount=quantize_money(line.expense),
            legacy_line=line,
        )
        audit.log("create", expense, None, {**audit.diff({}, audit.snapshot(expense)),
                  "legacy_line": line.pk, "source_category": line.category})  # fmt: skip
        return
    if ctx.overwrite and expense is not None and alloc is not None:
        amount = quantize_money(line.expense)
        if expense.amount != amount or alloc.amount != amount or expense.status == "void":
            ctx.count("manual_expense_updated")
            if not ctx.dry:
                before = audit.snapshot(expense)
                snap = _snapshot(ctx.company, amount, order.currency, line.date, ctx.settings)
                expense.amount, expense.expense_date, expense.title = (
                    amount,
                    line.date,
                    line.title[:255],
                )
                for k, v in snap.items():
                    setattr(expense, k, v)
                if expense.status == "void":
                    expense.status, expense.void_reason = "active", ""
                expense.save()
                alloc.amount = amount
                alloc.save(update_fields=["amount"])
                audit.log("update", expense, None, audit.diff(before, audit.snapshot(expense)))
            return
    ctx.count("manual_expense_existing")


def check_group(ctx: _Ctx, title: str, lines: list):
    """(trip, причина). Группа проходит только при выполнении ВСЕХ условий."""
    match = TRIP_TITLE.match(title)
    if not match:
        return None, "В названии строки нет номера рейса"
    number = match.group(1)
    trip = Trip.objects.filter(number=number).first()
    if trip is None:
        deleted = Trip.all_objects.filter(number=number).exists()
        return None, "Рейс удалён" if deleted else f"Рейс {number} не найден"
    if trip.carrier_id is None:
        return None, "У рейса нет перевозчика"
    order_ids = {ln.order_id for ln in lines}
    in_trip = set(
        TripConsignment.objects.filter(trip=trip).values_list("consignment__order_id", flat=True)
    )
    if not order_ids <= in_trip:
        return None, "Заказ строки не входит в состав рейса"
    for order in Order.all_objects.filter(pk__in=order_ids):
        if order.currency_id != trip.currency_id:
            return None, "Валюта заказа отличается от валюты рейса"
    key = f"trip:{trip.pk}"
    others = (
        OrderService.objects.filter(expense__gt=0, title__startswith="Перевозка")
        .exclude(title=title)
        .values_list("title", flat=True)
        .distinct()
    )
    for other in others:
        m = TRIP_TITLE.match(other)
        if m and m.group(1) == number:
            return None, f"Вторая группа расходов на тот же рейс: «{other}»"
    clash = Expense.objects.filter(trip=trip, kind="carrier_transport", status="active").exclude(
        legacy_group_key=key
    )
    if clash.exists():
        return None, "На рейс уже есть другой расход перевозчика"
    return trip, None


def _group_lines(title: str) -> list:
    return [
        ln
        for ln in OrderService.objects.filter(title=title, expense__gt=0).order_by("pk")
        if is_trip_candidate(ln)
    ]


def _migrate_group(ctx: _Ctx, title: str, mine: list) -> None:
    lines = _group_lines(title)
    trip, reason = check_group(ctx, title, lines)
    if trip is None:
        for line in mine:
            ctx.issue(line, reason, {"group_lines": [ln.pk for ln in lines]})
        return
    key = f"trip:{trip.pk}"
    expense = Expense.objects.filter(legacy_group_key=key).first()
    total = quantize_money(sum((ln.expense for ln in lines), Decimal("0")))
    day = min(ln.date for ln in lines)
    if expense is None:
        ctx.count("group_expense_created")
        if ctx.dry:
            ctx.count("group_allocations_created", len(lines))
            return
        Trip.objects.select_for_update().get(pk=trip.pk)
        snap = _snapshot(ctx.company, total, trip.currency, day, ctx.settings)
        mismatch = total != quantize_money(trip.carrier_price)
        expense = Expense(
            company_id=ctx.cid, kind="carrier_transport", title=title[:255], category=ctx.category,
            amount=total, currency_id=trip.currency_id, expense_date=day, status="active",
            source="migrated", trip=trip, carrier_id=trip.carrier_id, legacy_group_key=key,
            carrier_price_snapshot=quantize_money(trip.carrier_price),
            requires_full_allocation=True, needs_review=mismatch,
            review_reason="migrated_mismatch" if mismatch else "", **snap,
        )  # fmt: skip
        expense.save()
        for ln in lines:
            ExpenseAllocation.objects.create(
                company_id=ctx.cid, expense=expense, order_id=ln.order_id, trip=trip,
                amount=quantize_money(ln.expense), legacy_line=ln,
            )  # fmt: skip
        ctx.count("group_allocations_created", len(lines))
        audit.log("create", expense, None, {**audit.diff({}, audit.snapshot(expense)),
                  "legacy_lines": [ln.pk for ln in lines]})  # fmt: skip
        return
    existing = {
        a.legacy_line_id: a
        for a in ExpenseAllocation.objects.filter(expense=expense)
        if a.legacy_line_id
    }
    missing = [ln for ln in lines if ln.pk not in existing]
    if not ctx.overwrite:
        ctx.count("group_expense_existing")
        return
    stale = [a for lid, a in existing.items() if lid not in {ln.pk for ln in lines}]
    changed = bool(
        missing or stale or expense.amount != total
        or any(
            existing[ln.pk].amount != quantize_money(ln.expense)
            for ln in lines
            if ln.pk in existing
        )
    )  # fmt: skip
    if not changed:
        ctx.count("group_expense_existing")
        return
    ctx.count("group_expense_updated")
    if ctx.dry:
        return
    before = audit.snapshot(expense)
    for a in stale:
        a.delete()
    for ln in lines:
        amount = quantize_money(ln.expense)
        if ln.pk in existing:
            if existing[ln.pk].amount != amount:
                existing[ln.pk].amount = amount
                existing[ln.pk].save(update_fields=["amount"])
        else:
            ExpenseAllocation.objects.create(
                company_id=ctx.cid, expense=expense, order_id=ln.order_id, trip=trip,
                amount=amount, legacy_line=ln,
            )  # fmt: skip
    snap = _snapshot(ctx.company, total, trip.currency, day, ctx.settings)
    expense.amount, expense.expense_date = total, day
    for k, v in snap.items():
        setattr(expense, k, v)
    mismatch = total != quantize_money(trip.carrier_price)
    if mismatch:
        expense.needs_review, expense.review_reason = True, "migrated_mismatch"
    elif expense.review_reason == "migrated_mismatch":
        expense.needs_review, expense.review_reason = False, ""
    expense.save()
    audit.log("update", expense, None, audit.diff(before, audit.snapshot(expense)))


# --- заказ ------------------------------------------------------------------------------


def migrate_order(order, *, run=None, overwrite=False, dry_run=False) -> Result:
    """Идемпотентный перенос всех строк заказа. При dry_run ничего не пишется."""
    cid = current_cid(order.company_id)
    with transaction.atomic(), tenant_context(cid):
        if not dry_run:
            order = Order.all_objects.select_for_update().get(pk=order.pk)
        else:
            order = Order.all_objects.get(pk=order.pk)
        ctx = _Ctx(cid, run, overwrite, dry_run)
        lines = list(OrderService.objects.filter(order=order).order_by("pk"))
        group_titles: dict[str, list] = {}
        for line in lines:
            if line.income <= 0 and line.expense <= 0:
                ctx.count("lines_skipped_zero")
                if line.pk and overwrite:
                    _migrate_income(ctx, line, order)
                    _unlink_zero_expense(ctx, line)
                continue
            ctx.count("lines_total")
            key = (order.currency.code, f"{line.date:%Y-%m}")
            ctx.result.sources[key]["income"] += line.income
            ctx.result.sources[key]["expense"] += line.expense
            _migrate_income(ctx, line, order)
            if line.expense > 0:
                if is_trip_candidate(line):
                    group_titles.setdefault(line.title, []).append(line)
                else:
                    _migrate_manual(ctx, line, order)
            elif overwrite:
                _unlink_zero_expense(ctx, line)
        for title, mine in group_titles.items():
            _migrate_group(ctx, title, mine)
        return ctx.result


def _unlink_zero_expense(ctx: _Ctx, line) -> None:
    """Расход строки обнулён: долю зеркала снимаем (shadow, overwrite)."""
    if ctx.dry:
        return
    detach_expense_side(line, reason="legacy_line_zeroed")


# --- отвязка зеркала (удаление/обнуление строки) ------------------------------------------


def detach_expense_side(line, *, reason: str) -> None:
    alloc = ExpenseAllocation.objects.filter(legacy_line=line).select_related("expense").first()
    if alloc is None:
        return
    expense = Expense.objects.select_for_update().get(pk=alloc.expense_id)
    audit.log("delete", alloc, None, {"expense": expense.pk, "amount": str(alloc.amount),
              "legacy_line": line.pk, "reason": reason})  # fmt: skip
    alloc.delete()
    left = list(ExpenseAllocation.objects.filter(expense=expense))
    if expense.status == "void":
        return
    if not left:
        if expense.source == "migrated":
            expense.status, expense.void_reason = "void", reason
            expense.voided_at = timezone.now()
            expense.save()
            audit.log("update", expense, None, {"status": ["active", "void"], "reason": reason})
        return
    if expense.source == "migrated":
        total = quantize_money(sum((a.amount for a in left), Decimal("0")))
        before = audit.snapshot(expense)
        expense.amount = total
        if expense.fx_rate is not None:
            expense.base_amount = quantize_money(total * expense.fx_rate)
        if expense.trip_id:
            mismatch = total != quantize_money(expense.carrier_price_snapshot or 0)
            expense.needs_review = mismatch or expense.needs_review
            if mismatch:
                expense.review_reason = "migrated_mismatch"
        expense.save()
        audit.log("update", expense, None, audit.diff(before, audit.snapshot(expense)))


@transaction.atomic
def detach_line(line, *, reason: str = "legacy_line_deleted") -> None:
    """Перед удалением строки: зеркало отвязывается, история сохраняется (без ProtectedError)."""
    with tenant_context(current_cid(line.company_id)):
        income = Income.objects.select_for_update().filter(legacy_line=line).first()
        if income is not None:
            before = audit.snapshot(income)
            income.status, income.void_reason, income.legacy_line = "void", reason, None
            if income.recognized_on is None:
                income.recognized_on = None
            income.save()
            audit.log("update", income, None, {**audit.diff(before, audit.snapshot(income)),
                      "reason": reason})  # fmt: skip
        detach_expense_side(line, reason=reason)


# --- связи со счетами ------------------------------------------------------------------


def migrate_invoice_links(invoice: Invoice, *, dry_run: bool = False) -> Counter:
    """Связывает позиции активного счёта с перенесёнными Income / долями (идемпотентно)."""
    counters: Counter = Counter()
    cid = current_cid(invoice.company_id)
    with tenant_context(cid):
        if invoice.status == "cancelled" or invoice.deleted_at is not None:
            return counters
        for item in (
            InvoiceItem.objects.filter(invoice=invoice).select_related("line").order_by("pk")
        ):
            if item.line_id is None:
                counters["items_without_line"] += 1
                continue
            if invoice.direction == "out":
                income = Income.objects.filter(legacy_line_id=item.line_id).first()
                if income is None:
                    counters["links_missing_target"] += 1
                elif item.income_id == income.pk:
                    counters["links_existing"] += 1
                elif item.income_id is not None:
                    counters["links_conflict"] += 1
                else:
                    counters["links_created"] += 1
                    if not dry_run:
                        item.income = income
                        item.save(update_fields=["income"])
                        audit.log(
                            "update",
                            invoice,
                            None,
                            {
                                "item_income": [
                                    {"item": item.pk, "income": None},
                                    {"item": item.pk, "income": income.pk},
                                ]
                            },
                        )
            else:
                alloc = ExpenseAllocation.objects.filter(legacy_line_id=item.line_id).first()
                if alloc is None:
                    counters["links_missing_target"] += 1
                    continue
                link = ExpenseInvoiceAllocation.objects.filter(
                    expense_id=alloc.expense_id, invoice_item=item
                ).first()
                if link is not None:
                    counters["links_existing"] += 1
                    continue
                counters["links_created"] += 1
                if not dry_run:
                    link = ExpenseInvoiceAllocation.objects.create(
                        company_id=cid, expense_id=alloc.expense_id, invoice_item=item,
                        amount=quantize_money(item.amount_net),
                    )  # fmt: skip
                    audit.log("create", link, None, audit.diff({}, audit.snapshot(link)))
    return counters


# --- ручное разрешение спорных строк ---------------------------------------------------


RESOLUTIONS = ("carrier_expense", "manual_expense", "justified_exclusion")
MIN_JUSTIFICATION = 10


def _find_trip(value):
    if isinstance(value, Trip):
        return value
    if isinstance(value, bool) or value in (None, ""):
        raise FinanceError("trip_required", "Укажите рейс (id или номер)")
    trip = (
        Trip.objects.filter(pk=value).first()
        if isinstance(value, int)
        else Trip.objects.filter(number=str(value).strip()).first()
    )
    if trip is None:
        raise FinanceError("trip_not_found", f"Рейс {value} не найден в компании", status_code=404)
    return trip


def _find_category(value):
    qs = HandbookValue.objects.filter(handbook__code="expense_category", is_active=True)
    if value in (None, ""):
        value = "OTHER"
    if isinstance(value, HandbookValue):
        value = value.pk
    found = qs.filter(pk=value).first() if isinstance(value, int) else None
    found = found or qs.filter(code=str(value)).first() or qs.filter(name=str(value)).first()
    if found is None:
        raise FinanceError("category_not_found", f"Категория расходов {value} не найдена")
    return found


def _line_for(issue) -> OrderService:
    line = OrderService.objects.filter(pk=issue.source_id).select_related("order").first()
    if issue.source_model != SOURCE_MODEL or line is None:
        raise FinanceError("line_not_found", "Строка заказа проблемы не найдена")
    return line


def _apply_carrier(ctx: _Ctx, line, trip_id: int) -> None:
    """Доля строки в ОДНОМ расходе перевозчика рейса (создать или дополнить своим же расходом)."""
    trip = Trip.objects.select_for_update().filter(pk=trip_id).first()
    if trip is None:
        raise FinanceError("trip_not_found", "Рейс не найден", status_code=404)
    if trip.carrier_id is None:
        raise FinanceError(
            "resolution_impossible",
            "У рейса нет перевозчика: выберите другой вариант (ручной расход или исключение)",
        )
    order = Order.all_objects.get(pk=line.order_id)
    if order.currency_id != trip.currency_id:
        raise FinanceError(
            "resolution_impossible",
            "Валюта заказа отличается от валюты рейса: выберите другой вариант",
        )
    alloc = ExpenseAllocation.objects.filter(legacy_line=line).select_related("expense").first()
    amount = quantize_money(line.expense)
    key = f"resolved-trip:{trip.pk}"
    if alloc is not None:
        if alloc.expense.trip_id != trip.pk or alloc.expense.kind != "carrier_transport":
            raise FinanceError(
                "resolution_impossible", "Строка уже перенесена в другой расход", status_code=409
            )
        if ctx.overwrite and alloc.amount != amount and not ctx.dry:
            diff = amount - alloc.amount
            alloc.amount = amount
            alloc.save(update_fields=["amount"])
            _resum(ctx, alloc.expense, alloc.expense.amount + diff, trip)
        ctx.count("resolved_carrier_existing")
        return
    expense = (
        Expense.objects.select_for_update()
        .filter(trip=trip, kind="carrier_transport", status="active")
        .first()
    )
    if expense is not None and expense.legacy_group_key != key:
        raise FinanceError(
            "resolution_impossible",
            "На рейс уже есть другой расход перевозчика: выберите другой вариант "
            "(ручной расход или обоснованное исключение)",
            status_code=409,
        )
    ctx.count("resolved_carrier_applied")
    if ctx.dry:
        return
    if expense is None:
        snap = _snapshot(ctx.company, amount, trip.currency, line.date, ctx.settings)
        mismatch = amount != quantize_money(trip.carrier_price)
        expense = Expense(
            company_id=ctx.cid, kind="carrier_transport", title=f"Перевозка {trip.number}"[:255],
            category=ctx.category, amount=amount, currency_id=trip.currency_id,
            expense_date=line.date, status="active", source="migrated", trip=trip,
            carrier_id=trip.carrier_id, legacy_group_key=key,
            carrier_price_snapshot=quantize_money(trip.carrier_price),
            requires_full_allocation=True, needs_review=mismatch,
            review_reason="migrated_mismatch" if mismatch else "", **snap,
        )  # fmt: skip
        expense.save()
        audit.log("create", expense, None, {**audit.diff({}, audit.snapshot(expense)),
                  "legacy_lines": [line.pk], "source": "resolve_issue"})  # fmt: skip
        total = None
    else:
        total = expense.amount + amount
    ExpenseAllocation.objects.create(
        company_id=ctx.cid, expense=expense, order_id=line.order_id, trip=trip,
        amount=amount, legacy_line=line,
    )  # fmt: skip
    if total is not None:
        _resum(ctx, expense, total, trip, day=min(expense.expense_date, line.date))


def _resum(ctx: _Ctx, expense, total, trip, day=None) -> None:
    before = audit.snapshot(expense)
    total = quantize_money(total)
    day = day or expense.expense_date
    snap = _snapshot(ctx.company, total, trip.currency, day, ctx.settings)
    expense.amount, expense.expense_date = total, day
    for k, v in snap.items():
        setattr(expense, k, v)
    if total != quantize_money(trip.carrier_price):
        expense.needs_review, expense.review_reason = True, "migrated_mismatch"
    expense.save()
    audit.log("update", expense, None, audit.diff(before, audit.snapshot(expense)))


def _apply_manual(ctx: _Ctx, line, category_id: int) -> None:
    order = Order.all_objects.get(pk=line.order_id)
    key = f"line:{line.pk}"
    if (
        Expense.objects.filter(legacy_group_key=key).exists()
        or ExpenseAllocation.objects.filter(legacy_line=line).exists()
    ):
        ctx.count("resolved_manual_existing")
        return
    ctx.count("resolved_manual_applied")
    if ctx.dry:
        return
    category = HandbookValue.objects.get(pk=category_id)
    snap = _snapshot(ctx.company, line.expense, order.currency, line.date, ctx.settings)
    expense = Expense(
        company_id=ctx.cid, kind="other", title=line.title[:255], category=category,
        amount=quantize_money(line.expense), currency_id=order.currency_id,
        expense_date=line.date, status="active", source="migrated", legacy_group_key=key,
        requires_full_allocation=False, **snap,
    )  # fmt: skip
    expense.save()
    ExpenseAllocation.objects.create(
        company_id=ctx.cid, expense=expense, order=order,
        amount=quantize_money(line.expense), legacy_line=line,
    )  # fmt: skip
    audit.log("create", expense, None, {**audit.diff({}, audit.snapshot(expense)),
              "legacy_line": line.pk, "source": "resolve_issue"})  # fmt: skip


def apply_resolution(ctx: _Ctx, line, issue) -> None:
    """Применяет СОХРАНЁННОЕ решение к строке (идемпотентно: есть объекты - no-op)."""
    data = issue.resolution_data or {}
    if issue.resolution == "carrier_expense":
        _apply_carrier(ctx, line, data["trip"])
    elif issue.resolution == "manual_expense":
        _apply_manual(ctx, line, data["category"])


@transaction.atomic
def resolve_issue(
    issue: FinanceMigrationIssue, user, note: str, resolution: str | None = None, **params
) -> FinanceMigrationIssue:
    """Ручное разрешение. Спорная строка (ambiguous_trip_expense) требует РЕШЕНИЯ человека:
    carrier_expense (trip=id|номер), manual_expense (category=код|id, по умолчанию OTHER) или
    justified_exclusion (содержательный комментарий; сумма остаётся не отражённой в сверке).
    Для остальных типов проблем достаточно комментария."""
    note = (note or "").strip()
    if not note:
        raise FinanceError("note_required", "Укажите комментарий к ручному разрешению")
    cid = current_cid(issue.company_id)
    with tenant_context(cid):
        locked = FinanceMigrationIssue.objects.select_for_update().get(pk=issue.pk)
        if locked.status == "resolved":
            return locked
        data: dict = {}
        if locked.issue_type == ISSUE_TRIP:
            if resolution not in RESOLUTIONS:
                raise FinanceError(
                    "resolution_required",
                    "Выберите решение: carrier_expense, manual_expense или justified_exclusion",
                )
            line = _line_for(locked)
            ctx = _Ctx(cid, None, False, False)
            if resolution == "justified_exclusion":
                if len(note) < MIN_JUSTIFICATION:
                    raise FinanceError(
                        "justification_required",
                        f"Для исключения опишите причину подробнее (не менее {MIN_JUSTIFICATION} символов)",
                    )
            elif resolution == "carrier_expense":
                trip = _find_trip(params.get("trip"))
                data = {"trip": trip.pk}
                _apply_carrier(ctx, line, trip.pk)
            else:
                category = _find_category(params.get("category"))
                data = {"category": category.pk}
                _apply_manual(ctx, line, category.pk)
        elif resolution is not None:
            raise FinanceError(
                "resolution_unsupported", "Для этого типа проблем решение не требуется"
            )
        locked.status = "resolved"
        locked.resolved_by = user if getattr(user, "pk", None) else None
        locked.resolved_at = timezone.now()
        locked.resolution_note = note
        locked.resolution = resolution or ""
        locked.resolution_data = data
        locked.save()
        audit.log(
            "update",
            locked,
            user,
            {"status": ["open", "resolved"], "note": note, "resolution": resolution, "data": data},
        )
        return locked
