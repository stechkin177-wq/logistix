"""reconcile_finance (1.4.9): сверка старого учёта с новыми сущностями."""

from datetime import date
from decimal import Decimal as D
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.core.tenancy import tenant_context
from apps.finance import migration, reconcile, reports_new
from apps.finance.models import (
    Expense,
    ExpenseAllocation,
    FinanceMigrationIssue,
    FinanceMigrationRun,
    Income,
    InvoiceItem,
)
from apps.finance.tests.helpers import add_line, make_order
from apps.finance.tests.p2_helpers import rate
from apps.finance.tests.test_migrate_finance import (
    build,
    counts,
    disputed_lines,
    run_cmd,
    snapshot,
)
from apps.forwarding.finance_lines.models import OrderService
from apps.forwarding.models import Order

pytestmark = pytest.mark.django_db
D1, D2 = date(2026, 5, 10), date(2026, 6, 12)


def recon(company, month=None):
    return reconcile.reconcile(company.id, month=month)


def codes(run, check=None):
    return sorted(
        f["code"]
        for f in run.summary["findings"]
        if f["severity"] == "error" and (check is None or f["check"] == check)
    )


def simple(company):
    """Согласованная компания: заказы, ручные расходы, USD с курсом и без, без спорных строк."""
    rate(company, "USD", "480", date(2026, 6, 1))
    o1 = make_order(company)
    add_line(company, o1, income=200, title="Услуга", day=D1)
    add_line(company, o1, income=30, expense=20, title="Оба", day=D2)
    add_line(company, o1, expense=50, title="Склад", day=D2, category="Прочее")
    o2 = make_order(company, currency="USD")
    add_line(company, o2, income=10, expense=4, title="USD до курса", day=D1)
    add_line(company, o2, income=20, title="USD с курсом", day=D2)
    run_cmd(company)
    return o1, o2


def test_clean_consistent_db_is_success_and_read_only(company):
    simple(company)
    before = (snapshot(company), counts(company))
    run = recon(company)
    assert run.status == "success" and run.summary["unexplained"] == 0, run.summary["findings"]
    assert run.kind == "reconcile" and run.finished_at is not None
    assert (snapshot(company), {**counts(company), "issues": 0}) == (
        before[0],
        {**before[1], "issues": 0},
    )
    with tenant_context(company.id):
        assert FinanceMigrationIssue.objects.filter(issue_type="reconcile_diff").count() == 0
    # legacy_missing перечислен отдельным списком и не выпал из сумм
    kinds = {(m["kind"], m["currency"]) for m in run.summary["legacy_missing"]}
    assert ("income", "USD") in kinds and ("expense", "USD") in kinds
    assert [
        f
        for f in run.summary["findings"]
        if f["code"] == "legacy_missing" and f["severity"] == "info"
    ]


def test_legacy_missing_amount_is_not_excluded_from_sums(company):
    simple(company)
    with tenant_context(company.id):
        inc = Income.objects.get(fx_rate_source="legacy_missing", kind="service")
        Income.objects.filter(pk=inc.pk).update(amount=inc.amount + D("1"))
    run = recon(company)
    assert run.status == "needs_review"
    assert "income_sum" in codes(run, 1) and "income_line" in codes(run, 1)
    assert any(
        f["key"] == "USD:2026-05" for f in run.summary["findings"] if f["code"] == "income_sum"
    )


def test_changed_source_line_is_caught_in_every_report(company):
    o1, _ = simple(company)
    with tenant_context(company.id):
        line = OrderService.objects.get(order=o1, title="Услуга")
        OrderService.objects.filter(pk=line.pk).update(income=D("250"))
    run = recon(company)
    assert run.status == "needs_review"
    assert {"income_sum", "income_line"} <= set(codes(run, 1))
    assert "order_profit" in codes(run, 5) and "month_profit" in codes(run, 6)
    assert "operations_sum" in codes(run, 6)
    with tenant_context(company.id):  # расхождения оформлены Issues, данные не тронуты
        assert (
            FinanceMigrationIssue.objects.filter(issue_type="reconcile_diff", status="open").count()
            > 0
        )
        assert Income.objects.get(legacy_line=line).amount == D("200.00")


def test_changed_expense_line_is_caught(company):
    o1, _ = simple(company)
    with tenant_context(company.id):
        OrderService.objects.filter(order=o1, title="Склад").update(expense=D("55"))
    run = recon(company)
    assert run.status == "needs_review" and "expense_sum" in codes(run, 2)


def test_missing_invoice_link_is_caught(company):
    s = build(company)
    run_cmd(company)
    # согласованность не требуется: ищем именно связь
    with tenant_context(company.id):
        InvoiceItem.objects.filter(invoice=s["out_inv"]).update(income=None)
    run = recon(company)
    assert "income_link" in codes(run, 7) and run.status == "needs_review"
    orphans = [f for f in run.summary["findings"] if f["code"] == "orphan_item"]
    assert orphans == [] or all(f["severity"] == "info" for f in orphans)


def test_missing_expense_link_is_caught(company):
    s = build(company)
    run_cmd(company)
    with tenant_context(company.id):
        from apps.finance.models import ExpenseInvoiceAllocation

        ExpenseInvoiceAllocation.objects.all().delete()
    assert "expense_link" in codes(recon(company), 7)
    assert s


def test_allocation_problems_are_caught(company):
    simple(company)
    with tenant_context(company.id):
        exp = Expense.objects.filter(source="migrated").first()
        al = ExpenseAllocation.objects.filter(expense=exp).first()
        ExpenseAllocation.objects.create(
            company_id=company.id, expense=exp, order=al.order, trip=al.trip, amount=D("1")
        )  # дубль среза и Σ долей больше суммы
    run = recon(company)
    assert {"allocation_sum", "allocation_duplicate"} <= set(codes(run, 8))
    assert run.status == "needs_review"


def test_event_without_source_is_caught(company):
    simple(company)
    with tenant_context(company.id):
        inc = Income.objects.filter(legacy_line__isnull=False).first()
        Income.objects.filter(pk=inc.pk).update(legacy_line=None)
        exp = Expense.objects.filter(source="migrated").first()
        Expense.objects.filter(pk=exp.pk).update(legacy_group_key="")
    run = recon(company)
    assert "income_without_source" in codes(run, 10) and "expense_without_source" in codes(run, 10)
    assert "unmigrated_line" in codes(run, 3)  # у строки больше нет дохода-зеркала


def test_unmigrated_line_without_issue_is_caught_and_open_issue_explains_listing(company):
    o = make_order(company)
    add_line(company, o, income=10, title="Новая", day=D1)  # перенос не запускался
    run = recon(company)
    assert "unmigrated_line" in codes(run, 3) and run.status == "needs_review"


def test_justified_exclusion_is_not_hidden_from_reconcile(company):
    """Обоснованное исключение НЕ исключает сумму из сверки: needs_review и список «не отражено»."""
    s = build(company)
    run_cmd(company)
    run = recon(company)
    assert run.status == "needs_review"
    open_errors = [f for f in run.summary["findings"] if f["check"] == 4]
    assert {f["details"]["source_id"] for f in open_errors} == disputed_lines(s)
    assert {r["line"] for r in run.summary["not_reflected"]} == disputed_lines(s)
    with tenant_context(company.id):
        for issue in FinanceMigrationIssue.objects.filter(issue_type="ambiguous_trip_expense"):
            migration.resolve_issue(
                issue, None, "Проверено вручную, списано", "justified_exclusion"
            )
    run2 = recon(company)
    assert run2.status == "needs_review"
    rows = run2.summary["not_reflected"]
    assert {r["line"] for r in rows} == disputed_lines(s)
    assert all(
        r["field"] == "expense" and r["currency"] and r["month"] and "обоснованное" in r["reason"]
        for r in rows
    )
    assert "not_reflected" in codes(run2, 3) and "expense_sum" in codes(run2, 2)
    assert "manually_resolved_lines" not in run2.summary


def test_resolved_into_new_model_makes_reconcile_succeed(company):
    s = build(company)
    run_cmd(company)
    with tenant_context(company.id):
        for issue in FinanceMigrationIssue.objects.filter(issue_type="ambiguous_trip_expense"):
            migration.resolve_issue(issue, None, "Отнесено на прочие", "manual_expense")
    run2 = recon(company)
    assert run2.status == "success", [
        f["message"] for f in run2.summary["findings"] if f["severity"] == "error"
    ]
    assert run2.summary["not_reflected"] == []
    with tenant_context(company.id):  # производные Issues прошлой сверки закрыты автоматически
        assert not FinanceMigrationIssue.objects.filter(
            issue_type="reconcile_diff", status="open"
        ).exists()
    assert s


def test_repeated_reconcile_does_not_duplicate_issues_and_closes_fixed_ones(company):
    o1, _ = simple(company)
    with tenant_context(company.id):
        line = OrderService.objects.get(order=o1, title="Услуга")
        OrderService.objects.filter(pk=line.pk).update(income=D("250"))
    recon(company)
    with tenant_context(company.id):
        first = FinanceMigrationIssue.objects.filter(
            issue_type="reconcile_diff", status="open"
        ).count()
    recon(company)
    with tenant_context(company.id):
        assert (
            FinanceMigrationIssue.objects.filter(issue_type="reconcile_diff", status="open").count()
            == first
        )
        OrderService.objects.filter(pk=line.pk).update(income=D("200"))
    run = recon(company)
    assert run.status == "success"
    with tenant_context(company.id):
        assert (
            FinanceMigrationIssue.objects.filter(issue_type="reconcile_diff", status="open").count()
            == 0
        )
        assert (
            FinanceMigrationIssue.objects.filter(
                issue_type="reconcile_diff", status="resolved"
            ).count()
            == first
        )


def test_multicurrency_and_months_and_month_filter(company):
    simple(company)
    run = recon(company)
    assert run.status == "success"
    with tenant_context(company.id):
        line = OrderService.objects.get(title="Склад")
        OrderService.objects.filter(pk=line.pk).update(expense=D("1"))  # июнь, KZT
    may = recon(company, month="2026-05")  # месячные проверки не видят июнь; заказ - целиком (п.5)
    assert "expense_sum" not in codes(may) and "month_profit" not in codes(may)
    assert "order_profit" in codes(may)
    june = recon(company, month="2026-06")
    assert june.status == "needs_review" and "expense_sum" in codes(june, 2)


def test_isolation_between_companies(company, make_company):
    other, _, _ = make_company("Other")
    simple(company)
    o = make_order(other)
    add_line(
        other, o, income=5, title="Не переносим", day=D1
    )  # у другой компании неперенесённая строка
    assert recon(company).status == "success"
    assert recon(other).status == "needs_review"
    with tenant_context(company.id):
        assert not FinanceMigrationIssue.objects.filter(issue_type="reconcile_diff").exists()


def test_reports_new_match_old_for_consistent_company(company):
    o1, _ = simple(company)
    from apps.forwarding.finance_lines.services import order_totals

    with tenant_context(company.id):
        order = Order.objects.get(pk=o1.pk)
        assert reports_new.order_totals_new(order) == order_totals(order)


def test_command_output_and_validation(company):
    simple(company)
    out = StringIO()
    call_command("reconcile_finance", "--company", str(company.id), stdout=out)
    text = out.getvalue()
    assert "success" in text and "legacy_missing" in text
    with pytest.raises(CommandError):
        call_command("reconcile_finance", "--company", "999999")
    with pytest.raises(CommandError):
        call_command("reconcile_finance", "--company", str(company.id), "--month", "2026-13")
    with tenant_context(company.id):
        assert FinanceMigrationRun.objects.filter(kind="reconcile").count() == 1
