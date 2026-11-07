# ruff: noqa: E501
"""Базовая валюта в отчётах новой модели (1.4.13): итоги компании считаются в settings.base_currency
по сохранённым снимкам, без пересчёта истории; прежняя база и «без курса» выводятся отдельно."""

import io
from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal as D

import pytest
import time_machine
from openpyxl import load_workbook

from apps.core.api.auth import issue_tokens
from apps.core.handbooks.models import HandbookValue
from apps.core.tenancy import tenant_context
from apps.finance import expenses as ex
from apps.finance import reports_new
from apps.finance.fx import apply_snapshot, change_base_currency, legacy_missing_snapshot
from apps.finance.models import Income
from apps.finance.tests.helpers import cur, first_user, make_order
from apps.finance.tests.p2_helpers import enable_new, rate, set_engine

pytestmark = pytest.mark.django_db
JUNE_FIRST, JULY_FIRST = date(2026, 6, 1), date(2026, 7, 1)
DAY = date(2026, 6, 10)


@pytest.fixture(autouse=True)
def frozen():
    with time_machine.travel(datetime(2026, 6, 20, 12, 0, tzinfo=dt_tz.utc), tick=False):
        yield


def login(client, user, company):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")


def mk_income(company, order, amount, *, day=DAY, status="recognized", snapshot="apply", **extra):
    """Доход заказа; snapshot: apply (по курсу на день) / missing (legacy_missing) / none."""
    with tenant_context(company.id):
        inc = Income(
            company=company, order=order, kind="service", title=extra.pop("title", "Услуга"),
            amount=D(str(amount)), currency=order.currency, status=status,
            recognized_on=day if status == "recognized" else None,
            recognition_basis="service_confirmed" if status == "recognized" else "",
            **extra,
        )  # fmt: skip
        if snapshot == "apply":
            apply_snapshot(inc, day)
        elif snapshot == "missing":
            for key, value in legacy_missing_snapshot(company, order.currency).items():
                setattr(inc, key, value)
        inc.save()
        return inc


def mk_expense(company, order, amount, *, day=DAY, title="Расход"):
    with tenant_context(company.id):
        cat = HandbookValue.objects.get(handbook__code="expense_category", code="OTHER")
        return ex.create_expense(
            company, title=title, category=cat, amount=D(str(amount)), currency=order.currency,
            expense_date=day, user=first_user(company), perms=("finance.backdate",),
            allocations=[{"order": order, "amount": D(str(amount))}],
        )  # fmt: skip


def month(company):
    with tenant_context(company.id):
        return reports_new.month_totals_new(company, JUNE_FIRST, JULY_FIRST)


def switch_base(company, code):
    change_base_currency(company, cur(company, code), first_user(company), f"Переход на {code}")


def world(company):
    """KZT-заказ и USD-заказ, курс USD = 480; engine=new."""
    rate(company, "USD", "480", date(2026, 1, 1))
    enable_new(company)
    kzt, usd = make_order(company), make_order(company, currency="USD")
    return kzt, usd


# --- база KZT: регрессия ---------------------------------------------------------------------


def test_kzt_base_regression_and_foreign_orders_by_snapshot(company):
    kzt, usd = world(company)
    mk_income(company, kzt, 1000)
    mk_expense(company, kzt, 300)
    got = month(company)
    assert (got["revenue"], got["cost"], got["month_profit"]) == (D("1000"), D("300"), D("700"))
    assert got["month_margin_pct"] == D("70.00") and got["currency"] == "KZT"
    assert got["excluded"]["count"] == 0 and got["excluded_orders"] == 0
    mk_income(company, usd, 10)  # 10 USD по курсу 480 на дату записи
    mk_expense(company, usd, 4)
    got = month(company)
    assert got["revenue"] == D("5800.00") and got["cost"] == D("2220.00")
    assert got["excluded"]["count"] == 0
    # прибыль ЗАКАЗА - в валюте заказа и от базы не зависит
    with tenant_context(company.id):
        assert reports_new.order_totals_new(usd)["revenue"] == D("10.00")
        assert reports_new.order_totals_new(usd)["profit"] == D("6.00")


# --- смена базы на USD ---------------------------------------------------------------------


def test_base_switch_to_usd_old_snapshots_are_separate_and_margin_is_current_only(company):
    kzt, usd = world(company)
    mk_income(company, kzt, 1000)  # снимок в KZT
    mk_expense(company, kzt, 300)
    mk_income(company, usd, 5, snapshot="missing", title="Без курса")  # legacy_missing
    mk_expense(company, usd, 1)
    switch_base(company, "USD")
    mk_income(company, usd, 100)  # снимок в USD (same)
    mk_expense(company, usd, 40)
    mk_income(company, kzt, 480)  # KZT -> USD через тенге: 480 / 480 = 1.00
    got = month(company)
    assert got["currency"] == "USD"
    assert got["revenue"] == D("101.00") and got["cost"] == D("40.00")  # только текущая база
    assert got["month_profit"] == D("61.00")
    assert got["month_margin_pct"] == D("60.40")  # 61 / 101, считается лишь по текущей базе
    ex_ = got["excluded"]
    assert (
        ex_["prior_base"]["count"] == 3
    )  # доход 1000 и доля 300 (KZT-снимок), доля 1 USD (KZT-снимок)
    assert ex_["prior_base"]["by_currency"] == {
        "KZT": {"income": D("1000.00"), "expense": D("300.00")},
        "USD": {"income": D("0"), "expense": D("1.00")},
    }
    assert ex_["no_rate"]["count"] == 1  # legacy_missing: доход 5 USD
    assert ex_["no_rate"]["by_currency"] == {"USD": {"income": D("5.00"), "expense": D("0")}}
    assert ex_["count"] == 4 and ex_["orders"] == 2 and got["excluded_orders"] == 2


def test_history_is_not_recalculated_after_base_switch(company):
    kzt, _ = world(company)
    inc = mk_income(company, kzt, 1000)
    switch_base(company, "USD")
    inc.refresh_from_db()
    assert inc.fx_base_currency.code == "KZT" and inc.base_amount == D("1000.00")
    got = month(company)
    assert got["revenue"] == D("0") and got["excluded"]["prior_base"]["count"] == 1


def test_base_back_to_kzt_includes_old_kzt_snapshots_only(company):
    kzt, usd = world(company)
    mk_income(company, kzt, 1000)
    switch_base(company, "USD")
    mk_income(company, usd, 100)
    switch_base(company, "KZT")
    got = month(company)
    assert got["currency"] == "KZT" and got["revenue"] == D("1000.00")
    assert got["excluded"]["prior_base"]["by_currency"] == {
        "USD": {"income": D("100.00"), "expense": D("0")}
    }


def test_planned_income_without_snapshot_needs_base_currency_match(company):
    kzt, usd = world(company)
    mk_income(company, kzt, 70, status="planned", snapshot="none")
    mk_income(company, usd, 3, status="planned", snapshot="none")
    with tenant_context(company.id):
        split = reports_new.base_split(
            Income.objects.all(), reports_new.ExpenseAllocation.objects.none(), "KZT"
        )
    assert split["revenue"] == D("70.00")  # KZT без снимка - сумма как есть
    assert split["excluded"]["no_rate"]["by_currency"] == {
        "USD": {"income": D("3.00"), "expense": D("0")}
    }


# --- журнал, плитки, дашборд, Excel (API) -------------------------------------------------


def test_api_reports_use_base_currency_and_report_excluded(company, admin_client, admin_user):
    kzt, usd = world(company)
    mk_income(company, kzt, 1000)
    mk_expense(company, kzt, 300)
    switch_base(company, "USD")
    mk_income(company, usd, 100)
    mk_expense(company, usd, 40)
    login(admin_client, admin_user, company)

    dash = admin_client.get("/api/dashboard/summary/").json()
    assert (
        dash["currency"] == "USD"
        and dash["month_profit"] == "60.00"
        and dash["month_margin_pct"] == "60.00"
    )
    assert dash["excluded_orders"] == 1
    assert dash["excluded"]["prior_base"]["by_currency"] == {
        "KZT": {"income": "1000.00", "expense": "300.00"}
    }
    assert dash["excluded"]["count"] == 2

    ops = admin_client.get("/api/finance/operations/?page_size=100").json()
    summ = ops["summary"]
    assert summ["currency"] == "USD" and (
        summ["income_kzt"],
        summ["expense_kzt"],
        summ["diff_kzt"],
    ) == ("100.00", "40.00", "60.00")
    assert summ["excluded"]["prior_base"]["count"] == 2 and summ["unconverted"] == 0
    assert summ["by_currency"]["KZT"] == {
        "income": "1000.00",
        "expense": "300.00",
        "diff": "700.00",
    }
    assert sorted(r["base_status"] for r in ops["results"]) == [
        "current",
        "current",
        "prior_base",
        "prior_base",
    ]

    fin = admin_client.get("/api/finance/summary/").json()
    assert (
        fin["currency"] == "USD"
        and fin["debts_currency"] == "KZT"
        and fin["month_profit_kzt"] == "60.00"
    )
    assert fin["excluded"]["count"] == 2

    xlsx = admin_client.get("/api/finance/operations/export/")
    rows = list(load_workbook(io.BytesIO(xlsx.content)).active.iter_rows(values_only=True))
    assert rows[0][-3:] == ("Доход, USD", "Расход, USD", "Учёт в базовой валюте")
    marks = sorted((r[-1] or "") for r in rows[1:])
    assert (
        marks == ["", "", "в прежней базовой валюте", "в прежней базовой валюте"]
        or marks.count("в прежней базовой валюте") == 2
    )
    current = [r for r in rows[1:] if r[-1] in ("", None)]
    assert sorted((r[-3] or 0) + (r[-2] or 0) for r in current) == [40.0, 100.0]


def test_kzt_base_api_keeps_shape_without_excluded(company, admin_client, admin_user):
    kzt, _ = world(company)
    mk_income(company, kzt, 1000)
    login(admin_client, admin_user, company)
    dash = admin_client.get("/api/dashboard/summary/").json()
    assert (
        dash["currency"] == "KZT" and dash["month_profit"] == "1000.00" and dash["excluded"] is None
    )
    summ = admin_client.get("/api/finance/operations/").json()["summary"]
    assert (
        summ["currency"] == "KZT" and summ["excluded"] is None and summ["income_kzt"] == "1000.00"
    )


def test_legacy_and_shadow_stay_in_kzt_even_if_base_changed(company, admin_client, admin_user):
    kzt, usd = world(company)
    set_engine(company, "legacy")
    switch_base(company, "USD")
    login(admin_client, admin_user, company)
    for engine in ("legacy", "shadow"):
        set_engine(company, engine)
        dash = admin_client.get("/api/dashboard/summary/").json()
        assert dash["currency"] == "KZT" and dash["excluded"] is None
        assert admin_client.get("/api/finance/operations/").json()["summary"]["currency"] == "KZT"
        assert admin_client.get("/api/finance/summary/").json()["currency"] == "KZT"


# --- изоляция компаний --------------------------------------------------------------------


def test_companies_do_not_mix_bases(company, make_company):
    other, _, _ = make_company("Other")
    kzt, usd = world(company)
    mk_income(company, kzt, 1000)
    rate(other, "USD", "480", date(2026, 1, 1))
    enable_new(other)
    ousd = make_order(other, currency="USD")
    switch_base(other, "USD")
    mk_income(other, ousd, 7)
    assert month(company)["revenue"] == D("1000.00") and month(company)["currency"] == "KZT"
    got = month(other)
    assert (
        got["currency"] == "USD" and got["revenue"] == D("7.00") and got["excluded"]["count"] == 0
    )


def test_partial_flag_and_margin_none_without_suitable_records(company, admin_client, admin_user):
    kzt, usd = world(company)
    mk_income(company, kzt, 1000)
    mk_expense(company, kzt, 300)
    switch_base(company, "USD")  # в текущей базе записей нет: всё в прежней базе
    got = month(company)
    assert got["revenue"] == D("0") and got["cost"] == D("0") and got["month_profit"] == D("0")
    assert got["month_margin_pct"] is None  # не 0: нечего делить
    login(admin_client, admin_user, company)
    dash = admin_client.get("/api/dashboard/summary/").json()
    assert dash["is_partial"] is True and dash["excluded"]["is_partial"] is True
    assert dash["month_margin_pct"] is None and dash["month_profit"] == "0.00"
    # исключённое не попадает ни в числитель, ни в знаменатель после появления текущих записей
    mk_income(company, usd, 100)
    dash = admin_client.get("/api/dashboard/summary/").json()
    assert dash["month_profit"] == "100.00" and dash["month_margin_pct"] == "100.00"
    assert admin_client.get("/api/finance/summary/").json()["is_partial"] is True
    assert admin_client.get("/api/finance/operations/").json()["summary"]["is_partial"] is True


def test_not_partial_when_everything_is_in_base(company, admin_client, admin_user):
    kzt, _ = world(company)
    mk_income(company, kzt, 10)
    login(admin_client, admin_user, company)
    assert admin_client.get("/api/dashboard/summary/").json()["is_partial"] is False
    assert admin_client.get("/api/finance/summary/").json()["is_partial"] is False
