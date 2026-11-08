"""Доходы (Income): плановый доход заказа, признание, возврат, услуги, корректировка.

Принцип начисления (правило R-1, Master Spec §6.3.1 в редакции v1.1). Доход перевозки заказа
признаётся ТОЛЬКО при одновременном выполнении:
(а) каждому действующему грузу назначены рейсы на все отрезки маршрута (fully_assigned);
(б) ВСЕ действующие рейсы заказа завершены (статус = CompanyFinancialSettings.completed_status и
    заполнен completed_at);
(в) последняя остановка каждого груза выполнена: она в статусе done ИЛИ участок, заканчивающийся
    на ней, завершён (для двухточечных грузов это то же завершение рейса: прежнее поведение).
Предикат один (recognition_state, income_recognition_ready/blockers) и служит и признанию, и
возврату. Дата признания - дата (в часовом поясе компании) последнего события: завершения
последнего рейса или фиксации последней доставки. Рейс с системным кодом CANCELLED и удалённый
рейс не считаются. Признание идемпотентно: второго дохода не создаётся.
Услуги признаются отдельно: после mark_service_delivered и confirm_service.

Порядок блокировок: Order -> Trip -> Income -> (доли) -> Invoice -> Payment. Engine сервисы не
проверяют (см. engine.py и hooks.py). Права и причины приходят параметрами от API-слоя.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.audit import services as audit
from apps.core.tenancy import tenant_context
from apps.forwarding.models import Consignment, ConsignmentPoint, Order, Trip, TripConsignment
from apps.forwarding.trips.legs import route_coverage

from . import periods
from .engine import current_cid, local_date
from .errors import FinanceError
from .fx import fx_snapshot, get_settings
from .models import Income, IncomeTrip
from .money import quantize_money

FREIGHT_CATEGORY = "Перевозка"
CANCELLED_CODE = "CANCELLED"
FX_FIELDS = ("fx_base_currency", "fx_rate", "fx_rate_date", "fx_rate_source", "base_amount")


def _money(value, field="amount") -> Decimal:
    try:
        amount = quantize_money(Decimal(str(value)))
    except Exception:  # noqa: BLE001
        raise FinanceError("amount_invalid", f"{field}: некорректная сумма") from None
    if amount < 0:
        raise FinanceError("amount_invalid", f"{field}: сумма не может быть отрицательной")
    return amount


def _lock_order(order: Order) -> Order:
    return Order.all_objects.select_for_update().get(pk=order.pk)


def _state(income: Income) -> dict:
    return {
        "status": income.status,
        "amount": str(income.amount),
        "recognized_on": income.recognized_on.isoformat() if income.recognized_on else None,
        "base_amount": str(income.base_amount) if income.base_amount is not None else None,
    }


def active_trips(order: Order, *, lock: bool = False) -> list[Trip]:
    """Действующие рейсы заказа: не удалённые, не с системным кодом CANCELLED."""
    trip_ids = TripConsignment.objects.filter(
        consignment__order=order, consignment__deleted_at__isnull=True
    ).values("trip_id")
    qs = (
        Trip.objects.filter(pk__in=trip_ids)
        .exclude(status__code=CANCELLED_CODE)
        .select_related("status")
        .order_by("pk")
    )
    if lock:
        qs = qs.select_for_update(of=("self",))
    return list(qs)


def completion_state(order: Order, settings, *, lock: bool = False):
    """(выполнено?, действующие рейсы). Не выполнено, если рейсов нет или не все завершены."""
    if settings.completed_status_id is None:
        raise FinanceError(
            "completed_status_missing",
            "Не сопоставлен статус рейса «Завершён» (completed_status)",
            status_code=409,
        )
    trips = active_trips(order, lock=lock)
    done = bool(trips) and all(
        t.status_id == settings.completed_status_id and t.completed_at is not None for t in trips
    )
    return done, trips


@dataclass
class RecognitionState:
    """Итог проверки R-1: готовность, причины отказа, действующие рейсы, времена доставок."""

    ready: bool
    blockers: list[dict] = field(default_factory=list)
    trips: list[Trip] = field(default_factory=list)
    delivered_at: list = field(default_factory=list)  # done_at последних остановок (если есть)

    def recognized_on(self, cid: int) -> date:
        """Дата последнего события: завершения последнего рейса или фиксации доставки."""
        days = [local_date(t.completed_at, cid) for t in self.trips if t.completed_at]
        days += [local_date(moment, cid) for moment in self.delivered_at]
        return max(days)

    def last_trip(self) -> Trip:
        return max((t for t in self.trips), key=lambda t: (t.completed_at, t.pk))


def _trip_completed(trip: Trip, settings) -> bool:
    return trip.status_id == settings.completed_status_id and trip.completed_at is not None


def _consignment_blockers(consignment, settings, delivered_at: list) -> list[dict]:
    """Причины, по которым груз не готов к признанию: отрезки без рейса, не доставлен."""
    links = [
        link
        for link in TripConsignment.objects.filter(
            consignment=consignment, trip__deleted_at__isnull=True
        )
        .exclude(status=TripConsignment.CANCELLED)
        .exclude(trip__status__code=CANCELLED_CODE)
        .select_related("trip", "from_stop", "to_stop")
    ]
    stops = list(ConsignmentPoint.objects.filter(consignment=consignment).order_by("seq", "id"))
    blockers = []
    if len(stops) >= 2:
        uncovered = route_coverage(consignment, legs=links)["uncovered"]
        if uncovered:
            blockers.append(
                {
                    "code": "route_not_assigned",
                    "consignment": consignment.pk,
                    "segments": [[s["from_seq"], s["to_seq"]] for s in uncovered],
                }
            )
    elif not links:  # груз без маршрута: достаточно любого действующего участка
        blockers.append(
            {"code": "route_not_assigned", "consignment": consignment.pk, "segments": []}
        )
    last = stops[-1] if stops else None
    if last is not None and last.status == ConsignmentPoint.DONE:
        if last.done_at is not None:
            delivered_at.append(last.done_at)
        return blockers
    for link in links:
        ends_last = last is None or link.to_stop_id is None or link.to_stop_id == last.pk
        if ends_last and (
            link.status == TripConsignment.DONE or _trip_completed(link.trip, settings)
        ):
            return blockers
    code = (
        "in_storage" if consignment.location_status == Consignment.IN_STORAGE else "not_delivered"
    )
    blockers.append({"code": code, "consignment": consignment.pk})
    return blockers


def recognition_state(order: Order, settings, *, lock: bool = False) -> RecognitionState:
    """Единый предикат R-1 для признания и возврата дохода (см. docstring модуля)."""
    if settings.completed_status_id is None:
        raise FinanceError(
            "completed_status_missing",
            "Не сопоставлен статус рейса «Завершён» (completed_status)",
            status_code=409,
        )
    trips = active_trips(order, lock=lock)
    blockers: list[dict] = []
    if not trips:
        blockers.append({"code": "no_active_trips"})
    else:
        open_trips = [t.pk for t in trips if not _trip_completed(t, settings)]
        if open_trips:
            blockers.append({"code": "trips_not_completed", "trips": open_trips})
    delivered_at: list = []
    consignments = list(Consignment.objects.filter(order=order).order_by("pk"))
    if not consignments:
        blockers.append({"code": "no_consignments"})
    for consignment in consignments:
        blockers += _consignment_blockers(consignment, settings, delivered_at)
    return RecognitionState(not blockers, blockers, trips, delivered_at)


def income_recognition_blockers(order: Order, settings, *, lock: bool = False) -> list[dict]:
    """Список причин, мешающих признать доход (пусто - можно признавать)."""
    return recognition_state(order, settings, lock=lock).blockers


def income_recognition_ready(order: Order, settings, *, lock: bool = False) -> bool:
    return recognition_state(order, settings, lock=lock).ready


def _freight(order: Order, *, lock: bool = True) -> Income | None:
    qs = Income.objects.filter(order=order, kind="freight").exclude(status="void")
    if lock:
        qs = qs.select_for_update()
    return qs.first()


# --- плановый доход ------------------------------------------------------------------------


@transaction.atomic
def sync_planned_freight(order: Order, *, user=None) -> Income:
    """Один planned freight Income заказа: сумма = client_rate, валюта = валюта заказа.

    Пока доход planned - следует за client_rate; признанный (recognized) не меняется."""
    cid = current_cid(order.company_id)
    with tenant_context(cid):
        periods.assert_finance_writable(cid)
        order = _lock_order(order)
        income = _freight(order)
        if income is None:
            income = Income(
                company_id=cid,
                order=order,
                kind="freight",
                title=f"Перевозка {order.number}",
                category=FREIGHT_CATEGORY,
                amount=quantize_money(order.client_rate),
                currency_id=order.currency_id,
                status="planned",
                created_by=user if getattr(user, "pk", None) else None,
            )
            income.save()
            audit.log("create", income, user, audit.diff({}, audit.snapshot(income)))
            return income
        if income.status == "planned" and (
            income.amount != quantize_money(order.client_rate)
            or income.currency_id != order.currency_id
        ):
            before = audit.snapshot(income)
            income.amount = quantize_money(order.client_rate)
            income.currency_id = order.currency_id
            income.save()
            audit.log("update", income, user, audit.diff(before, audit.snapshot(income)))
        return income


# --- признание и возврат ---------------------------------------------------------------------


def _set_trips(income: Income, trips: list[Trip]) -> list[int]:
    """IncomeTrip = ровно завершившие рейсы; возвращает прежний список id (для аудита)."""
    old = sorted(IncomeTrip.objects.filter(income=income).values_list("trip_id", flat=True))
    new = sorted(t.pk for t in trips)
    IncomeTrip.objects.filter(income=income).exclude(trip_id__in=new).delete()
    for trip in trips:
        IncomeTrip.objects.get_or_create(company_id=income.company_id, income=income, trip=trip)
    return old


@transaction.atomic
def recognize_order_income(order: Order, *, user=None, now=None) -> Income | None:
    """Признаёт доход перевозки, если все действующие рейсы заказа завершены; иначе no-op."""
    cid = current_cid(order.company_id)
    with tenant_context(cid):
        periods.assert_finance_writable(cid)
        order = _lock_order(order)
        settings = get_settings_for(cid)
        state = recognition_state(order, settings, lock=True)
        income = _freight(order)
        if not state.ready:
            return income
        trips = state.trips
        if income is not None and income.status == "recognized":
            return income  # повторный вызов: ничего не меняется
        if income is None:
            income = sync_planned_freight(order, user=user)
            income = _freight(order)
        recognized_on = state.recognized_on(cid)
        last_trip = state.last_trip()
        periods.assert_period_open(cid, recognized_on)  # системное событие: только период
        snapshot = fx_snapshot(
            cid_company(cid), income.amount, income.currency, recognized_on, settings
        )
        before = _state(income)
        income.status = "recognized"
        income.recognized_on = recognized_on
        income.recognition_basis = "trip_completed"
        income.trip = last_trip
        for key, value in snapshot.items():
            setattr(income, key, value)
        income.save()
        old_trips = _set_trips(income, trips)
        audit.log(
            "update",
            income,
            user,
            {
                "recognition": [before, _state(income)],
                "trips": [old_trips, sorted(t.pk for t in trips)],
            },
        )
        return income


@transaction.atomic
def unrecognize_order_income(
    order: Order, *, user=None, can_adjust: bool = False, reason: str | None = None
) -> Income | None:
    """Возвращает признанный доход в planned, если условие признания больше не выполняется."""
    cid = current_cid(order.company_id)
    with tenant_context(cid):
        periods.assert_finance_writable(cid)
        order = _lock_order(order)
        settings = get_settings_for(cid)
        ready = recognition_state(order, settings, lock=True).ready
        income = _freight(order)
        if income is None or income.status != "recognized" or ready:
            return income
        adjusted = periods.assert_period_open(
            cid, income.recognized_on, can_adjust=can_adjust, reason=reason
        )
        before = _state(income)
        old_trips = sorted(
            IncomeTrip.objects.filter(income=income).values_list("trip_id", flat=True)
        )
        income.status = "planned"
        income.recognized_on = None
        income.recognition_basis = ""
        income.trip = None
        income.fx_base_currency = None
        income.fx_rate = None
        income.fx_rate_date = None
        income.fx_rate_source = ""
        income.base_amount = None
        income.save()
        changes = {"recognition": [before, _state(income)], "trips": [old_trips, old_trips]}
        if reason:
            changes["reason"] = reason.strip()
        if adjusted:
            changes.update(periods.adjustment_changes(reason, before, _state(income)))
        audit.log("update", income, user, changes)
        return income


def reconcile_order_income(
    order: Order, *, user=None, can_adjust: bool = False, reason: str | None = None
) -> Income | None:
    """Признаёт или возвращает доход заказа по текущему состоянию его рейсов."""
    income = recognize_order_income(order, user=user)
    if income is not None and income.status == "recognized":
        unrecognized = unrecognize_order_income(
            order, user=user, can_adjust=can_adjust, reason=reason
        )
        return unrecognized
    return income


# --- услуги ----------------------------------------------------------------------------------


@transaction.atomic
def plan_service(order: Order, title: str, category: str, amount, user) -> Income:
    title = (title or "").strip()
    if not title:
        raise FinanceError("title_required", "Укажите название услуги")
    cid = current_cid(order.company_id)
    with tenant_context(cid):
        periods.assert_finance_writable(cid)
        order = _lock_order(order)
        income = Income(
            company_id=cid,
            order=order,
            kind="service",
            title=title,
            category=(category or "")[:64],
            amount=_money(amount),
            currency_id=order.currency_id,
            status="planned",
            created_by=user if getattr(user, "pk", None) else None,
        )
        income.save()
        audit.log("create", income, user, audit.diff({}, audit.snapshot(income)))
        return income


def _locked_service(income: Income) -> Income:
    locked = Income.objects.select_for_update().get(pk=income.pk)
    if locked.kind != "service":
        raise FinanceError("income_not_service", "Это не дополнительная услуга")
    return locked


@transaction.atomic
def mark_service_delivered(
    income: Income, delivered_on: date, user, perms=(), adjust_reason: str | None = None
) -> Income:
    """Фактическое оказание услуги; дата вводится пользователем (правила 1.4.3)."""
    cid = current_cid(income.company_id)
    with tenant_context(cid):
        periods.assert_finance_writable(cid)
        Order.all_objects.select_for_update().get(pk=income.order_id)
        locked = _locked_service(income)
        if locked.status != "planned":
            raise FinanceError(
                "income_not_planned", "Оказание можно отметить только у запланированной услуги",
                status_code=409,
            )  # fmt: skip
        adjusted = periods.check_user_date(cid, delivered_on, perms, adjust_reason)
        before = locked.delivered_on
        locked.delivered_on = delivered_on
        locked.save()
        changes = {
            "delivered_on": [before.isoformat() if before else None, delivered_on.isoformat()]
        }
        if adjusted:
            changes.update(
                periods.adjustment_changes(
                    adjust_reason, before and before.isoformat(), delivered_on.isoformat()
                )
            )
        audit.log("update", locked, user, changes)
        return locked


@transaction.atomic
def confirm_service(income: Income, user, perms=(), adjust_reason: str | None = None) -> Income:
    """Подтверждение оказанной услуги: признание на дату оказания (принцип начисления)."""
    cid = current_cid(income.company_id)
    with tenant_context(cid):
        periods.assert_finance_writable(cid)
        Order.all_objects.select_for_update().get(pk=income.order_id)
        locked = _locked_service(income)
        if locked.status == "recognized":
            return locked  # идемпотентно
        if locked.status != "planned":
            raise FinanceError("income_not_planned", "Услуга аннулирована", status_code=409)
        if locked.delivered_on is None:
            raise FinanceError(
                "service_not_delivered", "Сначала отметьте фактическое оказание услуги",
                status_code=409,
            )  # fmt: skip
        adjusted = periods.check_system_date(cid, locked.delivered_on, perms, adjust_reason)
        settings = get_settings_for(cid)
        snapshot = fx_snapshot(
            cid_company(cid), locked.amount, locked.currency, locked.delivered_on, settings
        )
        before = _state(locked)
        locked.status = "recognized"
        locked.recognized_on = locked.delivered_on
        locked.recognition_basis = "service_confirmed"
        locked.confirmed_by = user if getattr(user, "pk", None) else None
        locked.confirmed_at = timezone.now()
        for key, value in snapshot.items():
            setattr(locked, key, value)
        locked.save()
        changes = {"recognition": [before, _state(locked)]}
        if adjusted:
            changes.update(periods.adjustment_changes(adjust_reason, before, _state(locked)))
        audit.log("update", locked, user, changes)
        return locked


# --- корректировка и аннулирование ---------------------------------------------------------


@transaction.atomic
def adjust_recognized_income(
    income: Income, new_amount, *, user, reason: str, can_adjust: bool = False
) -> Income:
    """Меняет сумму признанного дохода; курс снимка сохраняется, base_amount пересчитывается."""
    reason = (reason or "").strip()
    if not reason:
        raise FinanceError("reason_required", "Укажите причину корректировки дохода")
    amount = _money(new_amount, "new_amount")
    cid = current_cid(income.company_id)
    with tenant_context(cid):
        periods.assert_finance_writable(cid)
        Order.all_objects.select_for_update().get(pk=income.order_id)
        locked = Income.objects.select_for_update().get(pk=income.pk)
        if locked.status != "recognized":
            raise FinanceError(
                "income_not_recognized", "Корректировать можно только признанный доход",
                status_code=409,
            )  # fmt: skip
        adjusted = periods.assert_period_open(
            cid, locked.recognized_on, can_adjust=can_adjust, reason=reason
        )
        before = _state(locked)
        locked.amount = amount
        if locked.fx_rate is not None:
            locked.base_amount = quantize_money(amount * locked.fx_rate)
        locked.save()
        changes = {"adjustment": [before, _state(locked)], "reason": reason}
        if adjusted:
            changes.update(periods.adjustment_changes(reason, before, _state(locked)))
        audit.log("update", locked, user, changes)
        return locked


@transaction.atomic
def void_income(income: Income, reason: str, user) -> Income:
    reason = (reason or "").strip()
    if not reason:
        raise FinanceError("reason_required", "Укажите причину аннулирования дохода")
    cid = current_cid(income.company_id)
    with tenant_context(cid):
        periods.assert_finance_writable(cid)
        Order.all_objects.select_for_update().get(pk=income.order_id)
        locked = Income.objects.select_for_update().get(pk=income.pk)
        if locked.status != "planned":
            raise FinanceError(
                "income_not_planned", "Аннулировать можно только запланированный доход",
                status_code=409,
            )  # fmt: skip
        before = _state(locked)
        locked.status = "void"
        locked.void_reason = reason
        locked.save()
        audit.log("update", locked, user, {"status": [before["status"], "void"], "reason": reason})
        return locked


def cid_company(company_id: int):
    from apps.core.models import Company

    return Company.objects.get(pk=company_id)


def get_settings_for(company_id: int):
    return get_settings(cid_company(company_id))
