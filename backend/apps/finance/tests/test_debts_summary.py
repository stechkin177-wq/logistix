from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal as D

import pytest
import time_machine

from apps.core.tenancy import tenant_context
from apps.finance import debts, summary
from apps.finance.tests.helpers import (
    add_line,
    issue_invoice,
    make_carrier,
    make_client,
    make_order,
    pay_invoice,
    set_rate,
)

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 5, 20, 12, 0, tzinfo=dt_tz.utc)
TODAY = date(2026, 5, 20)


@pytest.fixture(autouse=True)
def frozen():
    with time_machine.travel(NOW, tick=False):
        yield


def by_name(rows):
    return {r["name"]: r for r in rows}


def test_client_debt_counts_only_issued_balance(company):
    client = make_client(company, "А", credit_limit=2000)
    order = make_order(company, client=client)
    inv = issue_invoice(company, order=order, amount="1000", due=date(2026, 6, 1))
    pay_invoice(company, inv, 300)
    with tenant_context(company.id):  # черновик и отменённый не в долге
        from apps.finance import invoices as svc
        from apps.finance.tests.helpers import cur, first_user, vat

        line = add_line(company, order, income=500)
        svc.create_draft(
            direction="out",
            party=client,
            order=order,
            currency=cur(company),
            vat_rate=vat(company),
            items=[{"title": "d", "amount_net": D("500"), "line": line}],
            user=first_user(company),
        )
        rows = by_name(debts.client_debts(TODAY))
    a = rows["А"]
    assert (a["issued_kzt"], a["paid_kzt"], a["balance_kzt"]) == (
        D("1000.00"),
        D("300.00"),
        D("700.00"),
    )
    assert a["overdue_kzt"] == D("0.00")
    assert a["credit_limit"] == D("2000.00") and a["limit_usage_pct"] == D("35.00")


def test_overdue_vs_not_due(company):
    client = make_client(company, "Б")
    order = make_order(company, client=client)
    issue_invoice(company, order=order, amount="400", due=date(2026, 5, 19))  # просрочен
    issue_invoice(company, order=order, amount="100", due=date(2026, 5, 20))  # срок сегодня
    with tenant_context(company.id):
        row = by_name(debts.client_debts(TODAY))["Б"]
    assert row["balance_kzt"] == D("500.00") and row["overdue_kzt"] == D("400.00")


def test_by_currency_breakdown(company):
    set_rate(company, "USD", 450, day=date(2026, 5, 1))
    client = make_client(company, "В")
    kz = make_order(company, client=client)
    us = make_order(company, client=client, currency="USD")
    issue_invoice(company, order=kz, amount="1000")
    issue_invoice(company, order=us, amount="10", currency="USD", due=date(2026, 6, 1))
    with tenant_context(company.id):
        row = by_name(debts.client_debts(TODAY))["В"]
    assert row["balance_kzt"] == D("5500.00")
    assert row["by_currency"]["USD"] == {
        "issued": D("10.00"),
        "paid": D("0.00"),
        "balance": D("10.00"),
    }


def test_limit_usage_none_when_zero_limit(company):
    client = make_client(company, "Г")
    issue_invoice(company, order=make_order(company, client=client), amount="100")
    with tenant_context(company.id):
        assert by_name(debts.client_debts(TODAY))["Г"]["limit_usage_pct"] is None


def test_empty_company_returns_zeros(company):
    with tenant_context(company.id):
        assert debts.client_debts(TODAY) == [] and debts.carrier_debts(TODAY) == []
        s = summary.finance_summary(TODAY)
    for key in (
        "client_debt_kzt",
        "overdue_kzt",
        "payable_kzt",
        "month_profit_kzt",
        "fx_difference_kzt",
    ):
        assert s[key] == D("0.00")
    assert s["month_margin_pct"] is None and s["currency"] == "KZT"


def test_carrier_debts_and_payable(company):
    carrier = make_carrier(company, "Перевозчик К")
    order = make_order(company)
    issue_invoice(
        company, order=order, amount="800", direction="in", carrier=carrier, due=date(2026, 5, 1)
    )
    with tenant_context(company.id):
        row = by_name(debts.carrier_debts(TODAY))["Перевозчик К"]
        s = summary.finance_summary(TODAY)
    assert row["balance_kzt"] == D("800.00") and row["overdue_kzt"] == D("800.00")
    assert "credit_limit" not in row
    assert s["payable_kzt"] == D("800.00") and s["client_debt_kzt"] == D("0.00")


def test_summary_month_profit_matches_dashboard_for_kzt(admin_client, company):
    order = make_order(company)
    add_line(company, order, income=1000, expense=400, day=date(2026, 5, 10))
    add_line(company, order, income=500, expense=0, day=date(2026, 4, 30))  # прошлый месяц
    with tenant_context(company.id):
        s = summary.finance_summary(TODAY)
    assert s["month_profit_kzt"] == D("600.00")
    assert s["month_margin_pct"] == D("60.00")
    dash = admin_client.get("/api/dashboard/summary/").data
    assert D(str(dash["month_profit"])) == s["month_profit_kzt"]


def test_fx_difference_reported_separately(company):
    set_rate(company, "USD", 450, day=date(2026, 5, 1))
    set_rate(company, "USD", 470, day=date(2026, 5, 10))
    order = make_order(company, currency="USD")
    inv = issue_invoice(company, order=order, amount="1000", currency="USD", due=date(2026, 6, 1))
    pay_invoice(company, inv, 100, day=date(2026, 5, 10))
    with tenant_context(company.id):
        s = summary.finance_summary(TODAY)
    assert s["fx_difference_kzt"] == D("2000.00")
    assert s["client_debt_kzt"] == D("405000.00")  # 900 USD * 450 (курс счёта)


def test_api_permissions_isolation_and_shape(make_company, company, admin_client):
    issue_invoice(company, order=make_order(company, client=make_client(company, "Д")), amount="50")
    r = admin_client.get("/api/finance/debts/clients/")
    assert r.status_code == 200 and r.data["results"][0]["balance_kzt"] == "50.00"
    assert admin_client.get("/api/finance/debts/carriers/").status_code == 200
    s = admin_client.get("/api/finance/summary/")
    assert (
        s.status_code == 200
        and s.data["currency"] == "KZT"
        and s.data["client_debt_kzt"] == "50.00"
    )
    _, _, other = make_company("Other")
    assert other.get("/api/finance/debts/clients/").data["results"] == []
    from apps.forwarding.tests.test_parties import client_with_role

    _, mech = client_with_role(company, "Механик")
    assert mech.get("/api/finance/summary/").status_code == 403


def test_query_count_stable(company, admin_client, django_assert_max_num_queries):
    for i in range(8):
        issue_invoice(
            company, order=make_order(company, client=make_client(company, f"К{i}")), amount="10"
        )
    with django_assert_max_num_queries(12):
        assert admin_client.get("/api/finance/debts/clients/").status_code == 200
    with django_assert_max_num_queries(16):
        assert admin_client.get("/api/finance/summary/").status_code == 200
