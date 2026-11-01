"""Прибыль заказа и сводка дашборда (Task 13)."""

from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal

import pytest
import time_machine

from apps.core.api.auth import issue_tokens
from apps.core.models import Company, Membership
from apps.core.tenancy import tenant_context
from apps.forwarding.dashboard import dashboard_summary
from apps.forwarding.finance_lines.models import OrderService
from apps.forwarding.finance_lines.services import annotate_order_totals, order_totals
from apps.forwarding.models import Order
from apps.forwarding.orders.services import change_status
from apps.forwarding.tests.test_orders import (
    ORDERS,
    hv,
    make_client,
    make_order,
    new_order,
)
from apps.forwarding.tests.test_parties import client_with_role
from apps.forwarding.tests.test_trips import make_cargos, make_carrier, svc_create

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=dt_tz.utc)
LINES = "/api/order-lines/"
SUMMARY = "/api/dashboard/summary/"
D = Decimal


@pytest.fixture(autouse=True)
def frozen():
    with time_machine.travel(NOW, tick=False):
        yield


@pytest.fixture
def two(make_company):
    return make_company("Co A"), make_company("Co B")


def add_line(company, order, income=0, expense=0, on=None, title="Услуга", **extra):
    with tenant_context(company.id):
        kwargs = {"date": on} if on else {}
        return OrderService.objects.create(
            order=order, title=title, income=income, expense=expense, **kwargs, **extra
        )


def set_status(company, order, name):
    with tenant_context(company.id):
        user = Membership.objects.filter(company=company).first().user
        status = hv(company, "order_status", name)
        return change_status(Order.objects.get(pk=order.pk), status, user)


def summary(api):
    r = api.get(SUMMARY)
    assert r.status_code == 200, r.content
    return r.data


def order_row(api, pk):
    r = api.get(f"{ORDERS}{pk}/")
    assert r.status_code == 200, r.content
    return r.data


# --- прибыль заказа ---


def test_profit_and_margin_example(admin_client, company):
    d = new_order(admin_client, make_client(company), client_rate="1000000")
    r = admin_client.post(
        LINES, {"order": d["id"], "title": "Перевозка", "expense": "770000"}, format="json"
    )
    assert r.status_code == 201, r.content
    row = order_row(admin_client, d["id"])
    assert row["revenue"] == "1000000.00" and row["cost"] == "770000.00"
    assert row["profit"] == "230000.00" and row["margin_pct"] == "23.00"
    with tenant_context(company.id):
        totals = order_totals(Order.objects.get(pk=d["id"]))
    assert totals == {
        "revenue": D("1000000"),
        "cost": D("770000"),
        "profit": D("230000"),
        "margin_pct": D("23.00"),
    }
    assert all(isinstance(totals[k], Decimal) for k in totals)


def test_zero_revenue_margin_is_none(admin_client, company):
    d = new_order(admin_client, make_client(company))  # ставка 0
    assert (
        admin_client.post(
            LINES, {"order": d["id"], "title": "Расход", "expense": "100"}, format="json"
        ).status_code
        == 201
    )
    row = order_row(admin_client, d["id"])
    assert row["revenue"] == "0.00" and row["profit"] == "-100.00" and row["margin_pct"] is None
    with tenant_context(company.id):
        assert order_totals(Order.objects.get(pk=d["id"]))["margin_pct"] is None


def test_order_without_lines_has_zero_totals(admin_client, company):
    order = make_order(company)  # без грузов
    with tenant_context(company.id):
        OrderService.objects.filter(order=order).delete()
        totals = order_totals(order)
    assert totals == {"revenue": D(0), "cost": D(0), "profit": D(0), "margin_pct": None}
    row = order_row(admin_client, order.pk)
    assert row["revenue"] == "0.00" and row["cost"] == "0.00"
    assert row["profit"] == "0.00" and row["margin_pct"] is None
    assert row["consignments"] == []


def test_negative_margin_and_half_up_rounding(company):
    order = make_order(company, client_rate=800)
    add_line(company, order, expense=799)  # 1/800*100 = 0.125 -> 0.13 (не банковское 0.12)
    loss = make_order(company, client_rate=100)
    add_line(company, loss, expense=150)
    with tenant_context(company.id):
        assert order_totals(order)["margin_pct"] == D("0.13")
        assert order_totals(loss)["margin_pct"] == D("-50.00")


def test_list_and_detail_have_totals_without_n_plus_one(
    admin_client, company, django_assert_max_num_queries
):
    from apps.forwarding.tests.test_orders import LIST_QUERY_BOUND

    for i in range(6):
        order = make_order(company, client_rate=1000 + i)
        add_line(company, order, expense=500)
    with django_assert_max_num_queries(LIST_QUERY_BOUND):
        r = admin_client.get(ORDERS)
    assert r.status_code == 200 and len(r.data["results"]) == 6
    for o in r.data["results"]:
        assert o["revenue"] == f"{o['client_rate']}" and o["cost"] == "500.00"
        assert D(o["profit"]) == D(o["revenue"]) - 500
    with django_assert_max_num_queries(LIST_QUERY_BOUND):
        assert admin_client.get(f"{ORDERS}{r.data['results'][0]['id']}/").status_code == 200


def test_annotate_order_totals_does_not_multiply_rows(company):
    order = make_order(company, client_rate=100)
    add_line(company, order, income=50, expense=10)
    add_line(company, order, income=0, expense=5)
    with tenant_context(company.id):
        row = annotate_order_totals(Order.objects.filter(pk=order.pk)).get()
        assert (row.revenue, row.cost) == (D(150), D(15))
        assert Order.objects.filter(pk=order.pk).count() == 1


# --- дашборд: пустая компания и права ---


def test_empty_company_dashboard(admin_client):
    s = summary(admin_client)
    assert s["active_orders"] == 0 and s["completed_orders"] == 0
    assert s["clients"] == 0 and s["carriers"] == 0 and s["unassigned_orders"] == 0
    assert s["month"] == "2026-10"
    assert s["month_profit"] == "0.00" and s["month_margin_pct"] is None
    # все статусы справочника в порядке справочника, нули включены
    assert [x["status"] for x in s["orders_by_status"]] == [
        "Новый",
        "В работе",
        "На погрузке",
        "В пути",
        "На выгрузке",
        "Завершён",
        "Отменён",
    ]
    assert all(x["count"] == 0 and isinstance(x["status_id"], int) for x in s["orders_by_status"])


def test_counts_and_orders_by_status(admin_client, company):
    c = make_client(company)
    make_carrier(company)
    o1, o2, o3, o4 = (make_order(company, c) for _ in range(4))
    set_status(company, o2, "В работе")
    set_status(company, o3, "Завершён")
    set_status(company, o4, "Отменён")
    deleted = make_order(company, c)
    assert admin_client.delete(f"{ORDERS}{deleted.pk}/").status_code == 204
    s = summary(admin_client)
    by = {x["status"]: x["count"] for x in s["orders_by_status"]}
    assert by["Новый"] == 1 and by["В работе"] == 1 and by["Завершён"] == 1 and by["Отменён"] == 1
    assert by["В пути"] == 0
    assert sum(by.values()) == 4  # удалённый не считается
    assert s["active_orders"] == 2 and s["completed_orders"] == 1  # финальные не активны
    assert s["clients"] == 1 and s["carriers"] == 1
    assert o1.pk


def test_dispatcher_sees_null_finance_but_dashboard_works(company):
    _, api = client_with_role(company, "Диспетчер")
    order = make_order(company, client_rate=500)
    add_line(company, order, expense=100)
    s = summary(api)
    assert s["month_profit"] is None and s["month_margin_pct"] is None
    assert s["active_orders"] == 1 and s["unassigned_orders"] == 1


def test_manager_dashboard_has_finance(company):
    _, api = client_with_role(company, "Менеджер")
    make_order(company, client_rate=500)
    s = summary(api)
    assert s["month_profit"] == "500.00" and s["month_margin_pct"] == "100.00"


def test_dashboard_profit_counts_only_base_currency(company):
    _, api = client_with_role(company, "Менеджер")
    make_order(company, client_rate=500000)  # KZT
    usd = make_order(company, client_rate=1000, currency=hv(company, "currency", code="USD"))
    eur = make_order(company, client_rate=700, currency=hv(company, "currency", code="EUR"))
    add_line(company, usd, expense=100)
    add_line(company, eur, expense=50)
    s = summary(api)
    assert s["currency"] == "KZT"
    assert s["month_profit"] == "500000.00" and s["month_margin_pct"] == "100.00"
    assert s["excluded_orders"] == 2


def test_dashboard_cancelled_foreign_order_is_not_excluded_order(company):
    _, api = client_with_role(company, "Менеджер")
    make_order(company, client_rate=500)
    usd = make_order(company, client_rate=1000, currency=hv(company, "currency", code="USD"))
    set_status(company, usd, "Отменён")
    s = summary(api)
    assert s["excluded_orders"] == 0 and s["month_profit"] == "500.00"


def test_dashboard_single_currency_unchanged(company):
    _, api = client_with_role(company, "Менеджер")
    order = make_order(company, client_rate=1000)
    add_line(company, order, expense=250)
    s = summary(api)
    assert s["month_profit"] == "750.00" and s["month_margin_pct"] == "75.00"
    assert s["currency"] == "KZT" and s["excluded_orders"] == 0


def test_dashboard_without_finance_hides_currency_fields(company):
    _, api = client_with_role(company, "Диспетчер")
    make_order(company, client_rate=500)
    s = summary(api)
    assert s["currency"] is None and s["excluded_orders"] is None


def test_driver_has_no_dashboard(company):
    _, api = client_with_role(company, "Водитель")
    assert api.get(SUMMARY).status_code == 403


def test_dashboard_requires_auth(api_client):
    assert api_client.get(SUMMARY).status_code in (401, 403)


# --- unassigned ---


def test_unassigned_counts_only_open_orders_without_carrier_trip(admin_client, company):
    o1, ids1 = make_cargos(company)
    o2, ids2 = make_cargos(company)
    o3, ids3 = make_cargos(company)
    o4, _ = make_cargos(company)
    carrier = make_carrier(company)
    svc_create(company, ids2, carrier)
    svc_create(company, ids3, None)  # рейс без перевозчика не считается
    set_status(company, o4, "Завершён")  # финальный не считается
    assert summary(admin_client)["unassigned_orders"] == 2  # o1 и o3
    svc_create(company, ids1, carrier)
    assert summary(admin_client)["unassigned_orders"] == 1
    assert o1.pk and o2.pk and o3.pk


# --- завершённые и начало учёта ---


def test_completed_counts_from_accounting_start(admin_client, company):
    order = make_order(company)
    with time_machine.travel(datetime(2026, 10, 14, 12, 0, tzinfo=dt_tz.utc), tick=False):
        set_status(company, order, "Завершён")
    assert summary(admin_client)["completed_orders"] == 1  # начало учёта не задано
    Company.objects.filter(pk=company.pk).update(accounting_start=date(2026, 10, 15))
    assert summary(admin_client)["completed_orders"] == 0
    Company.objects.filter(pk=company.pk).update(accounting_start=date(2026, 10, 14))
    assert summary(admin_client)["completed_orders"] == 1
    other = make_order(company)
    set_status(company, other, "Завершён")  # сегодня
    Company.objects.filter(pk=company.pk).update(accounting_start=date(2026, 10, 15))
    assert summary(admin_client)["completed_orders"] == 1


# --- прибыль месяца ---


def test_month_boundary_uses_company_timezone(admin_client, company, admin_user):
    # 20:00 UTC 31 октября = 01:00 1 ноября в Asia/Almaty (UTC+5)
    with time_machine.travel(datetime(2026, 10, 31, 20, 0, tzinfo=dt_tz.utc), tick=False):
        token = issue_tokens(admin_user, company.id)["access"]  # прежний токен просрочен
        admin_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        order = make_order(company, client_rate=0)
        add_line(company, order, income=500, expense=100, on=date(2026, 11, 1))
        add_line(company, order, income=900, expense=0, on=date(2026, 10, 31))
        s = summary(admin_client)
        assert s["month"] == "2026-11"
        assert s["month_profit"] == "400.00" and s["month_margin_pct"] == "80.00"
        Company.objects.filter(pk=company.pk).update(timezone="UTC")
        s = summary(admin_client)
        assert s["month"] == "2026-10"
        assert s["month_profit"] == "900.00" and s["month_margin_pct"] == "100.00"


def test_month_profit_excludes_cancelled_deleted_and_before_accounting_start(admin_client, company):
    ok = make_order(company, client_rate=0)
    add_line(company, ok, income=1000, expense=600, on=date(2026, 10, 3))
    cancelled = make_order(company, client_rate=0)
    add_line(company, cancelled, income=5000, expense=0, on=date(2026, 10, 3))
    set_status(company, cancelled, "Отменён")
    gone = make_order(company, client_rate=0)
    add_line(company, gone, income=7000, expense=0, on=date(2026, 10, 3))
    assert admin_client.delete(f"{ORDERS}{gone.pk}/").status_code == 204
    old = make_order(company, client_rate=0)
    add_line(company, old, income=9000, expense=0, on=date(2026, 9, 30))  # другой месяц
    s = summary(admin_client)
    assert s["month_profit"] == "400.00" and s["month_margin_pct"] == "40.00"
    # отменённый заказ показывает свои итоги, но в дашборд не входит
    assert order_row(admin_client, cancelled.pk)["profit"] == "5000.00"
    Company.objects.filter(pk=company.pk).update(accounting_start=date(2026, 10, 10))
    s = summary(admin_client)
    assert s["month_profit"] == "0.00" and s["month_margin_pct"] is None


def test_month_zero_revenue_margin_none_no_error(admin_client, company):
    order = make_order(company, client_rate=0)
    add_line(company, order, income=0, expense=300)
    s = summary(admin_client)
    assert s["month_profit"] == "-300.00" and s["month_margin_pct"] is None


# --- изоляция ---


def test_dashboard_isolation(two):
    (a, _, api_a), (b, _, api_b) = two
    c = make_client(a)
    order = make_order(a, c, client_rate=1000)
    add_line(a, order, expense=200)
    make_carrier(a)
    s = summary(api_b)
    assert s["active_orders"] == 0 and s["clients"] == 0 and s["carriers"] == 0
    assert s["unassigned_orders"] == 0 and s["month_profit"] == "0.00"
    assert all(x["count"] == 0 for x in s["orders_by_status"])
    sa = summary(api_a)
    assert sa["active_orders"] == 1 and sa["month_profit"] == "800.00"
    assert {x["status_id"] for x in sa["orders_by_status"]}.isdisjoint(
        {x["status_id"] for x in s["orders_by_status"]}
    )


def test_dashboard_summary_function_scopes_by_company(two):
    (a, _, _), (b, _, _) = two
    make_order(a, client_rate=100)
    with tenant_context(b.id):
        out = dashboard_summary(Company.objects.get(pk=b.pk), with_finance=True)
    assert out["active_orders"] == 0 and out["month_profit"] == D(0)


# --- запросы ---

DASHBOARD_QUERY_BOUND = 13  # измерено: 13 на любой размер данных (auth+подписка+9 запросов сводки)


def test_dashboard_query_count_is_flat(admin_client, company, django_assert_max_num_queries):
    for _ in range(12):
        order = make_order(company, client_rate=100)
        add_line(company, order, expense=10)
    make_carrier(company)
    with django_assert_max_num_queries(DASHBOARD_QUERY_BOUND):
        r = admin_client.get(SUMMARY)
    assert r.status_code == 200 and r.data["active_orders"] == 12


# --- RLS ---


def test_profit_and_dashboard_work_under_app_role(db, api_client):
    from apps.core.models import User
    from apps.core.services import create_company_with_defaults
    from apps.core.tests.test_rls import app_role
    from conftest import TEST_PASSWORD

    with app_role():
        admin = User.objects.create_user(email="rls-fin@x.kz", password=TEST_PASSWORD)
        create_company_with_defaults("RLS Fin", admin, ["forwarding"])
        other = User.objects.create_user(email="rls-fin2@x.kz", password=TEST_PASSWORD)
        create_company_with_defaults("RLS Fin 2", other, ["forwarding"])
        resp = api_client.post(
            "/api/auth/login/", {"login": "rls-fin@x.kz", "password": TEST_PASSWORD}
        )
        assert resp.status_code == 200, resp.content
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
        cl = api_client.post("/api/clients/", {"name": "ТОО Тест"}, format="json")
        assert cl.status_code == 201
        o = api_client.post(
            ORDERS, {"client": cl.data["id"], "client_rate": "1000000"}, format="json"
        )
        assert o.status_code == 201, o.content
        assert o.data["revenue"] == "1000000.00"  # базовая строка создана
        line = api_client.post(
            LINES, {"order": o.data["id"], "title": "Фрахт", "expense": "770000"}, format="json"
        )
        assert line.status_code == 201, line.content
        row = api_client.get(f"{ORDERS}{o.data['id']}/").data
        assert row["profit"] == "230000.00" and row["margin_pct"] == "23.00"
        s = api_client.get(SUMMARY).data
        assert s["active_orders"] == 1 and s["month_profit"] == "230000.00"
        assert s["month_margin_pct"] == "23.00" and s["unassigned_orders"] == 1
        # другая компания ничего не видит
        other_login = api_client.post(
            "/api/auth/login/", {"login": "rls-fin2@x.kz", "password": TEST_PASSWORD}
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {other_login.data['access']}")
        s2 = api_client.get(SUMMARY).data
        assert s2["active_orders"] == 0 and s2["month_profit"] == "0.00"
        assert api_client.get(LINES).data["count"] == 0
