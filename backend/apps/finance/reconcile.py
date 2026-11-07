# ruff: noqa: E501
"""Сверка старого учёта (OrderService) с новыми сущностями (Income / Expense / доли / связи).

Данные НЕ меняются: сверка читает, пишет только FinanceMigrationRun(kind=reconcile) и Issues
типа reconcile_diff (по расхождению; не воспроизведённые повторной сверкой закрываются
автоматически). Статус Run 'success' - ТОЛЬКО если нет необъяснённых расхождений: числовых,
структурных и открытых error-проблем переноса (ambiguous_trip_expense, shadow_error,
migrate_error). legacy_missing НЕ исключает сумму из сверки (сравнение в исходной валюте) и
перечисляется отдельным списком. Строки с РУЧНО разрешённой проблемой считаются объяснёнными:
их суммы исключаются из старой стороны сравнений и перечисляются в отчёте.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Count
from django.utils import timezone

from apps.core.models import Company
from apps.core.tenancy import tenant_context
from apps.forwarding.dashboard import _month_finance_legacy, month_bounds
from apps.forwarding.finance_lines.models import OrderService
from apps.forwarding.finance_lines.services import margin_pct, order_totals_legacy
from apps.forwarding.models import Order
from apps.forwarding.orders.services import BASE_CURRENCY_CODE

from . import operations, reports_new
from .engine import current_cid
from .migration import ISSUE_TRIP, MIGRATION_ISSUE_TYPES, SOURCE_MODEL
from .models import (
    Expense,
    ExpenseAllocation,
    ExpenseInvoiceAllocation,
    FinanceMigrationIssue,
    FinanceMigrationRun,
    Income,
    InvoiceItem,
)
from .money import ZERO

DIFF_TYPE = "reconcile_diff"
CANCELLED = "cancelled"


class _Findings:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, check, code, key, message, *, severity="error", **details):
        self.items.append(
            {
                "check": check,
                "code": code,
                "key": str(key),
                "severity": severity,
                "message": message,
                "details": details,
            }  # fmt: skip
        )

    @property
    def errors(self):
        return [f for f in self.items if f["severity"] == "error"]


def _month(d: date) -> str:
    return f"{d:%Y-%m}"


def _s(value) -> str:
    return format(value, "f") if isinstance(value, Decimal) else str(value)


def reconcile(company_id: int, *, month: str | None = None) -> FinanceMigrationRun:
    cid = current_cid(company_id)
    with tenant_context(cid):
        company = Company.objects.get(pk=cid)
        run = FinanceMigrationRun.objects.create(
            company_id=cid, kind="reconcile", mode="dry_run", params={"month": month}
        )
        findings = _Findings()
        summary = _collect(company, month, findings)
        _persist(cid, run, findings)
        errors = findings.errors
        summary["unexplained"] = len(errors)
        summary["findings"] = findings.items[:500]
        run.summary = summary
        run.status = "success" if not errors else "needs_review"
        run.finished_at = timezone.now()
        run.save()
        return run


def _collect(company, month, F: _Findings) -> dict:
    lines = list(OrderService.objects.select_related("order__currency").order_by("pk"))
    issues = list(FinanceMigrationIssue.objects.filter(source_model=SOURCE_MODEL))
    open_issue = {i.source_id: i for i in issues if i.status == "open"}
    justified = {
        i.source_id: i
        for i in issues
        if i.status == "resolved"
        and i.issue_type == ISSUE_TRIP
        and i.resolution == "justified_exclusion"
    }
    open_lines = set(open_issue)
    income_by_line = {
        i.legacy_line_id: i
        for i in Income.objects.filter(legacy_line__isnull=False)
        .exclude(status="void")
        .select_related("currency", "legacy_line")
    }
    alloc_by_line = {
        a.legacy_line_id: a
        for a in ExpenseAllocation.objects.filter(legacy_line__isnull=False).select_related(
            "expense__currency", "legacy_line"
        )
    }

    def wanted(d):
        return month is None or _month(d) == month

    # 1-2. суммы по (валюта, месяц) в ИСХОДНОЙ валюте
    for check, field, new_map, label in (
        (1, "income", income_by_line, "доходов"),
        (2, "expense", alloc_by_line, "расходов"),
    ):
        old: dict = defaultdict(Decimal)
        new: dict = defaultdict(Decimal)
        for ln in lines:
            value = getattr(ln, field)
            if value > 0 and wanted(ln.date):
                old[(ln.order.currency.code, _month(ln.date))] += value
        for line_id, obj in new_map.items():
            ln = obj.legacy_line
            code = obj.currency.code if field == "income" else obj.expense.currency.code
            if wanted(ln.date):
                new[(code, _month(ln.date))] += obj.amount
        for key in sorted(set(old) | set(new)):
            if old[key] != new[key]:
                F.add(check, f"{field}_sum", f"{key[0]}:{key[1]}",
                      f"Сумма {label} {key[0]} за {key[1]}: старая {_s(old[key])}, новая {_s(new[key])}",
                      old=_s(old[key]), new=_s(new[key]))  # fmt: skip
        for ln in lines:
            if not wanted(ln.date):
                continue
            obj = new_map.get(ln.pk)
            value = getattr(ln, field)
            if obj is not None and value > 0 and obj.amount != value:
                F.add(check, f"{field}_line", f"line:{ln.pk}",
                      f"Строка #{ln.pk}: {field} {_s(value)} != перенесено {_s(obj.amount)}",
                      line=ln.pk)  # fmt: skip

    # 3. неперенесённые строки
    not_reflected = []
    for ln in lines:
        for field, new_map, label in (
            ("income", income_by_line, "доход"),
            ("expense", alloc_by_line, "расход"),
        ):
            if getattr(ln, field) <= 0 or ln.pk in new_map:
                continue
            if ln.pk in open_lines or ln.pk in justified:
                issue = open_issue.get(ln.pk) or justified[ln.pk]
                reason = (
                    f"открыта проблема #{issue.pk}"
                    if ln.pk in open_lines
                    else f"обоснованное исключение: {issue.resolution_note}"
                )
                not_reflected.append(
                    {
                        "line": ln.pk,
                        "field": field,
                        "amount": _s(getattr(ln, field)),
                        "currency": ln.order.currency.code,
                        "month": _month(ln.date),
                        "reason": reason,
                        "issue": issue.pk,
                    }
                )
                if ln.pk in justified and wanted(ln.date):
                    F.add(3, "not_reflected", f"line:{ln.pk}:{field}",
                          f"Строка #{ln.pk} ({label} {_s(getattr(ln, field))}) не отражена в новой модели: {reason}",
                          line=ln.pk, issue=issue.pk)  # fmt: skip
            else:
                F.add(3, "unmigrated_line", f"line:{ln.pk}:{field}",
                      f"Строка #{ln.pk} ({label} {_s(getattr(ln, field))}) не перенесена и не имеет проблемы",
                      line=ln.pk)  # fmt: skip

    # 4. открытые error-проблемы
    for issue in issues_open_errors():
        F.add(4, "open_issue", f"issue:{issue.pk}", f"Открыта проблема #{issue.pk} ({issue.issue_type}): {issue.message}",
              issue=issue.pk, type=issue.issue_type, source_id=issue.source_id)  # fmt: skip

    # 5. прибыль и маржа каждого заказа
    order_ids = (
        {ln.order_id for ln in lines}
        | set(Income.objects.values_list("order_id", flat=True))
        | set(ExpenseAllocation.objects.exclude(order=None).values_list("order_id", flat=True))
    )
    for order in Order.all_objects.filter(pk__in=order_ids).order_by("pk"):
        old = order_totals_legacy(order)
        revenue, cost = old["revenue"], old["cost"]
        profit = revenue - cost
        new = reports_new.order_totals_new(order)
        old_t = (revenue, cost, profit, margin_pct(revenue, profit))
        new_t = (new["revenue"], new["cost"], new["profit"], new["margin_pct"])
        if old_t != new_t:
            F.add(5, "order_profit", f"order:{order.pk}",
                  f"Заказ {order.number}: прибыль/маржа старая {_s(profit)}/{old_t[3]}, новая {_s(new['profit'])}/{new_t[3]}",
                  order=order.pk, old=[_s(x) for x in old_t], new=[_s(x) for x in new_t])  # fmt: skip

    # 6. месяц, дашборд и журнал
    months = sorted(
        {_month(ln.date) for ln in lines if wanted(ln.date)} | ({month} if month else set())
    )
    for m in months:
        first = date(int(m[:4]), int(m[5:]), 1)
        first, nxt = month_bounds(first)
        old = _month_finance_legacy(company, first)
        new = reports_new.month_totals_new(company, first, nxt)
        revenue_old = _old_revenue(company, first, nxt)
        profit_old = old["month_profit"]  # прибыль - из самого дашборда
        if (profit_old, margin_pct(revenue_old, profit_old)) != (
            new["month_profit"],
            new["month_margin_pct"],
        ):
            F.add(6, "month_profit", f"month:{m}",
                  f"Месяц {m}: прибыль/маржа старая {_s(profit_old)}/{margin_pct(revenue_old, profit_old)}, "
                  f"новая {_s(new['month_profit'])}/{new['month_margin_pct']}",
                  old=_s(profit_old), new=_s(new["month_profit"]))  # fmt: skip
    old_ops = operations.summary(
        operations.operations_queryset(accounting_start=company.accounting_start)
    )["by_currency"]
    new_ops = reports_new.operations_by_currency_new(company.accounting_start)
    for code in sorted(set(old_ops) | set(new_ops)):
        o = old_ops.get(code, {"income": ZERO, "expense": ZERO})
        n = new_ops.get(code, {"income": ZERO, "expense": ZERO})
        if (o["income"], o["expense"]) != (n["income"], n["expense"]):
            F.add(6, "operations_sum", f"operations:{code}",
                  f"Журнал операций {code}: доход/расход старый {_s(o['income'])}/{_s(o['expense'])}, "
                  f"новый {_s(n['income'])}/{_s(n['expense'])}",
                  old=[_s(o["income"]), _s(o["expense"])], new=[_s(n["income"]), _s(n["expense"])])  # fmt: skip

    # 7. связи счетов
    orphans = []
    for item in InvoiceItem.objects.select_related("invoice").order_by("pk"):
        inv = item.invoice
        if item.line_id is None:
            orphans.append(
                {
                    "item": item.pk,
                    "invoice": inv.pk,
                    "status": inv.status,
                    "amount": _s(item.amount_net),
                }
            )
            continue
        if inv.status == "cancelled" or inv.deleted_at is not None:
            continue
        if inv.direction == "out":
            target = income_by_line.get(item.line_id)
            if target is not None and item.income_id != target.pk:
                F.add(7, "income_link", f"item:{item.pk}", f"Позиция #{item.pk} счёта {inv.number} не связана с доходом",
                      item=item.pk, expected=target.pk, actual=item.income_id)  # fmt: skip
        else:
            alloc = alloc_by_line.get(item.line_id)
            if (
                alloc is not None
                and not ExpenseInvoiceAllocation.objects.filter(
                    expense_id=alloc.expense_id, invoice_item=item, released_at__isnull=True
                ).exists()
            ):
                F.add(7, "expense_link", f"item:{item.pk}", f"Позиция #{item.pk} входящего счёта {inv.number} не связана с расходом",
                      item=item.pk, expense=alloc.expense_id)  # fmt: skip
    for orphan in orphans:
        F.add(7, "orphan_item", f"item:{orphan['item']}", f"Позиция #{orphan['item']} без строки (счёт {orphan['status']})",
              severity="info", **orphan)  # fmt: skip

    # 8. суммы долей
    for exp in Expense.objects.filter(status="active").order_by("pk"):
        allocs = list(ExpenseAllocation.objects.filter(expense=exp))
        total = sum((a.amount for a in allocs), ZERO)
        if total > exp.amount or (exp.requires_full_allocation and total != exp.amount):
            F.add(8, "allocation_sum", f"expense:{exp.pk}",
                  f"Расход #{exp.pk}: сумма {_s(exp.amount)}, долей {_s(total)}"
                  f"{' (нужно полное распределение)' if exp.requires_full_allocation else ''}",
                  expense=exp.pk, amount=_s(exp.amount), allocated=_s(total))  # fmt: skip
        pairs = [(a.order_id, a.trip_id) for a in allocs]
        if len(pairs) != len(set(pairs)):
            F.add(
                8,
                "allocation_duplicate",
                f"expense:{exp.pk}",
                f"Расход #{exp.pk}: повторяющиеся доли (двойной учёт)",
                expense=exp.pk,
            )
        both = [a for a in allocs if a.order_id and a.trip_id]
        if both and sum((a.amount for a in both), ZERO) != sum(
            (a.amount for a in allocs if a.trip_id), ZERO
        ) - sum((a.amount for a in allocs if a.trip_id and not a.order_id), ZERO):
            F.add(
                8,
                "allocation_slices",
                f"expense:{exp.pk}",
                f"Расход #{exp.pk}: срезы заказов и рейса расходятся",
                expense=exp.pk,
            )

    # 9. дубли
    for code, qs, field in (
        ("dup_income_line", Income.objects.filter(legacy_line__isnull=False), "legacy_line_id"),
        (
            "dup_alloc_line",
            ExpenseAllocation.objects.filter(legacy_line__isnull=False),
            "legacy_line_id",
        ),
        (
            "dup_carrier_expense",
            Expense.objects.filter(kind="carrier_transport", status="active"),
            "trip_id",
        ),
        ("dup_freight", Income.objects.filter(kind="freight").exclude(status="void"), "order_id"),
        ("dup_group_key", Expense.objects.exclude(legacy_group_key=""), "legacy_group_key"),
    ):
        for row in qs.order_by().values(field).annotate(n=Count("id")).filter(n__gt=1):
            F.add(
                9,
                code,
                f"{code}:{row[field]}",
                f"Дубль ({code}): {row[field]} встречается {row['n']} раз",
                value=str(row[field]),
            )

    # 10. события без источника
    for inc in Income.objects.filter(
        recognition_basis="legacy_line_date", legacy_line__isnull=True
    ).exclude(status="void"):
        F.add(
            10,
            "income_without_source",
            f"income:{inc.pk}",
            f"Доход #{inc.pk} из прежнего учёта без строки-источника",
            income=inc.pk,
        )
    for exp in Expense.objects.filter(source="migrated", legacy_group_key="").exclude(
        status="void"
    ):
        F.add(
            10,
            "expense_without_source",
            f"expense:{exp.pk}",
            f"Перенесённый расход #{exp.pk} без ключа источника",
            expense=exp.pk,
        )
    for exp in Expense.objects.filter(source="migrated").exclude(status="void"):
        if not ExpenseAllocation.objects.filter(expense=exp, legacy_line__isnull=False).exists():
            F.add(
                10,
                "expense_without_lines",
                f"expense:{exp.pk}",
                f"Перенесённый расход #{exp.pk} без долей-источников",
                expense=exp.pk,
            )

    # 11. legacy_missing (отдельный список, суммы НЕ исключаются)
    missing = []
    for model, kind in ((Income, "income"), (Expense, "expense")):
        for obj in (
            model.objects.filter(fx_rate_source="legacy_missing")
            .exclude(status="void")
            .select_related("currency")
        ):
            missing.append(
                {
                    "kind": kind,
                    "id": obj.pk,
                    "amount": _s(obj.amount),
                    "currency": obj.currency.code,
                }
            )
            F.add(11, "legacy_missing", f"{kind}:{obj.pk}", f"{kind} #{obj.pk}: нет курса на дату ({_s(obj.amount)} {obj.currency.code})",
                  severity="info", **missing[-1])  # fmt: skip
    review = [
        {"expense": e.pk, "reason": e.review_reason}
        for e in Expense.objects.filter(needs_review=True).exclude(status="void")
    ]
    return {
        "month": month,
        "lines_total": len(lines),
        "not_reflected": not_reflected,
        "legacy_missing": missing,
        "orphans": orphans,
        "needs_review_expenses": review,
    }


def issues_open_errors():
    return FinanceMigrationIssue.objects.filter(
        status="open", severity="error", issue_type__in=MIGRATION_ISSUE_TYPES
    ).order_by("pk")


def _dashboard_lines(company, first, nxt):
    start = max(first, company.accounting_start) if company.accounting_start else first
    return (
        OrderService.objects.filter(order__deleted_at__isnull=True, date__gte=start, date__lt=nxt)
        .exclude(order__status__code=CANCELLED)
        .filter(order__currency__code=BASE_CURRENCY_CODE)
    )


def _old_revenue(company, first, nxt) -> Decimal:
    from django.db.models import Sum

    return _dashboard_lines(company, first, nxt).aggregate(t=Sum("income"))["t"] or ZERO


def _in_dashboard(line, start, nxt) -> bool:
    o = line.order
    return (
        o.deleted_at is None
        and o.status.code != CANCELLED
        and o.currency.code == BASE_CURRENCY_CODE
        and start <= line.date < nxt
    )


def _in_ops(line, accounting_start) -> bool:
    o = line.order
    return (
        o.deleted_at is None
        and o.status.code != CANCELLED
        and (line.income or line.expense)
        and (accounting_start is None or line.date >= accounting_start)
    )


def _persist(cid: int, run, F: _Findings) -> None:
    """Issues reconcile_diff по ошибкам; не воспроизведённые открытые закрываются автоматически."""
    current = {}
    for f in F.errors:
        if f["check"] == 4:
            continue  # открытые проблемы переноса уже существуют
        current[f"{f['check']}:{f['code']}:{f['key']}"] = f
    open_diffs = {
        i.details.get("fingerprint"): i
        for i in FinanceMigrationIssue.objects.filter(issue_type=DIFF_TYPE, status="open")
    }
    for fp, f in current.items():
        if fp in open_diffs:
            continue
        FinanceMigrationIssue.objects.create(
            company_id=cid, run=run, issue_type=DIFF_TYPE, severity="error",
            source_model="reconcile", message=f["message"][:2000],
            details={"fingerprint": fp, "check": f["check"], **f["details"]},
        )  # fmt: skip
    for fp, issue in open_diffs.items():
        if fp not in current:
            issue.status = "resolved"
            issue.resolved_at = timezone.now()
            issue.resolution_note = "Не воспроизведено повторной сверкой"
            issue.save()
