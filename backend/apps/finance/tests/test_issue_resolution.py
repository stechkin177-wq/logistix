"""Решения по спорным строкам переноса и группировка сумм (замечания заказчика к П3, 0.1-0.3)."""

import json

import pytest
from django.core.management import call_command

from apps.core.tenancy import tenant_context
from apps.finance import migration, reconcile
from apps.finance.errors import FinanceError
from apps.finance.management.commands.migrate_finance import created_sums
from apps.finance.models import (
    Expense,
    ExpenseAllocation,
    FinanceMigrationIssue,
    Income,
)
from apps.finance.tests.p2_helpers import new_trip, order_with_cargos
from apps.finance.tests.test_migrate_finance import (
    build,
    counts,
    run_cmd,
    snapshot,
)
from apps.forwarding.models import Trip

pytestmark = pytest.mark.django_db


def issue_of(company, line):
    with tenant_context(company.id):
        return FinanceMigrationIssue.objects.get(
            issue_type="ambiguous_trip_expense", source_id=line.pk
        )


def resolve(company, line, resolution, note="Решение принято вручную", **params):
    issue = issue_of(company, line)
    with tenant_context(company.id):
        return migration.resolve_issue(issue, None, note, resolution, **params)


def trip_of_title(company, line):
    with tenant_context(company.id):
        return Trip.objects.get(number=line.title.split()[1])


def test_carrier_expense_resolution_extends_one_expense_and_is_idempotent(company):
    s = build(company)
    run_cmd(company)
    trip = trip_of_title(company, s["foreign"])
    # строка чужого заказа и вторая строка того же рейса -> ОДИН расход перевозчика
    resolve(company, s["foreign"], "carrier_expense", trip=trip.number)
    resolve(company, s["foreign_ok"], "carrier_expense", trip=trip.pk)
    with tenant_context(company.id):
        expenses = Expense.objects.filter(trip=trip, kind="carrier_transport", status="active")
        assert expenses.count() == 1
        exp = expenses.get()
        assert exp.source == "migrated" and exp.amount == 14
        allocs = ExpenseAllocation.objects.filter(expense=exp)
        assert sorted(a.legacy_line_id for a in allocs) == sorted(
            [s["foreign"].pk, s["foreign_ok"].pk]
        )
        assert exp.needs_review and exp.review_reason == "migrated_mismatch"  # 14 != 7
        row = FinanceMigrationIssue.objects.get(source_id=s["foreign"].pk)
        assert row.status == "resolved" and row.resolution == "carrier_expense"
        assert row.resolution_data == {"trip": trip.pk}
    # повторный перенос: 0 изменений, 0 новых проблем
    before, snap = counts(company), snapshot(company)
    out = run_cmd(company)
    assert counts(company) == before and snapshot(company) == snap
    assert "issues_new" not in out


def test_manual_expense_resolution(company):
    s = build(company)
    run_cmd(company)
    resolve(company, s["no_trip"], "manual_expense", category="OTHER")
    with tenant_context(company.id):
        exp = Expense.objects.get(legacy_group_key=f"line:{s['no_trip'].pk}")
        assert exp.kind == "other" and exp.source == "migrated" and exp.amount == 10
        assert exp.category.code == "OTHER"
        alloc = ExpenseAllocation.objects.get(expense=exp)
        assert alloc.legacy_line_id == s["no_trip"].pk and alloc.order_id == s["no_trip"].order_id
    before, snap = counts(company), snapshot(company)
    run_cmd(company)
    assert counts(company) == before and snapshot(company) == snap


def test_justified_exclusion_requires_note_and_stays_unreflected(company):
    s = build(company)
    run_cmd(company)
    issue = issue_of(company, s["currency"])
    with tenant_context(company.id):
        with pytest.raises(FinanceError) as exc:
            migration.resolve_issue(issue, None, "коротко", "justified_exclusion")
        assert exc.value.detail.code == "justification_required"
        with pytest.raises(FinanceError) as exc:
            migration.resolve_issue(issue, None, "Подробное обоснование")
        assert exc.value.detail.code == "resolution_required"
        migration.resolve_issue(issue, None, "Расход списан по акту №5", "justified_exclusion")
        assert not ExpenseAllocation.objects.filter(legacy_line=s["currency"]).exists()
    before = counts(company)
    run_cmd(company)  # строка пропущена, новой проблемы нет
    assert counts(company) == before
    run = reconcile.reconcile(company.id)
    listed = [r for r in run.summary["not_reflected"] if r["line"] == s["currency"].pk]
    assert listed and "акту №5" in listed[0]["reason"]
    assert run.status == "needs_review"


def test_impossible_carrier_resolutions_are_refused_with_message(company):
    s = build(company)
    run_cmd(company)
    no_carrier_trip = trip_of_title(company, s["no_carrier"])
    ok_trip = trip_of_title(company, s["foreign"])
    usd_trip = trip_of_title(company, s["currency"])
    cases = [
        (s["no_carrier"], no_carrier_trip.number),  # у рейса нет перевозчика
        (s["currency"], usd_trip.number),  # валюта заказа != валюте рейса
        (s["no_trip"], "НЕТ-ТАКОГО"),  # рейс не найден
        (s["no_trip"], 99999999),
    ]
    for line, trip in cases:
        with pytest.raises(FinanceError) as exc:
            resolve(company, line, "carrier_expense", trip=trip)
        assert exc.value.detail.code in ("resolution_impossible", "trip_not_found")
    with pytest.raises(FinanceError) as exc:  # рейс не указан
        resolve(company, s["no_trip"], "carrier_expense")
    assert exc.value.detail.code == "trip_required"
    # на рейс уже есть расход группы (другой ключ) - отказ и подсказка про другой вариант
    group_trip = s["trip"]
    with pytest.raises(FinanceError) as exc:
        resolve(company, s["foreign"], "carrier_expense", trip=group_trip.number)
    assert exc.value.detail.code == "resolution_impossible"
    assert "другой вариант" in str(exc.value.detail)
    # ни одна проблема не разрешена, данных не добавилось
    with tenant_context(company.id):
        assert not FinanceMigrationIssue.objects.filter(
            issue_type="ambiguous_trip_expense", status="resolved"
        ).exists()
    assert ok_trip


def test_unknown_category_and_foreign_company_issue_isolated(company, make_company):
    other, _, _ = make_company("Other")
    s = build(company)
    run_cmd(company)
    with pytest.raises(FinanceError) as exc:
        resolve(company, s["no_trip"], "manual_expense", category="НЕТ")
    assert exc.value.detail.code == "category_not_found"
    # проблема чужой компании не разрешается в контексте другой
    issue = issue_of(company, s["no_trip"])
    with tenant_context(other.id):
        with pytest.raises(FinanceIssueMissing):
            migration.resolve_issue(issue, None, "Подробное обоснование", "justified_exclusion")


FinanceIssueMissing = (FinanceMigrationIssue.DoesNotExist, FinanceError)


def test_dry_run_applies_nothing_after_resolution(company):
    s = build(company)
    run_cmd(company)
    resolve(company, s["no_trip"], "manual_expense")
    with tenant_context(company.id):  # имитируем потерю зеркала: доли нет
        ExpenseAllocation.objects.filter(legacy_line=s["no_trip"]).delete()
        Expense.objects.filter(legacy_group_key=f"line:{s['no_trip'].pk}").delete()
    before = counts(company)
    out = run_cmd(company, "--dry-run")
    assert counts(company) == before and "X-999" not in out  # решённая строка не спорная
    run_cmd(company)  # применение создаёт по сохранённому решению
    with tenant_context(company.id):
        assert Expense.objects.filter(legacy_group_key=f"line:{s['no_trip'].pk}").exists()
        assert FinanceMigrationIssue.objects.filter(source_id=s["no_trip"].pk).count() == 1


def test_resolve_command_with_resolution_params(company):
    s = build(company)
    run_cmd(company)
    issue = issue_of(company, s["foreign"])
    trip = trip_of_title(company, s["foreign"])
    call_command(
        "resolve_finance_issue", "--issue", str(issue.pk), "--note", "Это рейс клиента",
        "--resolution", "carrier_expense", "--trip", trip.number,
    )  # fmt: skip
    with tenant_context(company.id):
        assert ExpenseAllocation.objects.filter(legacy_line=s["foreign"]).exists()


def test_unique_open_or_resolved_issue_per_line(company):
    s = build(company)
    run_cmd(company)
    from django.db import IntegrityError, transaction

    with tenant_context(company.id), pytest.raises(IntegrityError), transaction.atomic():
        FinanceMigrationIssue.objects.create(
            company_id=company.id,
            issue_type="ambiguous_trip_expense",
            source_model=migration.SOURCE_MODEL,
            source_id=s["no_trip"].pk,
            message="дубль",
        )


# --- 0.3 плановый доход и группировка сумм ----------------------------------------------------


def test_planned_income_does_not_break_summaries(company):
    """Незавершённый рейс: плановый Income (recognized_on пусто) не ломает перенос/сверку/сводки."""
    build(company)
    order, ids = order_with_cargos(company, 1)
    new_trip(company, ids, price="100")
    from apps.finance.income import sync_planned_freight
    from apps.finance.reports_new import operations_by_currency_new

    with tenant_context(company.id):
        planned = sync_planned_freight(order)  # плановый доход без legacy_line и без даты
        assert planned.recognized_on is None and planned.legacy_line_id is None
    run_cmd(company)
    with tenant_context(company.id):
        # доход со строкой-источником, но без даты признания (плановый)
        legacy_income = Income.objects.filter(legacy_line__isnull=False).order_by("pk").first()
        line_date = legacy_income.legacy_line.date
        Income.objects.filter(pk=legacy_income.pk).update(
            status="planned", recognized_on=None, base_amount=None
        )
        sums = created_sums(company.id)
        operations_by_currency_new()  # плановые доходы без даты не падают
    assert "None" not in json.dumps(sums)
    # сумма дохода сгруппирована по дате ИСХОДНОЙ строки, а не по дате создания записи
    month = f"{line_date:%Y-%m}"
    assert float(sums[legacy_income.currency.code][month]["income"]) >= float(legacy_income.amount)
    run = reconcile.reconcile(company.id)  # не падает
    assert run.summary["lines_total"] > 0 and run.status == "needs_review"
    with tenant_context(company.id):  # плановый Income без legacy_line вне сумм переноса
        assert Income.objects.filter(legacy_line__isnull=True, status="planned").count() == 1
