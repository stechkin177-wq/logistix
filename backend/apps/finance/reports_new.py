"""Расчёты прибыли по НОВЫМ сущностям (Income / ExpenseAllocation) - для сверки и переключения.

Фильтры совпадают со старыми расчётами: заказ не удалён и не отменён (месячные итоги и журнал),
не раньше Company.accounting_start, прибыль месяца - только по заказам в базовой валюте.
Доход: Income не void; расход: доли активных (не void) расходов. Месяц дохода - recognized_on,
месяц доли - дата исходной строки (legacy_line), а у новых долей - expense_date расхода.
Только чтение.
"""

from collections import defaultdict
from decimal import Decimal
from types import SimpleNamespace

from django.db.models import Count, DecimalField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce, TruncDate

from apps.forwarding.finance_lines.services import margin_pct, totals_from
from apps.forwarding.orders.services import BASE_CURRENCY_CODE

from .models import ExpenseAllocation, Income
from .money import ZERO, quantize_money

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


_MONEY = DecimalField(max_digits=18, decimal_places=2)


def annotate_order_totals_new(queryset):
    """Аналог annotate_order_totals: revenue и cost подзапросами по Income / долям расходов."""

    def total(model_qs):
        per_order = model_qs.order_by().values("order").annotate(t=Sum("amount")).values("t")
        return Coalesce(Subquery(per_order, output_field=_MONEY), Value(ZERO), output_field=_MONEY)

    return queryset.annotate(
        revenue=total(Income.objects.filter(order=OuterRef("pk")).exclude(status="void")),
        cost=total(
            ExpenseAllocation.objects.filter(order=OuterRef("pk"), expense__status="active")
        ),
    )


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


def _filtered(qs, *, income: bool, date_from, date_to, accounting_start, client, order):
    if accounting_start:
        qs = qs.filter(day__gte=accounting_start)
    if date_from:
        qs = qs.filter(day__gte=date_from)
    if date_to:
        qs = qs.filter(day__lte=date_to)
    if client:
        qs = qs.filter(order__client_id=client)
    if order:
        qs = qs.filter(order_id=order)
    return qs


def journal_querysets(
    *, date_from=None, date_to=None, category=None, client=None, order=None, accounting_start=None
):
    """(доходы, доли расходов) журнала по тем же фильтрам, что и operations_queryset."""
    flt = dict(
        date_from=date_from,
        date_to=date_to,
        accounting_start=accounting_start,
        client=client,
        order=order,
    )
    # дата дохода в журнале: признание; у планового - дата создания (None не допускается)
    incomes = (
        _income_qs()
        .exclude(amount=0)
        .annotate(day=Coalesce("recognized_on", TruncDate("created_at")))
    )
    incomes = _filtered(incomes, income=True, **flt)
    allocs = _filtered(_alloc_qs().exclude(amount=0), income=False, **flt)
    if category:
        incomes = incomes.filter(category=category)
        allocs = allocs.filter(
            Q(expense__category__name=category) | Q(expense__category__code=category)
        )
    return incomes, allocs


def journal_rows_new(**filters) -> list:
    """Строки журнала операций по новым сущностям (доход и расход - отдельные строки).

    Порядок как в старом журнале: дата по убыванию, затем идентификатор по убыванию."""
    incomes, allocs = journal_querysets(**filters)
    rows = []
    for inc in incomes.select_related("order__client", "order__currency"):
        rows.append(
            SimpleNamespace(
                pk=f"income:{inc.pk}",
                date=inc.day,
                order=inc.order,
                order_id=inc.order_id,
                title=inc.title,
                category=inc.category,
                income=inc.amount,
                expense=ZERO,
                is_base=False,
                sort=(inc.day, 1, inc.pk),
            )
        )
    for al in allocs.select_related("expense__category", "order__client", "order__currency"):
        rows.append(
            SimpleNamespace(
                pk=f"expense:{al.pk}",
                date=al.day,
                order=al.order,
                order_id=al.order_id,
                title=al.expense.title,
                category=al.expense.category.name if al.expense.category_id else "",
                income=ZERO,
                expense=al.amount,
                is_base=False,
                sort=(al.day, 0, al.pk),
            )
        )
    rows.sort(key=lambda r: r.sort, reverse=True)
    return rows


def summary_new(rate_table_factory, **filters) -> dict:
    """Аналог operations.summary по новым сущностям (тенге по курсу на дату, как в журнале)."""
    incomes, allocs = journal_querysets(**filters)
    groups: dict = defaultdict(lambda: {"income": ZERO, "expense": ZERO, "lines": 0})
    codes: dict = {}
    for row in (
        incomes.order_by()
        .values("order__currency_id", "order__currency__code", "day")
        .annotate(t=Sum("amount"), n=Count("id"))
    ):
        key = (row["order__currency_id"], row["day"])
        codes[row["order__currency_id"]] = row["order__currency__code"]
        groups[key]["income"] += row["t"]
        groups[key]["lines"] += row["n"]
    for row in (
        allocs.order_by()
        .values("order__currency_id", "order__currency__code", "day")
        .annotate(t=Sum("amount"), n=Count("id"))
    ):
        key = (row["order__currency_id"], row["day"])
        codes[row["order__currency_id"]] = row["order__currency__code"]
        groups[key]["expense"] += row["t"]
        groups[key]["lines"] += row["n"]
    table = rate_table_factory({cid for cid, _ in groups})
    by_currency: dict = defaultdict(lambda: {"income": ZERO, "expense": ZERO})
    income_kzt = expense_kzt = ZERO
    unconverted = 0
    for (cid, day), g in groups.items():
        code = codes[cid]
        by_currency[code]["income"] += g["income"]
        by_currency[code]["expense"] += g["expense"]
        rate = Decimal("1") if code == BASE_CURRENCY_CODE else table.rate(cid, day)
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


__all__ = [
    "order_totals_new",
    "month_totals_new",
    "operations_by_currency_new",
    "annotate_order_totals_new",
    "journal_rows_new",
    "summary_new",
]
