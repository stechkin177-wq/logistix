# ruff: noqa: E501
"""Долги, просрочка и курсовые разницы в базовой валюте (1.4.14).

Математика (направление, знак, частичные оплаты, несколько курсов), курс на дату отчёта, смена
базы (prior_base), «без базового курса», двойной учёт, снимки при закрытии периода, права и
изоляция, backfill, Excel, legacy-совместимость.
"""

import io
from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal as D

import pytest
import time_machine
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from openpyxl import load_workbook

from apps.core.api.auth import issue_tokens
from apps.core.tenancy import tenant_context
from apps.finance import debts, debts_base, operations, periods, reports_new
from apps.finance.fx import change_base_currency
from apps.finance.models import (
    Expense,
    FxRevaluation,
    FxRevaluationLine,
    Income,
    Invoice,
    Payment,
)
from apps.finance.tests.helpers import (
    cur,
    first_user,
    issue_invoice,
    make_carrier,
    make_client,
    make_order,
    pay_invoice,
    set_rate,
)
from apps.finance.tests.p2_helpers import enable_new, set_engine
from apps.finance.tests.test_base_currency_reports import mk_expense, mk_income
from apps.finance.tests.test_finance_api import custom_client

pytestmark = pytest.mark.django_db
NOW = datetime(2026, 6, 20, 12, 0, tzinfo=dt_tz.utc)
TODAY = date(2026, 6, 20)
F = "/api/finance"


@pytest.fixture(autouse=True)
def frozen():
    with time_machine.travel(NOW, tick=False):
        yield


@pytest.fixture
def usd_rates(company):
    """USD: 450 (1 мая), 460 (20 мая), 480 (10 июня)."""
    set_rate(company, "USD", 450, date(2026, 5, 1))
    set_rate(company, "USD", 460, date(2026, 5, 20))
    set_rate(company, "USD", 480, date(2026, 6, 10))


def login(client, user, company):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")


def usd_invoice(company, amount="100", direction="out", day=date(2026, 5, 1), due=None, **kw):
    carrier = make_carrier(company, f"П{amount}{day}") if direction == "in" else None
    return issue_invoice(
        company,
        amount=amount,
        currency="USD",
        day=day,
        due=due,
        direction=direction,
        carrier=carrier,
        **kw,
    )


def get(client, path, **params):
    response = client.get(f"{F}/{path}", params)
    return response


def one(rows, name=None):
    return rows[0] if name is None else next(r for r in rows if r["name"] == name)


# --- снимки при создании ---------------------------------------------------------------------


def test_invoice_and_payment_store_base_snapshot_once(company, usd_rates):
    inv = usd_invoice(company, "100")
    pay = pay_invoice(company, inv, 40, day=date(2026, 5, 20))
    with tenant_context(company.id):
        inv, pay = Invoice.objects.get(pk=inv.pk), Payment.objects.get(pk=pay.pk)
        assert (inv.base_currency.code, inv.rate_to_base, inv.rate_to_base_date) == (
            "KZT",
            D("450.000000"),
            date(2026, 5, 1),
        )
        assert (pay.base_currency.code, pay.rate_to_base, pay.rate_to_base_date) == (
            "KZT",
            D("460.000000"),
            date(2026, 5, 20),
        )
        assert inv.rate_to_kzt == D("450.000000") and pay.rate_to_kzt == D("460.000000")
    set_rate(company, "USD", 999, date(2026, 6, 15))  # позже: снимок не пересчитывается
    with tenant_context(company.id):
        assert Invoice.objects.get(pk=inv.pk).rate_to_base == D("450.000000")


def test_missing_base_rate_leaves_nulls_and_does_not_block(company, usd_rates):
    set_rate(company, "RUB", 5, date(2026, 6, 15))
    with tenant_context(company.id):
        change_base_currency(company, cur(company, "RUB"), first_user(company), "тест")
    inv = usd_invoice(
        company, "10", day=date(2026, 5, 1)
    )  # на 1 мая курса RUB нет: курс к KZT есть
    with tenant_context(company.id):
        got = Invoice.objects.get(pk=inv.pk)
        assert got.status == "issued" and got.rate_to_kzt == D("450.000000")
        assert (got.base_currency, got.rate_to_base, got.rate_to_base_date) == (None, None, None)


# --- математика ----------------------------------------------------------------------------------


def test_receivable_unrealized_and_applied_rate(company, usd_rates):
    usd_invoice(company, "100")
    enable_new(company)
    with tenant_context(company.id):
        report = debts_base.debts_report("out", TODAY)
    row = one(report["results"])
    assert report["base_currency"] == "KZT" and report["is_partial"] is False
    assert row["balance"] == {"USD": D("100.00")}
    assert row["balance_base"] == D("48000.00") and row["carrying_base"] == D("45000.00")
    assert row["unrealized_diff"] == D("3000.00") and row["revalued_base"] == D("48000.00")
    assert row["applied_rate"]["USD"] == {
        "rate": D("480.000000"),
        "rate_date": date(2026, 6, 10),
        "source": "via_kzt",
    }
    # прежние поля (KZT по курсу счёта) не изменились
    assert row["balance_kzt"] == D("45000.00")


def test_payable_sign_is_opposite(company, usd_rates):
    usd_invoice(company, "100", direction="in")
    enable_new(company)
    with tenant_context(company.id):
        row = one(debts_base.debts_report("in", TODAY)["results"])
    assert row["unrealized_diff"] == D("-3000.00") and row["balance_base"] == D("48000.00")


def test_partial_payments_realized_only_paid_unrealized_only_open(company, usd_rates):
    inv = usd_invoice(company, "100")
    pay_invoice(company, inv, 30, day=date(2026, 5, 20))  # курс 460
    pay_invoice(company, inv, 10, day=date(2026, 6, 10))  # курс 480
    enable_new(company)
    with tenant_context(company.id):
        row = one(debts_base.debts_report("out", TODAY)["results"])
        base = debts_base.base_info()
        realized = debts_base.realized_summary(
            debts_base.realized_rows(Payment.objects.all(), base["id"])
        )
    # остаток 60 USD: нереализованная 60 * (480 - 450); оплачено: 30 * 10 + 10 * 30
    assert row["balance"] == {"USD": D("60.00")} and row["unrealized_diff"] == D("1800.00")
    assert realized["fx_realized_base"] == D("600.00") and realized["by_direction"]["out"] == D(
        "600.00"
    )
    # разделены: общей суммы одним числом нет
    assert "total" not in realized and realized["fx_realized_base"] != row["unrealized_diff"]


def test_realized_sign_for_incoming(company, usd_rates):
    inv = usd_invoice(company, "100", direction="in")
    pay_invoice(company, inv, 50, day=date(2026, 5, 20))  # 50 * (460 - 450) = 500 -> убыток
    enable_new(company)
    with tenant_context(company.id):
        base = debts_base.base_info()
        rows = debts_base.realized_rows(Payment.objects.all(), base["id"])
    assert rows[0]["fx_realized_base"] == D("-500.00") and rows[0]["fx_status"] == "ok"


def test_base_currency_invoice_has_zero_difference(company):
    inv = issue_invoice(company, amount="1000")  # KZT = база
    pay_invoice(company, inv, 300)
    enable_new(company)
    with tenant_context(company.id):
        row = one(debts_base.debts_report("out", TODAY)["results"])
        base = debts_base.base_info()
        realized = debts_base.realized_rows(Payment.objects.all(), base["id"])
    assert row["balance_base"] == D("700.00") == row["balance_kzt"]
    assert row["unrealized_diff"] == D("0.00") and row["carrying_base"] == D("700.00")
    assert realized[0]["fx_realized_base"] == D("0.00")
    assert row["applied_rate"]["KZT"]["source"] == "same"


def test_kzt_base_regression_matches_legacy_values(company, usd_rates):
    client = make_client(company, "Рег")
    kzt = issue_invoice(company, order=make_order(company, client=client), amount="1000")
    pay_invoice(company, kzt, 250)
    usd_invoice(
        company,
        "10",
        due=date(2026, 6, 1),
        order=make_order(company, client=client, currency="USD"),
    )
    with tenant_context(company.id):
        legacy = {r["name"]: r for r in debts.client_debts(TODAY)}["Рег"]
    enable_new(company)
    with tenant_context(company.id):
        new = {r["name"]: r for r in debts_base.debts_report("out", TODAY)["results"]}["Рег"]
    for key in ("issued_kzt", "paid_kzt", "balance_kzt", "overdue_kzt"):
        assert new[key] == legacy[key], key
    assert new["by_currency"]["USD"]["balance"] == legacy["by_currency"]["USD"]["balance"]
    # просрочены оба: USD (срок 1 июня) 10 * 480 и KZT-счёт (срок по умолчанию = день выставления)
    assert new["overdue_base"] == D("5550.00")


def test_different_as_of_uses_rate_on_that_date(company, usd_rates):
    usd_invoice(company, "100")
    enable_new(company)
    with tenant_context(company.id):
        a = one(debts_base.debts_report("out", date(2026, 5, 25))["results"])
        b = one(debts_base.debts_report("out", date(2026, 6, 12))["results"])
    assert a["applied_rate"]["USD"]["rate"] == D("460.000000")
    assert a["applied_rate"]["USD"]["rate_date"] == date(2026, 5, 20)
    assert a["balance_base"] == D("46000.00") and a["unrealized_diff"] == D("1000.00")
    assert b["balance_base"] == D("48000.00")


def test_as_of_reconstructs_state_payments_after_date_do_not_count(company, usd_rates):
    inv = usd_invoice(company, "100")
    pay_invoice(company, inv, 40, day=date(2026, 6, 10))
    enable_new(company)
    with tenant_context(company.id):
        before = one(debts_base.debts_report("out", date(2026, 6, 1))["results"])
        after = one(debts_base.debts_report("out", TODAY)["results"])
    assert before["balance"] == {"USD": D("100.00")} and after["balance"] == {"USD": D("60.00")}


def test_triangulation_usd_to_rub_through_kzt(company):
    set_rate(company, "USD", 450, date(2026, 5, 1))
    set_rate(company, "RUB", 5, date(2026, 5, 1))
    with tenant_context(company.id):
        change_base_currency(company, cur(company, "RUB"), first_user(company), "тест")
    usd_invoice(company, "100")  # снимок: 450 / 5 = 90 RUB за USD (через KZT)
    set_rate(company, "USD", 480, date(2026, 6, 10))
    set_rate(company, "RUB", 6, date(2026, 6, 10))  # 480 / 6 = 80
    enable_new(company)
    with tenant_context(company.id):
        report = debts_base.debts_report("out", TODAY)
    row = one(report["results"])
    assert report["base_currency"] == "RUB"
    assert row["applied_rate"]["USD"]["rate"] == D("80.000000")
    assert row["applied_rate"]["USD"]["source"] == "via_kzt"
    assert row["carrying_base"] == D("9000.00") and row["balance_base"] == D("8000.00")
    assert row["unrealized_diff"] == D("-1000.00") and report["is_partial"] is False


# --- смена базы, нет курса, нет базового курса ---------------------------------------------------


def test_missing_report_rate_is_no_rate_and_not_blocking(company, usd_rates):
    usd_invoice(company, "100")
    set_rate(company, "RUB", 5, date(2026, 6, 15))
    enable_new(company)
    with tenant_context(company.id):
        change_base_currency(company, cur(company, "RUB"), first_user(company), "тест")
        report = debts_base.debts_report("out", date(2026, 6, 10))  # RUB на эту дату нет
    row = one(report["results"])
    assert report["is_partial"] is True
    assert report["excluded"]["no_rate"]["count"] == 1
    assert report["excluded"]["no_rate"]["by_currency"]["USD"]["open"] == D("100.00")
    assert row["balance"] == {"USD": D("100.00")}  # исходная валюта показывается
    assert row["balance_base"] == D("0.00") and row["unrealized_diff"] == D("0.00")
    assert "USD" not in row["applied_rate"]


def test_base_switch_prior_base_is_separate_and_not_mixed(company, usd_rates):
    old = usd_invoice(company, "100")  # снимок в KZT
    set_rate(company, "RUB", 5, date(2026, 6, 1))
    with tenant_context(company.id):
        change_base_currency(company, cur(company, "RUB"), first_user(company), "тест")
    new = usd_invoice(company, "10", day=date(2026, 6, 12))  # снимок в RUB: 480 / 5 = 96
    enable_new(company)
    with tenant_context(company.id):
        assert Invoice.objects.get(pk=new.pk).rate_to_base == D("96.000000")
        report = debts_base.debts_report("out", TODAY)
    assert old.pk != new.pk
    row = report["results"][0] if len(report["results"]) == 1 else None
    assert row is not None or len(report["results"]) == 2
    total = report["totals"]
    # в итогах базы только пригодный счёт (10 USD * 96 = 960); прежняя база - отдельным блоком
    assert total["balance_base"] == D("960.00") and total["unrealized_diff"] == D("0.00")
    prior = report["excluded"]["prior_base"]
    assert prior["count"] == 1 and prior["by_currency"]["USD"]["open"] == D("100.00")
    assert prior["by_currency"]["USD"]["equivalent_base"] == D("9600.00")  # справочно, не в итогах
    assert report["is_partial"] is True


def test_invoice_without_base_rate_shows_equivalent_but_no_difference(company, usd_rates):
    inv = usd_invoice(company, "100")
    with tenant_context(company.id):
        Invoice.objects.filter(pk=inv.pk).update(
            base_currency=None, rate_to_base=None, rate_to_base_date=None
        )
    enable_new(company)
    with tenant_context(company.id):
        report = debts_base.debts_report("out", TODAY)
    row = one(report["results"])
    assert row["balance_base"] == D("48000.00") and row["carrying_base"] == D("0.00")
    assert row["unrealized_diff"] == D("0.00")
    assert report["excluded"]["no_base_rate"]["count"] == 1 and report["is_partial"] is True


def test_realized_excludes_payments_without_base_rate_or_other_base(company, usd_rates):
    inv = usd_invoice(company, "100")
    p1 = pay_invoice(company, inv, 10, day=date(2026, 5, 20))
    p2 = pay_invoice(company, inv, 10, day=date(2026, 5, 20))
    with tenant_context(company.id):
        Payment.objects.filter(pk=p1.pk).update(rate_to_base=None, base_currency=None)
        other = cur(company, "USD")
        Payment.objects.filter(pk=p2.pk).update(base_currency=other)
    enable_new(company)
    with tenant_context(company.id):
        base = debts_base.base_info()
        summary = debts_base.realized_summary(
            debts_base.realized_rows(Payment.objects.all(), base["id"])
        )
    assert summary["fx_realized_base"] == D("0.00") and summary["is_partial"] is True
    assert summary["excluded"]["no_base_rate"]["count"] == 1
    assert summary["excluded"]["prior_base"]["count"] == 1


# --- просрочка -------------------------------------------------------------------------------------


def test_overdue_boundary_in_company_timezone(company, usd_rates):
    client = make_client(company, "Граница")
    kw = {"order": None}
    for amount, due in (("100", date(2026, 6, 19)), ("50", date(2026, 6, 20))):
        # 19 июня просрочен; срок сегодня (20 июня) - не просрочен
        kw["order"] = make_order(company, client=client, currency="USD")
        usd_invoice(company, amount, due=due, **kw)
    enable_new(company)
    # 19 июня 20:00 UTC = 20 июня 01:00 в Алматы: сегодня компании - 20 июня
    with time_machine.travel(datetime(2026, 6, 19, 20, 0, tzinfo=dt_tz.utc), tick=False):
        from apps.forwarding.finance_lines.models import company_today

        today = company_today(company.id)
        assert today == date(2026, 6, 20)
        with tenant_context(company.id):
            row = one(debts_base.debts_report("out", today)["results"])
    assert row["overdue"] == {"USD": D("100.00")} and row["balance"] == {"USD": D("150.00")}
    assert row["overdue_base"] == D("48000.00") and row["balance_base"] == D("72000.00")


def test_overdue_partially_paid_counts_open_balance_only(company, usd_rates):
    inv = usd_invoice(company, "100", due=date(2026, 6, 1))
    pay_invoice(company, inv, 25, day=date(2026, 5, 20))
    enable_new(company)
    with tenant_context(company.id):
        row = one(debts_base.debts_report("out", TODAY)["results"])
    assert row["overdue"] == {"USD": D("75.00")} and row["overdue_base"] == D("36000.00")


# --- двойной учёт ----------------------------------------------------------------------------------


def snapshot_profit(company, order):
    enable_new(company)
    with tenant_context(company.id):
        totals = reports_new.order_totals_new(order)
        month = reports_new.month_totals_new(company, date(2026, 6, 1), date(2026, 7, 1))
        journal = operations.journal_summary(company.id)
        counts = (
            Income.objects.count(),
            Expense.objects.count(),
            sum(i.amount for i in Income.objects.all()),
            sum(e.amount for e in Expense.objects.all()),
        )
    return (
        {k: totals[k] for k in ("revenue", "cost", "profit", "margin_pct")},
        {k: month[k] for k in ("month_profit", "month_margin_pct", "revenue", "cost")},
        {k: journal[k] for k in ("income_kzt", "expense_kzt", "diff_kzt")},
        counts,
    )


def test_payment_at_other_rate_changes_only_differences_not_income_expense_profit(
    company, usd_rates
):
    set_engine(company, "legacy")
    order = make_order(company, currency="USD")
    inv = issue_invoice(company, order=order, amount="100", currency="USD", day=date(2026, 6, 1))
    enable_new(company)
    mk_income(company, order, 100, day=date(2026, 6, 10))
    mk_expense(company, order, 40, day=date(2026, 6, 10))
    before = snapshot_profit(company, order)
    pay_invoice(company, inv, 100, day=date(2026, 6, 15))  # курс 480 против курса счёта 450
    after = snapshot_profit(company, order)
    assert before == after
    with tenant_context(company.id):
        base = debts_base.base_info()
        rows = debts_base.realized_rows(Payment.objects.all(), base["id"])
    assert rows[0]["fx_realized_base"] == D("2000.00")  # 100 * (480 - 460): отдельно от прибыли


# --- снимки закрытия периода -------------------------------------------------------------------------


def close_may(company):
    with tenant_context(company.id):
        return periods.close_period(company, 2026, 5, first_user(company))


def test_close_period_in_new_creates_snapshot_and_report_reads_it(
    company, admin_client, admin_user, usd_rates
):
    inv = usd_invoice(company, "100")
    pay_invoice(company, inv, 40, day=date(2026, 5, 20))
    enable_new(company)
    close_may(company)
    with tenant_context(company.id):
        reval = FxRevaluation.objects.get(kind="period_close")
        line = reval.lines.get()
    assert reval.as_of == date(2026, 5, 31) and reval.period.month == 5
    # на 31 мая курс USD = 460: остаток 60, переоценка 60 * (460 - 450)
    assert (line.open_balance, line.applied_rate, line.applied_rate_date) == (
        D("60.00"),
        D("460.000000"),
        date(2026, 5, 20),
    )
    assert (line.carrying_base, line.current_base, line.unrealized_diff) == (
        D("27000.00"),
        D("27600.00"),
        D("600.00"),
    )
    assert reval.summary["clients"]["unrealized_diff"] == "600.00"
    # курс меняется ПОСЛЕ закрытия: снимок и отчёт по периоду не меняются, живой отчёт - меняется
    set_rate(company, "USD", 500, date(2026, 6, 18))
    with tenant_context(company.id):
        fresh = FxRevaluationLine.objects.get(pk=line.pk)
        assert (fresh.unrealized_diff, fresh.applied_rate) == (D("600.00"), D("460.000000"))
    login(admin_client, admin_user, company)
    snap = get(admin_client, "debts/clients/", period="2026-05").json()
    live = get(admin_client, "debts/clients/").json()
    assert snap["source"] == "snapshot" and snap["results"][0]["unrealized_diff"] == "600.00"
    assert live["source"] == "live" and live["results"][0]["unrealized_diff"] == "3000.00"
    assert get(admin_client, "debts/clients/", period="2026-04").status_code == 404
    assert get(admin_client, "debts/clients/", period="bad").status_code == 400


def test_close_period_without_rate_is_not_blocked_lines_flagged(company, usd_rates):
    usd_invoice(company, "100")
    set_rate(company, "RUB", 5, date(2026, 6, 15))
    enable_new(company)
    with tenant_context(company.id):
        change_base_currency(company, cur(company, "RUB"), first_user(company), "тест")
    period = close_may(company)
    assert period.status == "closed"
    with tenant_context(company.id):
        line = FxRevaluation.objects.get(kind="period_close").lines.get()
    assert line.flags["status"] == "no_rate" and line.current_base is None
    assert line.unrealized_diff is None and line.open_balance == D("100.00")


def test_close_period_legacy_makes_no_snapshot(company, usd_rates):
    usd_invoice(company, "100")
    close_may(company)
    with tenant_context(company.id):
        assert FxRevaluation.objects.count() == 0


def test_snapshots_are_immutable(company, usd_rates):
    usd_invoice(company, "100")
    enable_new(company)
    close_may(company)
    with tenant_context(company.id):
        reval = FxRevaluation.objects.get()
        line = reval.lines.get()
        reval.summary = {}
        with pytest.raises(Exception, match="изменять нельзя"):
            reval.save()
        with pytest.raises(Exception, match="удалять нельзя"):
            reval.delete()
        line.flags = {}
        with pytest.raises(Exception, match="изменять нельзя"):
            line.save()
        with pytest.raises(Exception, match="удалять нельзя"):
            line.delete()


def test_on_demand_revaluation_api_permissions_and_readonly(
    company, admin_client, admin_user, usd_rates
):
    usd_invoice(company, "100")
    enable_new(company)
    login(admin_client, admin_user, company)
    created = admin_client.post(f"{F}/fx-revaluations/", {"as_of": "2026-06-12"}, format="json")
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["kind"] == "report" and body["summary"]["clients"]["unrealized_diff"] == "3000.00"
    assert (
        admin_client.post(
            f"{F}/fx-revaluations/", {"as_of": "2026-07-01"}, format="json"
        ).status_code
        == 400
    )
    assert admin_client.post(f"{F}/fx-revaluations/", {}, format="json").status_code == 400
    one_id = body["id"]
    assert get(admin_client, f"fx-revaluations/{one_id}/").status_code == 200
    lines = get(admin_client, f"fx-revaluations/{one_id}/lines/").json()
    assert lines["results"][0]["unrealized_diff"] == "3000.00"
    for method in ("patch", "put", "delete"):
        assert getattr(admin_client, method)(f"{F}/fx-revaluations/{one_id}/").status_code == 405
    # права: просмотр - finance.view; создание - close_period или manage_settings
    viewer = custom_client(company, ["finance.view"])
    assert get(viewer, "fx-revaluations/").status_code == 200
    assert (
        viewer.post(f"{F}/fx-revaluations/", {"as_of": "2026-06-12"}, format="json").status_code
        == 403
    )
    manager = custom_client(company, ["finance.view", "finance.manage_settings"])
    assert (
        manager.post(f"{F}/fx-revaluations/", {"as_of": "2026-06-12"}, format="json").status_code
        == 201
    )
    closer = custom_client(company, ["finance.view", "finance.close_period"])
    assert (
        closer.post(f"{F}/fx-revaluations/", {"as_of": "2026-06-12"}, format="json").status_code
        == 201
    )
    nobody = custom_client(company, ["orders.view"])
    assert get(nobody, "fx-revaluations/").status_code == 403
    assert get(nobody, "debts/clients/").status_code == 403


def test_revaluation_requires_new_engine(company, admin_client, admin_user, usd_rates):
    login(admin_client, admin_user, company)
    r = admin_client.post(f"{F}/fx-revaluations/", {"as_of": "2026-06-12"}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "engine_not_new"


def test_isolation_between_companies(company, admin_client, admin_user, make_company, usd_rates):
    usd_invoice(company, "100")
    enable_new(company)
    other, other_admin, other_client = make_company("Другая")
    set_rate(other, "USD", 450, date(2026, 5, 1))
    enable_new(other)
    login(admin_client, admin_user, company)
    created = admin_client.post(
        f"{F}/fx-revaluations/", {"as_of": "2026-06-12"}, format="json"
    ).json()
    assert get(other_client, "debts/clients/").json()["results"] == []
    assert get(other_client, "fx-revaluations/").json()["results"] == []
    assert get(other_client, f"fx-revaluations/{created['id']}/").status_code == 404
    assert get(other_client, f"fx-revaluations/{created['id']}/lines/").status_code == 404
    assert get(other_client, "debts/clients/", period="2026-05").status_code == 404
    assert len(get(admin_client, "debts/clients/").json()["results"]) == 1


# --- API: долги, сводка, оплаты, журнал, Excel ---------------------------------------------------


def test_debts_api_new_shape_and_legacy_unchanged(company, admin_client, admin_user, usd_rates):
    usd_invoice(company, "100")
    login(admin_client, admin_user, company)
    legacy = get(admin_client, "debts/clients/").json()
    assert set(legacy) == {"results"} and "balance_base" not in legacy["results"][0]
    set_engine(company, "shadow")
    assert set(get(admin_client, "debts/clients/").json()) == {"results"}
    enable_new(company)
    data = get(admin_client, "debts/clients/").json()
    assert data["base_currency"] == "KZT" and data["as_of"] == "2026-06-20"
    assert data["is_partial"] is False and data["excluded"]["count"] == 0
    row = data["results"][0]
    assert row["balance"] == {"USD": "100.00"} and row["balance_base"] == "48000.00"
    assert row["applied_rate"]["USD"] == {
        "rate": "480.000000",
        "rate_date": "2026-06-10",
        "source": "via_kzt",
    }
    assert row["carrying_base"] == "45000.00" and row["unrealized_diff"] == "3000.00"
    assert row["balance_kzt"] == "45000.00"
    past = get(admin_client, "debts/clients/", as_of="2026-05-25").json()
    assert past["as_of"] == "2026-05-25" and past["results"][0]["balance_base"] == "46000.00"
    assert get(admin_client, "debts/clients/", as_of="2026-07-01").status_code == 400
    assert get(admin_client, "debts/clients/", as_of="garbage").status_code == 400


def test_carrier_debts_api(company, admin_client, admin_user, usd_rates):
    usd_invoice(company, "100", direction="in")
    enable_new(company)
    login(admin_client, admin_user, company)
    data = get(admin_client, "debts/carriers/").json()
    assert data["results"][0]["unrealized_diff"] == "-3000.00"


def test_summary_realized_and_unrealized_are_separate_fields(
    company, admin_client, admin_user, usd_rates
):
    inv = usd_invoice(company, "100")
    pay_invoice(company, inv, 40, day=date(2026, 6, 10))  # 40 * (480 - 450) = 1200 в июне
    usd_invoice(company, "20", direction="in")
    login(admin_client, admin_user, company)
    legacy = get(admin_client, "summary/").json()
    assert "fx_realized_base" not in legacy and "fx_difference_kzt" in legacy
    enable_new(company)
    s = get(admin_client, "summary/").json()
    assert s["base_currency"] == "KZT"
    assert s["fx_realized_base"] == "1200.00"
    assert s["fx_unrealized_clients_base"] == "1800.00"  # 60 * (480 - 450)
    assert s["fx_unrealized_payables_base"] == "-600.00"  # 20 * 30, входящий
    assert s["fx_unrealized_base"] == "1200.00"
    assert not [k for k in s if "total" in k and "fx" in k]  # общего «итого разница» нет
    assert s["client_debt_base"] == "28800.00" and s["payable_base"] == "9600.00"
    assert s["debts_partial"] is False and s["fx_realized_partial"] is False
    assert s["fx_difference_kzt"] == "1200.00"  # прежнее поле сохранено


def test_payments_journal_new_fields_and_legacy_unchanged(
    company, admin_client, admin_user, usd_rates
):
    inv = usd_invoice(company, "100")
    pay_invoice(company, inv, 40, day=date(2026, 5, 20))
    login(admin_client, admin_user, company)
    legacy = get(admin_client, "payments/").json()
    assert "summary" not in legacy and "fx_realized_base" not in legacy["results"][0]
    enable_new(company)
    data = get(admin_client, "payments/").json()
    pay = data["results"][0]
    assert pay["fx_realized_base"] == "400.00" and pay["fx_status"] == "ok"
    assert pay["rate_to_base"] == "460.000000" and pay["invoice_rate_to_base"] == "450.000000"
    assert (
        data["summary"]["fx_realized_base"] == "400.00" and data["summary"]["is_partial"] is False
    )
    assert data["summary"]["base_currency"] == "KZT"
    assert (
        get(admin_client, "payments/", date_from="2026-06-01").json()["summary"]["fx_realized_base"]
        == "0.00"
    )


def test_fx_differences_section_is_separate_from_income_expense(
    company, admin_client, admin_user, usd_rates
):
    inv = usd_invoice(company, "100")
    pay_invoice(company, inv, 40, day=date(2026, 5, 20))
    enable_new(company)
    login(admin_client, admin_user, company)
    ops_before = get(admin_client, "operations/").json()["summary"]
    data = get(admin_client, "operations/fx-differences/").json()
    assert data["results"][0]["fx_realized_base"] == "400.00"
    assert data["results"][0]["invoice"]["direction"] == "out"
    assert data["summary"]["fx_realized_base"] == "400.00"
    assert get(admin_client, "operations/").json()["summary"] == ops_before
    assert get(admin_client, "operations/fx-differences/", direction="x").status_code == 400
    set_engine(company, "legacy")
    assert get(admin_client, "operations/fx-differences/").status_code == 409


def test_excel_debts_and_operations_fx_sheet(company, admin_client, admin_user, usd_rates):
    inv = usd_invoice(company, "100", due=date(2026, 6, 1))
    pay_invoice(company, inv, 40, day=date(2026, 5, 20))
    login(admin_client, admin_user, company)
    assert get(admin_client, "debts/clients/export/").status_code == 409  # legacy
    enable_new(company)
    r = get(admin_client, "debts/clients/export/")
    assert r.status_code == 200
    ws = load_workbook(io.BytesIO(r.content)).active
    rows = list(ws.values)
    assert rows[0][2] == "Остаток, исходная валюта" and rows[0][3] == "Эквивалент в базе, KZT"
    assert "Просрочено, исходная валюта" in rows[0] and "Просрочено, KZT" in rows[0]
    assert "Курсовая разница нереализованная, KZT" in rows[0] and "Пометка о неполноте" in rows[0]
    assert rows[1][1] == "USD" and rows[1][2] == D("60") and rows[1][3] == D("28800")
    assert rows[1][7] == D("60") and rows[1][8] == D("28800") and rows[1][10] == D("1800")
    ops = get(admin_client, "operations/export/")
    wb = load_workbook(io.BytesIO(ops.content))
    assert wb.sheetnames == ["Операции", "Курсовые разницы"]
    fx_rows = list(wb["Курсовые разницы"].values)
    assert "Курсовая разница реализованная, KZT" in fx_rows[0][7] and fx_rows[1][7] == D("400")
    assert get(admin_client, "debts/carriers/export/").status_code == 200


def test_debts_query_count_does_not_grow_with_invoices(
    company, admin_client, admin_user, usd_rates
):
    login(admin_client, admin_user, company)
    usd_invoice(company, "10")
    enable_new(company)
    with CaptureQueriesContext(connection) as small:
        assert get(admin_client, "debts/clients/").status_code == 200
    set_engine(company, "legacy")
    for i in range(10):
        usd_invoice(company, str(11 + i))
    enable_new(company)
    with CaptureQueriesContext(connection) as large:
        assert get(admin_client, "debts/clients/").status_code == 200
    assert len(large) == len(small)


# --- backfill --------------------------------------------------------------------------------------


def clear_snapshots(company):
    with tenant_context(company.id):
        Invoice.all_objects.update(base_currency=None, rate_to_base=None, rate_to_base_date=None)
        Payment.all_objects.update(base_currency=None, rate_to_base=None, rate_to_base_date=None)


def test_backfill_deterministic_case_idempotent_and_dry_run(company, usd_rates, capsys):
    inv = usd_invoice(company, "100")
    pay = pay_invoice(company, inv, 40, day=date(2026, 5, 20))
    clear_snapshots(company)
    with tenant_context(company.id):
        inv_before = Invoice.objects.values("total_gross", "rate_to_kzt", "currency_id").get(
            pk=inv.pk
        )
    call_command("backfill_fx_base_snapshots", company=company.id, dry_run=True)
    out = capsys.readouterr().out
    assert "ПРОБНЫЙ" in out and "будет заполнено 1" in out
    with tenant_context(company.id):
        assert Invoice.objects.get(pk=inv.pk).rate_to_base is None  # dry-run не пишет
    call_command("backfill_fx_base_snapshots", company=company.id)
    with tenant_context(company.id):
        got, pay_got = Invoice.objects.get(pk=inv.pk), Payment.objects.get(pk=pay.pk)
        assert (got.base_currency.code, got.rate_to_base, got.rate_to_base_date) == (
            "KZT",
            D("450.000000"),
            date(2026, 5, 1),
        )
        assert (pay_got.rate_to_base, pay_got.rate_to_base_date) == (
            D("460.000000"),
            date(2026, 5, 20),
        )
        assert (
            Invoice.objects.values("total_gross", "rate_to_kzt", "currency_id").get(pk=inv.pk)
            == inv_before
        )
    call_command("backfill_fx_base_snapshots", company=company.id)  # повтор: ничего не меняется
    assert "заполнено 0" in capsys.readouterr().out
    with tenant_context(company.id):
        assert Invoice.objects.get(pk=inv.pk).rate_to_base == D("450.000000")


def test_backfill_does_not_touch_other_cases(company, usd_rates, capsys):
    inv = usd_invoice(company, "100")
    clear_snapshots(company)
    set_rate(company, "RUB", 5, date(2026, 6, 1))
    with tenant_context(company.id):
        change_base_currency(company, cur(company, "RUB"), first_user(company), "тест")
    call_command("backfill_fx_base_snapshots", company=company.id)
    assert "не применим" in capsys.readouterr().out
    with tenant_context(company.id):
        got = Invoice.objects.get(pk=inv.pk)
        assert got.base_currency is None and got.rate_to_base is None
