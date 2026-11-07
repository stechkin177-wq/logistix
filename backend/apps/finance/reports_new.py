"""Расчёты прибыли по НОВЫМ сущностям (Income / ExpenseAllocation) - для сверки и переключения.

Фильтры совпадают со старыми расчётами: заказ не удалён и не отменён (месячные итоги и журнал),
не раньше Company.accounting_start, прибыль месяца - только по заказам в базовой валюте.
Доход: Income не void; расход: доли активных (не void) расходов. Месяц дохода - recognized_on,
месяц доли - дата исходной строки (legacy_line), а у новых долей - expense_date расхода.
Только чтение.
"""

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce

from apps.forwarding.finance_lines.services import margin_pct, totals_from
from apps.forwarding.orders.services import BASE_CURRENCY_CODE

from .models import ExpenseAllocation, Income
from .money import ZERO

CANCELLED_CODE = "cancelled"


def order_totals_new(order) -> dict:
    """{'revenue','cost','profit','margin_pct'} заказа из новых сущностей."""
    revenue = (
        Income.objects.filter(order=order).exclude(status="void").aggregate(t=Sum("amount"))["t"]
    )
    cost = ExpenseAllocation.objects.filter(order=order, expense__status="active").aggregate(
        t=Sum("amount")
    )["t"]
    return totals_from(revenue or ZERO, cost or ZERO)


def _income_qs(start=None, nxt=None):
    qs = (
        Income.objects.exclude(status="void")
        .filter(order__deleted_at__isnull=True)
        .exclude(order__status__code=CANCELLED_CODE)
    )
    if start:
        qs = qs.filter(recognized_on__gte=start)
    if nxt:
        qs = qs.filter(recognized_on__lt=nxt)
    return qs


def _alloc_qs(start=None, nxt=None):
    qs = (
        ExpenseAllocation.objects.filter(expense__status="active", order__isnull=False)
        .filter(order__deleted_at__isnull=True)
        .exclude(order__status__code=CANCELLED_CODE)
        .annotate(day=Coalesce("legacy_line__date", "expense__expense_date"))
    )
    if start:
        qs = qs.filter(day__gte=start)
    if nxt:
        qs = qs.filter(day__lt=nxt)
    return qs


def month_totals_new(company, first, nxt) -> dict:
    """Аналог dashboard._month_finance по новым сущностям (прибыль месяца в базовой валюте)."""
    start = max(first, company.accounting_start) if company.accounting_start else first
    base = Q(order__currency__code=BASE_CURRENCY_CODE)
    income = _income_qs(start, nxt)
    alloc = _alloc_qs(start, nxt)
    revenue = income.filter(base).aggregate(t=Sum("amount"))["t"] or ZERO
    cost = alloc.filter(base).aggregate(t=Sum("amount"))["t"] or ZERO
    excluded_orders = set(income.exclude(base).values_list("order_id", flat=True)) | set(
        alloc.exclude(base).values_list("order_id", flat=True)
    )
    profit = revenue - cost
    return {
        "month_profit": profit,
        "month_margin_pct": margin_pct(revenue, profit),
        "currency": BASE_CURRENCY_CODE,
        "excluded_orders": len(excluded_orders),
        "revenue": revenue,
        "cost": cost,
    }


def operations_by_currency_new(accounting_start=None) -> dict:
    """Аналог operations.summary(...)['by_currency'] по новым сущностям."""
    by: dict = {}
    for row in (
        _income_qs(accounting_start)
        .order_by()
        .values("order__currency__code")
        .annotate(t=Sum("amount"), n=Count("id"))
    ):
        by.setdefault(row["order__currency__code"], {"income": ZERO, "expense": ZERO})[
            "income"
        ] += row["t"]
    for row in (
        _alloc_qs(accounting_start)
        .order_by()
        .values("order__currency__code")
        .annotate(t=Sum("amount"))
    ):
        by.setdefault(row["order__currency__code"], {"income": ZERO, "expense": ZERO})[
            "expense"
        ] += row["t"]
    return {
        code: {**v, "diff": v["income"] - v["expense"]}
        for code, v in sorted(by.items())
        if v["income"] or v["expense"]
    }


__all__ = ["order_totals_new", "month_totals_new", "operations_by_currency_new"]
