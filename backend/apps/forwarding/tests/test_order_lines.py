"""Строки заказа: API /api/order-lines/, базовая строка, ограничения БД (Task 13)."""

from datetime import date, datetime, timedelta
from datetime import timezone as dt_tz

import pytest
import time_machine
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.billing.models import Subscription
from apps.core.api.auth import issue_tokens
from apps.core.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.forwarding.finance_lines.models import OrderService
from apps.forwarding.tests.test_orders import (
    ORDERS,
    make_client,
    make_order,
    new_order,
)
from apps.forwarding.tests.test_parties import client_with_role

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=dt_tz.utc)
LINES = "/api/order-lines/"


@pytest.fixture(autouse=True)
def frozen():
    with time_machine.travel(NOW, tick=False):
        yield


@pytest.fixture
def two(make_company):
    return make_company("Co A"), make_company("Co B")


def reauth(api, user, company):
    """Свежий токен: после прыжка времени вперёд прежний access уже просрочен."""
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")


def url(pk):
    return f"{LINES}{pk}/"


def post_line(api, order_id, **extra):
    payload = {"order": order_id, "title": "Перевозка", "income": "100", **extra}
    return api.post(LINES, payload, format="json")


def lines_of(company, order_id):
    with tenant_context(company.id):
        return list(OrderService.objects.filter(order_id=order_id).order_by("id"))


def base_line(company, order_id):
    (line,) = [x for x in lines_of(company, order_id) if x.is_base]
    return line


# --- базовая строка ---


def test_create_order_makes_single_base_line(admin_client, company):
    d = new_order(admin_client, make_client(company), client_rate="250000.50")
    lines = lines_of(company, d["id"])
    assert len(lines) == 1 and lines[0].is_base
    assert lines[0].title == "Начальная ставка"
    assert str(lines[0].income) == "250000.50" and lines[0].expense == 0
    assert lines[0].date == date(2026, 10, 15)


def test_base_line_date_is_order_creation_date_in_company_timezone(company):
    # 20:00 UTC 31 октября = 1 ноября в Asia/Almaty
    with time_machine.travel(datetime(2026, 10, 31, 20, 0, tzinfo=dt_tz.utc), tick=False):
        order = make_order(company, client_rate=10)
    assert base_line(company, order.pk).date == date(2026, 11, 1)


def test_rate_change_updates_base_line_and_keeps_date(admin_client, company):
    d = new_order(admin_client, make_client(company), client_rate="100")
    with tenant_context(company.id):
        OrderService.objects.filter(order_id=d["id"]).update(date=date(2026, 10, 1))
    r = admin_client.patch(f"{ORDERS}{d['id']}/", {"client_rate": "300"}, format="json")
    assert r.status_code == 200, r.content
    assert r.data["revenue"] == "300.00"  # итоги в ответе PATCH уже новые
    lines = lines_of(company, d["id"])
    assert len(lines) == 1 and str(lines[0].income) == "300.00"
    assert lines[0].date == date(2026, 10, 1)  # дата сохраняется
    # правка без ставки базовую строку не трогает
    r = admin_client.patch(f"{ORDERS}{d['id']}/", {"comment": "x"}, format="json")
    assert r.status_code == 200 and r.data["revenue"] == "300.00"


def test_rate_change_keeps_other_lines(admin_client, company):
    d = new_order(admin_client, make_client(company), client_rate="100")
    post_line(admin_client, d["id"], income="50", expense="20")
    r = admin_client.patch(f"{ORDERS}{d['id']}/", {"client_rate": "200"}, format="json")
    assert r.data["revenue"] == "250.00" and r.data["cost"] == "20.00"
    assert len(lines_of(company, d["id"])) == 2


def test_base_line_is_read_only(admin_client, company):
    d = new_order(admin_client, make_client(company), client_rate="100")
    base = base_line(company, d["id"])
    r = admin_client.patch(url(base.pk), {"income": "1"}, format="json")
    assert r.status_code == 400 and "ставк" in str(r.data).lower()
    r = admin_client.delete(url(base.pk))
    assert r.status_code == 400 and "ставк" in str(r.data).lower()
    assert str(base_line(company, d["id"]).income) == "100.00"


def test_base_line_cannot_be_forged_through_api(admin_client, company):
    d = new_order(admin_client, make_client(company))
    r = post_line(admin_client, d["id"], is_base=True)
    assert r.status_code == 201 and r.data["is_base"] is False


# --- CRUD ---


def test_crud_roundtrip_and_hard_delete(admin_client, company):
    d = new_order(admin_client, make_client(company))
    r = post_line(admin_client, d["id"], category="Фрахт", expense="70.5", date="2026-10-01")
    assert r.status_code == 201, r.content
    assert r.data["income"] == "100.00" and r.data["expense"] == "70.50"
    assert r.data["date"] == "2026-10-01" and r.data["category"] == "Фрахт"
    assert r.data["is_base"] is False and r.data["order"] == d["id"]
    pk = r.data["id"]
    assert admin_client.get(url(pk)).data["title"] == "Перевозка"
    r = admin_client.patch(url(pk), {"expense": "10"}, format="json")
    assert r.status_code == 200 and r.data["expense"] == "10.00"
    r = admin_client.put(
        url(pk), {"order": d["id"], "title": "Новое", "income": "1", "expense": "2"}, format="json"
    )
    assert r.status_code == 200 and r.data["title"] == "Новое"
    assert admin_client.delete(url(pk)).status_code == 204
    assert admin_client.get(url(pk)).status_code == 404
    with tenant_context(company.id):
        assert not OrderService.objects.filter(pk=pk).exists()  # жёсткое удаление


def test_date_defaults_to_today_in_company_timezone(admin_client, company, admin_user):
    d = new_order(admin_client, make_client(company))
    with time_machine.travel(datetime(2026, 10, 31, 20, 0, tzinfo=dt_tz.utc), tick=False):
        reauth(admin_client, admin_user, company)
        r = post_line(admin_client, d["id"])
    assert r.status_code == 201 and r.data["date"] == "2026-11-01"


def test_validation(admin_client, company):
    d = new_order(admin_client, make_client(company))
    assert post_line(admin_client, d["id"], income="-1").status_code == 400
    assert post_line(admin_client, d["id"], expense="-0.01").status_code == 400
    assert post_line(admin_client, d["id"], date="2026-13-45").status_code == 400
    assert post_line(admin_client, d["id"], date="не дата").status_code == 400
    assert post_line(admin_client, d["id"], title="  ").status_code == 400
    assert post_line(admin_client, d["id"], title="x" * 256).status_code == 400
    assert post_line(admin_client, d["id"], income="1" * 13).status_code == 400  # > 14 знаков
    assert admin_client.post(LINES, {"title": "x"}, format="json").status_code == 400
    assert post_line(admin_client, d["id"], income=1.5).data["income"] == "1.50"


def test_order_must_be_live_order_of_company(two):
    (a, _, api_a), (b, _, api_b) = two
    foreign = make_order(b)
    assert post_line(api_a, foreign.pk).status_code == 400
    mine = new_order(api_a, make_client(a))
    assert api_a.delete(f"{ORDERS}{mine['id']}/").status_code == 204
    assert post_line(api_a, mine["id"]).status_code == 400  # удалённый заказ


def test_order_cannot_be_moved_by_patch(admin_client, company):
    c = make_client(company)
    d1, d2 = new_order(admin_client, c), new_order(admin_client, c)
    pk = post_line(admin_client, d1["id"]).data["id"]
    r = admin_client.patch(url(pk), {"order": d2["id"]}, format="json")
    assert r.status_code == 400
    assert admin_client.patch(url(pk), {"order": d1["id"]}, format="json").status_code == 200


def test_list_filter_by_order(admin_client, company):
    c = make_client(company)
    d1, d2 = new_order(admin_client, c), new_order(admin_client, c)
    post_line(admin_client, d1["id"], title="a")
    post_line(admin_client, d2["id"], title="b")
    r = admin_client.get(LINES, {"order": d1["id"]})
    assert r.status_code == 200 and {x["title"] for x in r.data["results"]} == {
        "Начальная ставка",
        "a",
    }
    assert admin_client.get(LINES).data["count"] == 4
    assert admin_client.get(LINES, {"order": "abc"}).status_code == 400


def test_lines_of_soft_deleted_order_stay_but_are_hidden(admin_client, company):
    d = new_order(admin_client, make_client(company), client_rate="10")
    pk = post_line(admin_client, d["id"]).data["id"]
    assert admin_client.delete(f"{ORDERS}{d['id']}/").status_code == 204
    assert len(lines_of(company, d["id"])) == 2  # строки остались
    assert admin_client.get(url(pk)).status_code == 404
    assert admin_client.get(LINES, {"order": d["id"]}).data["count"] == 0


def test_totals_follow_line_changes(admin_client, company):
    d = new_order(admin_client, make_client(company), client_rate="1000")
    pk = post_line(admin_client, d["id"], income="0", expense="400").data["id"]
    row = admin_client.get(f"{ORDERS}{d['id']}/").data
    assert row["profit"] == "600.00" and row["margin_pct"] == "60.00"
    admin_client.patch(url(pk), {"expense": "500"}, format="json")
    assert admin_client.get(f"{ORDERS}{d['id']}/").data["margin_pct"] == "50.00"
    admin_client.delete(url(pk))
    assert admin_client.get(f"{ORDERS}{d['id']}/").data["margin_pct"] == "100.00"
    listed = admin_client.get(ORDERS).data["results"][0]
    assert listed["revenue"] == "1000.00" and listed["profit"] == "1000.00"


def test_money_is_never_float(admin_client, company):
    d = new_order(admin_client, make_client(company), client_rate="1000.10")
    row = admin_client.get(f"{ORDERS}{d['id']}/").data
    for key in ("revenue", "cost", "profit", "margin_pct"):
        assert isinstance(row[key], str)
    line = post_line(admin_client, d["id"]).data
    assert isinstance(line["income"], str) and isinstance(line["expense"], str)


# --- права и подписка ---


def test_accountant_can_create_dispatcher_cannot(company):
    _, accountant = client_with_role(company, "Бухгалтер")
    _, dispatcher = client_with_role(company, "Диспетчер")
    order = make_order(company)
    assert post_line(accountant, order.pk).status_code == 201
    assert post_line(dispatcher, order.pk).status_code == 403
    assert dispatcher.get(LINES).status_code == 403
    assert accountant.get(LINES).status_code == 200


def test_view_only_role_cannot_write(company):
    _, manager = client_with_role(company, "Менеджер")  # finance.view
    order = make_order(company)
    pk = post_line(manager, order.pk)
    assert pk.status_code == 403
    assert manager.get(LINES).status_code == 200


def test_readonly_subscription_blocks_line_writes(company, admin_client):
    d = new_order(admin_client, make_client(company))
    pk = post_line(admin_client, d["id"]).data["id"]
    Subscription.objects.filter(company=company).update(ends_at=timezone.now() - timedelta(days=20))
    assert admin_client.get(LINES).status_code == 200
    r = post_line(admin_client, d["id"])
    assert r.status_code == 403 and r.data["code"] == "subscription_readonly"
    assert admin_client.patch(url(pk), {"title": "y"}, format="json").status_code == 403
    assert admin_client.delete(url(pk)).status_code == 403


# --- изоляция ---


def test_isolation_list_detail_patch_delete(two):
    (a, _, api_a), (b, _, api_b) = two
    d = new_order(api_a, make_client(a), client_rate="10")
    pk = post_line(api_a, d["id"]).data["id"]
    assert api_b.get(LINES).data["count"] == 0
    assert api_b.get(LINES, {"order": d["id"]}).data["count"] == 0  # чужой заказ: пусто
    assert api_b.get(url(pk)).status_code == 404
    assert api_b.patch(url(pk), {"title": "взлом"}, format="json").status_code == 404
    assert api_b.delete(url(pk)).status_code == 404
    assert api_a.get(url(pk)).data["title"] == "Перевозка"
    assert len(lines_of(a, d["id"])) == 2
    # итоги заказа компании B не содержат строк A
    mine_b = new_order(api_b, make_client(b), client_rate="5")
    assert mine_b["revenue"] == "5.00"


# --- аудит ---


def test_line_changes_are_audited(admin_client, company):
    d = new_order(admin_client, make_client(company))
    pk = post_line(admin_client, d["id"]).data["id"]
    admin_client.patch(url(pk), {"expense": "5"}, format="json")
    admin_client.delete(url(pk))
    with tenant_context(company.id):
        rows = list(
            AuditLog.objects.filter(object_type="forwarding.orderservice", object_id=str(pk))
            .order_by("id")
            .values_list("action", flat=True)
        )
    assert rows == ["create", "update", "delete"]


# --- ограничения БД ---


def test_db_constraints(company):
    order = make_order(company, client_rate=1)
    with tenant_context(company.id):
        for field in ("income", "expense"):
            with pytest.raises(IntegrityError), transaction.atomic():
                OrderService.objects.create(order=order, title="x", **{field: -1})
        with pytest.raises(IntegrityError), transaction.atomic():  # вторая базовая
            OrderService.objects.create(order=order, title="y", is_base=True)
        other = make_order(company)
        assert OrderService.objects.filter(order=other, is_base=True).count() == 1


# --- финансовые поля заказа скрыты без finance.view (fix round 1, 16a) ---

FINANCE_KEYS = ("revenue", "cost", "profit", "margin_pct")


def test_dispatcher_gets_null_finance_on_list_detail_create_and_patch(admin_client, company):
    order = new_order(admin_client, make_client(company), client_rate="500")
    _, dispatcher = client_with_role(
        company, "Диспетчер"
    )  # orders.view/update/create, без finance.view
    listed = next(x for x in dispatcher.get(ORDERS).data["results"] if x["id"] == order["id"])
    detail = dispatcher.get(f"{ORDERS}{order['id']}/").data
    patched = dispatcher.patch(f"{ORDERS}{order['id']}/", {"comment": "x"}, format="json")
    created = dispatcher.post(
        ORDERS, {"client": make_client(company, "Другой").pk, "client_rate": "10"}, format="json"
    )
    assert patched.status_code == 200 and created.status_code == 201
    for data in (listed, detail, patched.data, created.data):
        for key in FINANCE_KEYS:
            assert key in data and data[key] is None, (key, data)


@pytest.mark.parametrize("role", ["Бухгалтер", "Менеджер"])
def test_finance_roles_get_numbers(admin_client, company, role):
    order = new_order(admin_client, make_client(company), client_rate="500")
    _, api = client_with_role(company, role)
    assert api.get(f"{ORDERS}{order['id']}/").data["revenue"] == "500.00"
    row = next(x for x in api.get(ORDERS).data["results"] if x["id"] == order["id"])
    assert row["profit"] == "500.00" and row["margin_pct"] == "100.00"


def test_admin_gets_numbers(admin_client, company):
    order = new_order(admin_client, make_client(company), client_rate="500")
    assert admin_client.get(f"{ORDERS}{order['id']}/").data["revenue"] == "500.00"


def test_finance_hidden_does_not_cross_companies(two):
    (a, _, admin_a), (b, _, _) = two
    _, dispatcher_b = client_with_role(b, "Диспетчер")
    order_a = new_order(admin_a, make_client(a), client_rate="700")
    mine_b = new_order(dispatcher_b, make_client(b), client_rate="9")
    assert mine_b["revenue"] is None
    assert dispatcher_b.get(f"{ORDERS}{order_a['id']}/").status_code == 404
    assert admin_a.get(f"{ORDERS}{order_a['id']}/").data["revenue"] == "700.00"


@pytest.mark.parametrize("role", ["Диспетчер", "Бухгалтер"])
def test_list_query_bound_holds_with_and_without_finance(
    admin_client, company, role, django_assert_max_num_queries
):
    for i in range(5):
        new_order(admin_client, make_client(company, f"К{i}"), client_rate="5")
    _, api = client_with_role(company, role)
    with django_assert_max_num_queries(10):
        assert api.get(ORDERS).status_code == 200
