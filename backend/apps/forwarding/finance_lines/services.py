"""Строки заказа и прибыль.

Прибыль заказа = Σ доходов - Σ расходов его строк (OrderService), маржа = прибыль / выручка ×
100 (округление ROUND_HALF_UP до 2 знаков; None при нулевой выручке). Итоги считает БД
(Sum + Coalesce в подзапросе: строки заказа не умножаются и N+1 нет).

Базовая строка «Начальная ставка» (is_base) всегда одна на заказ: sync_base_line вызывается при
создании заказа и при каждой смене Order.client_rate; через API она только читается.

Известное ограничение этапа 2: цены рейсов (Trip.price) со строками НЕ связаны - расходы на
перевозчиков вносятся вручную строками заказа до появления счетов перевозчиков (этап 3).
"""

from decimal import ROUND_HALF_UP, Decimal

from django.db.models import DecimalField, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from .models import OrderService, company_zone

BASE_TITLE = "Начальная ставка"
ZERO = Decimal("0.00")
_MONEY = DecimalField(max_digits=18, decimal_places=2)


def margin_pct(revenue: Decimal, profit: Decimal) -> Decimal | None:
    """profit / revenue × 100 с округлением до 2 знаков (ROUND_HALF_UP); None при revenue == 0."""
    if not revenue:
        return None
    return (profit / revenue * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def totals_from(revenue: Decimal, cost: Decimal) -> dict:
    profit = revenue - cost
    return {
        "revenue": revenue,
        "cost": cost,
        "profit": profit,
        "margin_pct": margin_pct(revenue, profit),
    }


def order_totals(order) -> dict:
    """{'revenue','cost','profit','margin_pct'} заказа (Decimal; margin_pct None при revenue 0)."""
    sums = OrderService.objects.filter(order=order).aggregate(
        revenue=Coalesce(Sum("income"), Value(ZERO), output_field=_MONEY),
        cost=Coalesce(Sum("expense"), Value(ZERO), output_field=_MONEY),
    )
    return totals_from(sums["revenue"], sums["cost"])


def annotate_order_totals(queryset):
    """Добавляет заказам revenue и cost подзапросами (без join: строки заказа не множатся)."""

    def total(field):
        per_order = (
            OrderService.objects.filter(order=OuterRef("pk"))
            .order_by()
            .values("order")
            .annotate(total=Sum(field))
            .values("total")
        )
        return Coalesce(Subquery(per_order, output_field=_MONEY), Value(ZERO), output_field=_MONEY)

    return queryset.annotate(revenue=total("income"), cost=total("expense"))


def attach_totals(order) -> None:
    """Выставляет заказу revenue/cost/profit/margin_pct (аннотация списка либо запрос)."""
    if not hasattr(order, "revenue") or not hasattr(order, "cost"):
        order.revenue, order.cost = (order_totals(order)[k] for k in ("revenue", "cost"))
    order.profit = order.revenue - order.cost
    order.margin_pct = margin_pct(order.revenue, order.profit)


def forget_totals(order) -> None:
    """Сбрасывает закэшированные на объекте итоги (после правки строк или ставки)."""
    for name in ("revenue", "cost", "profit", "margin_pct"):
        order.__dict__.pop(name, None)


def sync_base_line(order) -> OrderService:
    """Создаёт или обновляет базовую строку заказа: income = client_rate, expense = 0.

    Дата строки - дата создания заказа в часовом поясе компании; при обновлении сохраняется.
    """
    line = OrderService.objects.filter(order=order, is_base=True).first()
    if line is None:
        created = order.created_at.astimezone(company_zone(order.company_id)).date()
        return OrderService.objects.create(
            order=order,
            title=BASE_TITLE,
            income=order.client_rate,
            expense=ZERO,
            date=created,
            is_base=True,
        )
    if line.income != order.client_rate or line.expense != 0:
        line.income, line.expense = order.client_rate, ZERO
        line.save(update_fields=["income", "expense", "updated_at"])
    return line
