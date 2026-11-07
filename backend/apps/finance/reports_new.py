"""Расчёты прибыли по НОВЫМ сущностям (Income / ExpenseAllocation) - для сверки и переключения.

Фильтры совпадают со старыми расчётами: заказ не удалён и не отменён (месячные итоги и журнал),
не раньше Company.accounting_start, прибыль месяца - только по заказам в базовой валюте.
Доход: Income не void; расход: доли активных (не void) расходов. Месяц дохода - recognized_on,
месяц доли - дата исходной строки (legacy_line), а у новых долей - expense_date расхода.
Только чтение.

Базовая валюта (1.4.13). Итоги по КОМПАНИИ (месяц дашборда, журнал, плитки) считаются в
settings.base_currency по СОХРАНЁННОМУ снимку записи, без пересчёта истории:
  current    - снимок сделан в текущей базовой валюте (base_amount; у доли расхода - сумма доли по
               курсу снимка расхода), либо без снимка в валюте, равной базовой (сумма как есть);
  prior_base - снимок сделан в ДРУГОЙ базовой валюте (эпоха до смены базы): задним числом не
               конвертируется, выводится отдельно в исходной валюте;
  no_rate    - курса нет (legacy_missing, а также плановый доход без снимка в небазовой валюте):
               выводится отдельно в исходной валюте.
Итоги и маржа включают только current; число и суммы исключённого возвращаются в `excluded`.
Прибыль ЗАКАЗА (order_totals_new) остаётся в валюте заказа. Для сверки со старым учётом
(month_totals_order_currency) сохранено прежнее правило «только заказы в валюте KZT».
"""

from collections import defaultdict
from types import SimpleNamespace

from django.db.models import (
    Case,
    CharField,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Round, TruncDate

from apps.core.tenancy import get_current_company_id, tenant_context
from apps.forwarding.finance_lines.services import margin_pct, totals_from
from apps.forwarding.orders.services import BASE_CURRENCY_CODE

from .models import CompanyFinancialSettings, ExpenseAllocation, Income
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


CURRENT, PRIOR_BASE, NO_RATE = "current", "prior_base", "no_rate"
EXCLUDED_KINDS = (PRIOR_BASE, NO_RATE)
_BASE_MONEY = DecimalField(max_digits=18, decimal_places=2)


def base_currency_code(company=None) -> str:
    """Код базовой валюты компании (settings.base_currency); при пустой настройке - KZT."""
    cid = getattr(company, "pk", company) if company is not None else get_current_company_id()
    if not cid:
        return BASE_CURRENCY_CODE
    with tenant_context(cid):
        code = (
            CompanyFinancialSettings.objects.filter(company_id=cid)
            .values_list("base_currency__code", flat=True)
            .first()
        )
    return code or BASE_CURRENCY_CODE


def _snapshot_q(prefix: str, base_code: str, own_currency: str):
    """(current_q, nosnap_base_q, snapshot_q) по полям снимка (prefix - путь к ним)."""
    has_snapshot = (
        Q(**{f"{prefix}base_amount__isnull": False})
        & ~Q(**{f"{prefix}fx_rate_source": "legacy_missing"})
        & ~Q(**{f"{prefix}fx_rate_source": ""})
    )
    current = has_snapshot & Q(**{f"{prefix}fx_base_currency__code": base_code})
    nosnap_base = Q(**{f"{prefix}fx_rate_source": ""}) & Q(**{f"{own_currency}__code": base_code})
    return current, nosnap_base, has_snapshot


def annotate_base(queryset, *, allocations: bool, base_code: str):
    """Добавляет `bucket` (current / prior_base / no_rate) и `base_value` (сумма в текущей базе).

    Доход: base_amount снимка. Доля расхода: round(сумма доли * курс снимка расхода, 2); снимок
    принадлежит расходу. Исключённые записи получают base_value = 0 и в итоги базы не входят."""
    if allocations:
        current, nosnap_base, has_snapshot = _snapshot_q(
            "expense__", base_code, "expense__currency"
        )
        current &= Q(expense__fx_rate__isnull=False)
        in_base = Round(
            ExpressionWrapper(
                F("amount") * F("expense__fx_rate"),
                output_field=DecimalField(max_digits=30, decimal_places=8),
            ),
            2,
        )
    else:
        current, nosnap_base, has_snapshot = _snapshot_q("", base_code, "currency")
        in_base = F("base_amount")
    return queryset.annotate(
        bucket=Case(
            When(current | nosnap_base, then=Value(CURRENT)),
            When(has_snapshot, then=Value(PRIOR_BASE)),
            default=Value(NO_RATE),
            output_field=CharField(),
        ),
        base_value=Case(
            When(current, then=in_base),
            When(nosnap_base, then=F("amount")),
            default=Value(ZERO),
            output_field=_BASE_MONEY,
        ),
    )


def empty_excluded() -> dict:
    return {
        "count": 0,
        "orders": 0,
        PRIOR_BASE: {"count": 0, "by_currency": {}},
        NO_RATE: {"count": 0, "by_currency": {}},
    }


def base_split(incomes, allocs, base_code: str) -> dict:
    """Итоги в базовой валюте по записям current + сведения об исключённых (prior_base, no_rate).

    incomes / allocs - QuerySet доходов и долей расходов (с фильтрами периода и заказов)."""
    incomes = annotate_base(incomes, allocations=False, base_code=base_code)
    allocs = annotate_base(allocs, allocations=True, base_code=base_code)
    revenue = cost = ZERO
    excluded = empty_excluded()
    orders: set = set()
    for model_qs, is_income, cur_field in (
        (incomes, True, "currency__code"),
        (allocs, False, "expense__currency__code"),
    ):
        for row in (
            model_qs.order_by()
            .values("bucket", cur_field)
            .annotate(total=Sum("amount"), base=Sum("base_value"), n=Count("id"))
        ):
            if row["bucket"] == CURRENT:
                if is_income:
                    revenue += row["base"] or ZERO
                else:
                    cost += row["base"] or ZERO
                continue
            part = excluded[row["bucket"]]
            part["count"] += row["n"]
            excluded["count"] += row["n"]
            cell = part["by_currency"].setdefault(row[cur_field], {"income": ZERO, "expense": ZERO})
            cell["income" if is_income else "expense"] += row["total"] or ZERO
        orders |= set(
            model_qs.exclude(bucket=CURRENT).order_by().values_list("order_id", flat=True)
        ) - {None}
    excluded["orders"] = len(orders)
    return {"currency": base_code, "revenue": revenue, "cost": cost, "excluded": excluded}


def month_totals_new(company, first, nxt) -> dict:
    """Прибыль месяца в БАЗОВОЙ валюте компании по новым сущностям (без пересчёта истории).

    excluded_orders - число заказов, у которых есть исключённые записи (прежняя база / нет курса);
    подробности (число и суммы в исходной валюте) - в excluded."""
    start = max(first, company.accounting_start) if company.accounting_start else first
    split = base_split(_income_qs(start, nxt), _alloc_qs(start, nxt), base_currency_code(company))
    revenue, cost = split["revenue"], split["cost"]
    profit = revenue - cost
    return {
        "month_profit": profit,
        "month_margin_pct": margin_pct(revenue, profit),
        "currency": split["currency"],
        "excluded_orders": split["excluded"]["orders"],
        "excluded": split["excluded"],
        "revenue": revenue,
        "cost": cost,
    }


def month_totals_order_currency(company, first, nxt) -> dict:
    """Прежнее правило месяца (только заказы в валюте KZT) - для СВЕРКИ со старым учётом.

    Аналог dashboard._month_finance_legacy по новым сущностям; базовая валюта компании не
    учитывается (сверка идёт до переключения, по правилам прежнего учёта)."""
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


def journal_split(**filters) -> dict:
    """Итоги журнала в базовой валюте компании контекста (см. base_split)."""
    incomes, allocs = journal_querysets(**filters)
    return base_split(incomes, allocs, base_currency_code())


def journal_rows_new(**filters) -> list:
    """Строки журнала операций по новым сущностям (доход и расход - отдельные строки).

    Порядок как в старом журнале: дата по убыванию, затем идентификатор по убыванию."""
    incomes, allocs = journal_querysets(**filters)
    base_code = base_currency_code()
    incomes = annotate_base(incomes, allocations=False, base_code=base_code)
    allocs = annotate_base(allocs, allocations=True, base_code=base_code)
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
                bucket=inc.bucket,
                base_income=inc.base_value if inc.bucket == CURRENT else None,
                base_expense=None,
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
                bucket=al.bucket,
                base_income=None,
                base_expense=al.base_value if al.bucket == CURRENT else None,
                is_base=False,
                sort=(al.day, 0, al.pk),
            )
        )
    rows.sort(key=lambda r: r.sort, reverse=True)
    return rows


def summary_new(**filters) -> dict:
    """Аналог operations.summary по новым сущностям: итоги в БАЗОВОЙ валюте компании.

    Ключи income_kzt / expense_kzt / diff_kzt сохранены для совместимости ответа API (это суммы в
    базовой валюте, код - в currency). by_currency - по исходным валютам, все записи журнала.
    unconverted - число записей без курса; excluded - исключённое из итогов базы (число и суммы
    в исходной валюте: prior_base - снимок в прежней базовой валюте, no_rate - без курса)."""
    incomes, allocs = journal_querysets(**filters)
    split = base_split(incomes, allocs, base_currency_code())
    by_currency: dict = defaultdict(lambda: {"income": ZERO, "expense": ZERO})
    for qs, key in ((incomes, "income"), (allocs, "expense")):
        for row in qs.order_by().values("order__currency__code").annotate(t=Sum("amount")):
            by_currency[row["order__currency__code"]][key] += row["t"]
    revenue, cost = split["revenue"], split["cost"]
    return {
        "currency": split["currency"],
        "income_kzt": revenue,
        "expense_kzt": cost,
        "diff_kzt": revenue - cost,
        "by_currency": {
            code: {**v, "diff": v["income"] - v["expense"]}
            for code, v in sorted(by_currency.items())
        },
        "unconverted": split["excluded"][NO_RATE]["count"],
        "excluded": split["excluded"],
    }


__all__ = [
    "order_totals_new",
    "month_totals_new",
    "month_totals_order_currency",
    "base_currency_code",
    "base_split",
    "journal_split",
    "operations_by_currency_new",
    "annotate_order_totals_new",
    "journal_rows_new",
    "summary_new",
]
