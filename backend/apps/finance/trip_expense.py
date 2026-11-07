"""Расход заказов рейса из цены рейса (ручное действие, ничего не создаётся автоматически)."""

from decimal import Decimal

from django.db import transaction

from apps.core.audit import services as audit
from apps.forwarding.finance_lines.models import OrderService
from apps.forwarding.orders.models import Order
from apps.forwarding.trips.models import Trip

from .errors import FinanceError
from .money import CENT, quantize_money

CATEGORY = "Перевозка"


def _title(trip: Trip) -> str:
    return f"Перевозка {trip.number}"


def _orders_of(trip: Trip) -> list[Order]:
    ids = trip.consignments.values_list("order_id", flat=True)
    return list(Order.objects.filter(pk__in=set(ids)).order_by("pk"))


def split_evenly(total: Decimal, count: int) -> list[Decimal]:
    """Поровну с точностью до копейки; остаток копеек уходит первым."""
    total = quantize_money(total)
    base = (total / count).quantize(CENT, rounding="ROUND_DOWN")
    parts = [base] * count
    extra = int((total - base * count) / CENT)
    for i in range(extra):
        parts[i] += CENT
    return parts


def trip_expense_lines(trip: Trip) -> dict:
    """Заказы рейса с уже существующими строками «Перевозка» и подсказкой деления поровну."""
    orders = _orders_of(trip)
    existing = {}
    for line in OrderService.objects.filter(
        order__in=orders, category=CATEGORY, title=_title(trip)
    ):
        existing.setdefault(line.order_id, []).append(line)
    suggestion = [
        {"order_id": o.pk, "amount": a}
        for o, a in zip(orders, split_evenly(trip.carrier_price, len(orders)) if orders else [])
    ]
    return {
        "trip": {
            "id": trip.pk,
            "number": trip.number,
            "price": trip.carrier_price,  # устаревший алиас carrier_price
            "carrier_price": trip.carrier_price,
        },
        "orders": [
            {
                "order_id": o.pk,
                "order_number": o.number,
                "lines": [
                    {"id": ln.pk, "title": ln.title, "expense": ln.expense}
                    for ln in existing.get(o.pk, [])
                ],
            }
            for o in orders
        ],
        "suggestion": suggestion,
    }


@transaction.atomic
def create_trip_expense(trip: Trip, allocations: list[dict], *, user) -> list[OrderService]:
    """Создаёт строки расхода «Перевозка» по заказам рейса; сумма = цене рейса."""
    # рейс блокируется: двойная отправка не создаст расход дважды (блокировка по строкам расхода
    # ничего не держит, пока их нет)
    trip = Trip.objects.select_for_update().get(pk=trip.pk)
    orders = {o.pk: o for o in _orders_of(trip)}
    seen = set()
    for item in allocations:
        order = orders.get(item["order_id"])
        if order is None:
            raise FinanceError("order_not_in_trip", "Заказ не входит в рейс")
        if order.pk in seen:
            raise FinanceError("allocation_mismatch", "Заказ указан дважды")
        seen.add(order.pk)
        if order.currency_id != trip.currency_id:
            raise FinanceError("currency_mismatch", "Валюта рейса отличается от валюты заказа")
    total = sum((quantize_money(i["amount"]) for i in allocations), Decimal("0"))
    if total != quantize_money(trip.carrier_price):
        raise FinanceError("allocation_mismatch", "Сумма по заказам должна равняться цене рейса")
    if (
        OrderService.objects.select_for_update()
        .filter(order_id__in=seen, category=CATEGORY, title=_title(trip))
        .exists()
    ):
        raise FinanceError("expense_exists", "Расход по этому рейсу уже создан")
    lines = []
    for item in allocations:
        line = OrderService.objects.create(
            order=orders[item["order_id"]],
            title=_title(trip),
            category=CATEGORY,
            income=Decimal("0"),
            expense=quantize_money(item["amount"]),
        )
        audit.log("create", line, user, {"trip": trip.pk, "expense": str(line.expense)})
        lines.append(line)
    return lines
