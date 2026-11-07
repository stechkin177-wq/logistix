"""Журнал операций: доходы и расходы по строкам заказов, итоги в тенге и по валютам.

Исключены строки удалённых и отменённых заказов и строки раньше Company.accounting_start (как в
дашборде). Итоги считает БД по группам (валюта, дата); в тенге строка конвертируется по курсу
на её дату, без курса - попадает в unconverted и в тенге не суммируется.
"""

from bisect import bisect_right
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Sum

from apps.forwarding.finance_lines.models import OrderService
from apps.forwarding.orders.services import BASE_CURRENCY_CODE

from .models import ExchangeRate
from .money import ZERO, quantize_money

CANCELLED_CODE = "cancelled"


def operations_queryset(
    *, date_from=None, date_to=None, category=None, client=None, order=None, accounting_start=None
):
    qs = (
        OrderService.objects.filter(order__deleted_at__isnull=True)
        .exclude(order__status__code=CANCELLED_CODE)
        .exclude(income=0, expense=0)  # нулевые строки (например, ставка 0) в журнале - шум
    )
    if accounting_start:
        qs = qs.filter(date__gte=accounting_start)
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    if category:
        qs = qs.filter(category=category)
    if client:
        qs = qs.filter(order__client_id=client)
    if order:
        qs = qs.filter(order_id=order)
    return qs


def listing(qs):
    return qs.select_related("order__client", "order__currency").order_by("-date", "-id")


class RateTable:
    """Курсы нужных валют, загруженные одним запросом; поиск «последний не позже даты»."""

    def __init__(self, currency_ids):
        rows = defaultdict(list)
        for cid, day, rate in (
            ExchangeRate.objects.filter(currency_id__in=currency_ids, quote_currency__isnull=True)
            .order_by("currency_id", "date")
            .values_list("currency_id", "date", "rate")
        ):
            rows[cid].append((day, rate))
        self._dates = {cid: [d for d, _ in r] for cid, r in rows.items()}
        self._rates = {cid: [r for _, r in rows_] for cid, rows_ in rows.items()}

    def rate(self, currency_id, day) -> Decimal | None:
        dates = self._dates.get(currency_id)
        if not dates:
            return None
        i = bisect_right(dates, day) - 1
        return self._rates[currency_id][i] if i >= 0 else None


def summary(qs) -> dict:
    groups = list(
        qs.order_by()
        .values("order__currency_id", "order__currency__code", "date")
        .annotate(income=Sum("income"), expense=Sum("expense"), lines=Count("id"))
    )
    table = RateTable({g["order__currency_id"] for g in groups})
    by_currency = defaultdict(lambda: {"income": ZERO, "expense": ZERO})
    income_kzt = expense_kzt = ZERO
    unconverted = 0
    for g in groups:
        code = g["order__currency__code"]
        by_currency[code]["income"] += g["income"]
        by_currency[code]["expense"] += g["expense"]
        rate = (
            Decimal("1")
            if code == BASE_CURRENCY_CODE
            else table.rate(g["order__currency_id"], g["date"])
        )
        if rate is None:
            unconverted += g["lines"]
            continue
        income_kzt += quantize_money(g["income"] * rate)
        expense_kzt += quantize_money(g["expense"] * rate)
    return {
        "income_kzt": income_kzt,
        "expense_kzt": expense_kzt,
        "diff_kzt": income_kzt - expense_kzt,
        "by_currency": {
            code: {**v, "diff": v["income"] - v["expense"]} for code, v in by_currency.items()
        },
        "unconverted": unconverted,
    }
