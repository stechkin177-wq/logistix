"""Хуки существующего кода (заказы, рейсы) в новую финансовую архитектуру.

Активны ТОЛЬКО при settings.engine == 'new'. Для engine legacy/shadow ничего не делают, поэтому
поведение текущих компаний не меняется. В engine='new' ошибка финансовой записи ПРОБРАСЫВАЕТСЯ
и откатывает основную операцию (хуки вызываются внутри её транзакции).
"""

from apps.core.tenancy import tenant_context
from apps.forwarding.models import Order

from . import income, shadow
from .engine import company_engine, current_cid, engine_is_new
from .errors import FinanceError
from .models import (
    CompanyFinancialSettings,
    Expense,
    ExpenseAllocation,
    Income,
    Invoice,
)


def _order_ids_of_trip(trip) -> set[int]:
    return set(
        trip.consignments.filter(order__deleted_at__isnull=True).values_list("order_id", flat=True)
    )


def after_order_saved(order, user=None) -> None:
    """Создание заказа или смена client_rate: плановый доход перевозки."""
    cid = current_cid(order.company_id)
    engine = company_engine(cid)
    if engine == "new":
        income.sync_planned_freight(order, user=user)
    elif engine == "shadow":
        shadow.mirror_order(order, "order_saved")


def after_line_saved(line) -> None:
    """Строка заказа создана или изменена (API): Shadow-зеркало заказа."""
    shadow.mirror_order(line.order, "order_line_saved")


def before_line_delete(line) -> None:
    shadow.before_line_delete(line)


def after_line_deleted(order) -> None:
    """После удаления строки: обновить остальные строки группы расходов рейса."""
    shadow.mirror_order(order, "order_line_deleted")


def after_trip_changed(trip, user=None, *, perms=(), reason=None, extra_order_ids=()) -> None:
    """Статус или состав рейса изменились: пересчёт признания по заказам рейса."""
    cid = current_cid(trip.company_id)
    if not engine_is_new(cid):
        return
    ids = _order_ids_of_trip(trip) | set(extra_order_ids)
    with tenant_context(cid):
        for order in Order.all_objects.filter(pk__in=sorted(ids)).order_by("pk"):
            income.reconcile_order_income(
                order,
                user=user,
                can_adjust="finance.adjust_closed" in perms,
                reason=reason,
            )


def after_consignment_changed(consignment, user=None, *, perms=(), reason=None) -> None:
    """Событие, передача или участки груза изменились: пересчёт признания дохода его заказа."""
    cid = current_cid(consignment.company_id)
    if not engine_is_new(cid):
        return
    with tenant_context(cid):
        order = Order.all_objects.get(pk=consignment.order_id)
        income.reconcile_order_income(
            order, user=user, can_adjust="finance.adjust_closed" in perms, reason=reason
        )


def after_trip_price_changed(trip, old_price, user=None, *, perms=(), reason=None) -> None:
    """Цена рейса изменилась: корректировка существующего расхода (второй не создаётся)."""
    from . import expenses

    if old_price == trip.carrier_price:
        return
    cid = current_cid(trip.company_id)
    row = settings_row(cid)
    if row is None or row.engine != "new" or not row.sync_carrier_price:
        return
    expenses.sync_trip_expense(
        trip, user=user, can_adjust="finance.adjust_closed" in perms, reason=reason
    )


def settings_row(company_id: int) -> CompanyFinancialSettings | None:
    with tenant_context(company_id):
        return CompanyFinancialSettings.objects.filter(company_id=company_id).first()


# --- удаление, восстановление, смена валюты (только engine=new, этап 1.5-E3) ---
# Консервативно: если удаление изменило бы деньги (расход рейса, признанный доход, доли расходов,
# счета), оно блокируется понятной ошибкой 409; ничего не пересчитывается молча.


def before_trip_delete(trip) -> None:
    """Рейс с активным расходом перевозчику в корзину не уходит: сначала аннулируйте расход."""
    cid = current_cid(trip.company_id)
    if not engine_is_new(cid):
        return
    with tenant_context(cid):
        if Expense.objects.filter(trip=trip, kind="carrier_transport", status="active").exists():
            raise FinanceError(
                "trip_has_expense",
                "Нельзя удалить рейс: по нему создан активный расход перевозчику. "
                "Сначала аннулируйте расход в разделе «Финансы»",
                status_code=409,
            )


def after_trip_deleted(trip, user=None, *, perms=()) -> None:
    """Рейс удалён: состав действующих рейсов заказов изменился, признание пересчитывается."""
    after_trip_changed(trip, user, perms=perms, reason="Рейс удалён")


def trip_restore_blocker(trip) -> str | None:
    """Восстановление рейса при engine=new: участки не должны конфликтовать с участками,
    назначенными на другие рейсы за время удаления (иначе груз окажется на двух рейсах сразу)."""
    from apps.forwarding.trips import legs as leg_rules

    cid = current_cid(trip.company_id)
    if not engine_is_new(cid):
        return None
    from apps.forwarding.models import Consignment, TripConsignment

    with tenant_context(cid):
        by_consignment: dict[int, list] = {}
        for link in (
            TripConsignment.objects.filter(trip=trip)
            .exclude(status=TripConsignment.CANCELLED)
            .select_related("from_stop", "to_stop")
        ):
            by_consignment.setdefault(link.consignment_id, []).append(link)
        for pk, group in by_consignment.items():
            consignment = Consignment.objects.filter(pk=pk).first()
            if consignment is None:
                continue
            specs = [
                leg_rules.LegSpec(
                    consignment,
                    link.from_stop,
                    link.to_stop,
                    link.weight_kg,
                    link.volume_m3,
                    link.pallets,
                    legacy=link.from_stop_id is None
                    or (link.weight_kg is None and link.volume_m3 is None and link.pallets is None),
                )
                for link in group
            ]
            try:
                leg_rules.check_consignment_legs(consignment, specs, exclude_trip_id=trip.pk)
            except Exception:  # noqa: BLE001 - ValidationError правил участков
                return (
                    "Нельзя восстановить рейс: его участки пересекаются с участками других рейсов, "
                    "назначенных после удаления"
                )
    return None


def after_trip_restored(trip, user=None) -> None:
    after_trip_changed(trip, user, reason="Рейс восстановлен")


def before_order_delete(order, user=None) -> None:
    """Заказ с признанным доходом, активными долями расходов или счетами не удаляется (409);
    плановые доходы заказа без счетов аннулируются (void) в той же транзакции."""
    cid = current_cid(order.company_id)
    if not engine_is_new(cid):
        return
    with tenant_context(cid):
        recognized = Income.objects.filter(order=order, status="recognized").exists()
        shares = ExpenseAllocation.objects.filter(order=order, expense__status="active").exists()
        invoices = Invoice.objects.filter(order=order).exclude(status="cancelled").exists()
        if recognized or shares or invoices:
            raise FinanceError(
                "order_has_finance",
                "Нельзя удалить заказ: по нему есть признанный доход, доли расходов или активные "
                "счета. Сначала аннулируйте или отмените их в разделе «Финансы»",
                status_code=409,
            )
        for planned in Income.objects.filter(order=order, status="planned").order_by("pk"):
            income.void_income(planned, "Заказ удалён", user)


def after_order_restored(order, user=None) -> None:
    """Заказ восстановлен: плановый доход перевозки создаётся заново (прежний был аннулирован),
    признание пересчитывается по текущему состоянию рейсов."""
    cid = current_cid(order.company_id)
    if not engine_is_new(cid):
        return
    income.sync_planned_freight(order, user=user)
    with tenant_context(cid):
        income.reconcile_order_income(order, user=user, reason="Заказ восстановлен")


def trip_currency_blocker(trip, new_currency_id) -> None:
    """Смена валюты рейса при активном расходе перевозчику запрещена (молчаливой синхронизации
    нет): сначала аннулируйте расход."""
    cid = current_cid(trip.company_id)
    if not engine_is_new(cid) or trip.currency_id == new_currency_id:
        return
    with tenant_context(cid):
        if Expense.objects.filter(trip=trip, kind="carrier_transport", status="active").exists():
            raise FinanceError(
                "trip_currency_locked",
                "Нельзя изменить валюту рейса: по нему есть активный расход перевозчику. "
                "Сначала аннулируйте расход",
                status_code=409,
            )
