"""Хуки существующего кода (заказы, рейсы) в новую финансовую архитектуру.

Активны ТОЛЬКО при settings.engine == 'new'. Для engine legacy/shadow ничего не делают, поэтому
поведение текущих компаний не меняется. В engine='new' ошибка финансовой записи ПРОБРАСЫВАЕТСЯ
и откатывает основную операцию (хуки вызываются внутри её транзакции).
"""

from apps.core.tenancy import tenant_context
from apps.forwarding.models import Order

from . import income, shadow
from .engine import company_engine, current_cid, engine_is_new
from .models import CompanyFinancialSettings


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
