"""Фильтры списка заказов, канбан и выгрузка в Excel (Task 14)."""

import io
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal

import pytest
import time_machine
from django.utils import timezone
from openpyxl import load_workbook

from apps.billing.models import Subscription
from apps.core.handbooks.models import HandbookValue
from apps.core.models import Company, Membership, User
from apps.core.tenancy import tenant_context
from apps.forwarding.consignments.services import create_consignment
from apps.forwarding.finance_lines.models import OrderService
from apps.forwarding.models import Consignment, Order, Trip
from apps.forwarding.orders.services import change_status, create_order
from apps.forwarding.tests.test_orders import (
    ORDERS,
    _svc_cargo,
    hv,
    make_client,
    make_order,
    status_id,
)
from apps.forwarding.tests.test_parties import client_with_role
from apps.forwarding.tests.test_trips import make_carrier, svc_create

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=dt_tz.utc)
BOARD = ORDERS + "board/"
EXPORT = ORDERS + "export/"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture(autouse=True)
def frozen():
    with time_machine.travel(NOW, tick=False):
        yield


@pytest.fixture
def two(make_company):
    return make_company("Co A"), make_company("Co B")


# --- помощники ---


def user_of(company):
    return Membership.objects.filter(company=company).first().user


def mk(company, client=None, name="Груз", load="2026-06-02T09:00:00Z", **extra):
    """Заказ с одним грузом; точка погрузки в момент load (ISO, UTC)."""
    cargo = _svc_cargo(name=name)
    cargo["points"][0]["window_from"] = datetime.fromisoformat(load.replace("Z", "+00:00"))
    return make_order(company, client, consignments=[cargo], **extra)


def set_created(company, order, when):
    with tenant_context(company.id):
        Order.objects.filter(pk=order.pk).update(created_at=when)


def cargo_ids(company, order):
    with tenant_context(company.id):
        return list(
            Consignment.objects.filter(order=order).order_by("id").values_list("pk", flat=True)
        )


def carry(company, order, carrier):
    return svc_create(company, cargo_ids(company, order), carrier)


def to_status(company, order, name):
    with tenant_context(company.id):
        return change_status(
            Order.objects.get(pk=order.pk), hv(company, "order_status", name), user_of(company)
        )


def ids(response):
    assert response.status_code == 200, response.content
    return [o["id"] for o in response.data["results"]]


def sheet(response):
    assert response.status_code == 200, response.content
    wb = load_workbook(io.BytesIO(response.content))
    return [list(row) for row in wb["Заказы"].iter_rows(values_only=True)]


# --- фильтры списка ---


def test_filter_by_two_statuses_comma_and_repeated(admin_client, company):
    a, b, c = (mk(company) for _ in range(3))
    to_status(company, a, "В работе")
    to_status(company, b, "Завершён")
    work, done = status_id(company, "В работе"), status_id(company, "Завершён")
    expected = {a.pk, b.pk}
    assert set(ids(admin_client.get(ORDERS, {"status": f"{work},{done}"}))) == expected
    assert set(ids(admin_client.get(ORDERS + f"?status={work}&status={done}"))) == expected
    assert ids(admin_client.get(ORDERS, {"status": work})) == [a.pk]
    assert c.pk not in expected


def test_search_finds_order_by_cargo_name(admin_client, company):
    target = mk(company, name="Консервы")
    mk(company, name="Мука")
    assert ids(admin_client.get(ORDERS, {"q": "консервы"})) == [target.pk]


def test_filter_by_client(admin_client, company):
    c1, c2 = make_client(company, "Альфа"), make_client(company, "Бета")
    o1, _ = mk(company, c1), mk(company, c2)
    assert ids(admin_client.get(ORDERS, {"client": c1.pk})) == [o1.pk]


def test_filter_by_carrier_counts_only_live_trips(admin_client, company):
    x, y = make_carrier(company, "Х"), make_carrier(company, "Ю")
    o1, o2, o3 = mk(company), mk(company), mk(company)
    carry(company, o1, x)
    trip = carry(company, o2, y)
    with tenant_context(company.id):
        Trip.objects.get(pk=trip.pk).delete()  # мягкое удаление рейса
    carry(company, o3, x)
    carry(company, o3, x)  # два рейса одного перевозчика: без дублей
    assert set(ids(admin_client.get(ORDERS, {"carrier": x.pk}))) == {o1.pk, o3.pk}
    assert ids(admin_client.get(ORDERS, {"carrier": y.pk})) == []


def test_filter_by_carrier_ignores_deleted_cargo(admin_client, company):
    x = make_carrier(company, "Х")
    order = mk(company)
    carry(company, order, x)
    with tenant_context(company.id):
        Consignment.objects.filter(order=order).first().delete()
    assert ids(admin_client.get(ORDERS, {"carrier": x.pk})) == []


def test_filter_unassigned(admin_client, company):
    x = make_carrier(company, "Х")
    carried, bare, no_carrier_trip = mk(company), mk(company), mk(company)
    carry(company, carried, x)
    carry(company, no_carrier_trip, None)  # рейс без перевозчика не считается
    assert set(ids(admin_client.get(ORDERS, {"unassigned": "1"}))) == {bare.pk, no_carrier_trip.pk}
    assert len(ids(admin_client.get(ORDERS, {"unassigned": "0"}))) == 3
    assert admin_client.get(ORDERS, {"unassigned": "2"}).status_code == 400


def test_loading_dates_are_local_inclusive_and_use_earliest_point(admin_client, company):
    # 20:00 UTC 2 июня = 01:00 3 июня в Алматы (+05:00)
    late = mk(company, load="2026-06-02T20:00:00Z")
    early = mk(company, load="2026-06-02T18:59:00Z")  # 23:59 2 июня по Алматы
    both = mk(company, load="2026-06-10T09:00:00Z")
    with tenant_context(company.id):
        # второй груз с более ранней погрузкой: заказ определяется самой ранней точкой
        item = _svc_cargo(name="Ранний")
        item["points"][0]["window_from"] = datetime(2026, 6, 5, 9, 0, tzinfo=dt_tz.utc)
        create_consignment(both, item)
    got = lambda **p: set(ids(admin_client.get(ORDERS, p)))  # noqa: E731
    assert got(loading_from="2026-06-03") == {late.pk, both.pk}
    assert got(loading_to="2026-06-02") == {early.pk}
    assert got(loading_from="2026-06-03", loading_to="2026-06-03") == {late.pk}
    assert got(loading_from="2026-06-05", loading_to="2026-06-05") == {both.pk}  # 5-е, не 10-е
    assert got(loading_from="2026-06-06") == set()  # самая ранняя точка 5-го, поздняя не в счёт
    assert got(loading_from="2026-06-10") == set()


def test_loading_filter_ignores_deleted_consignment_points(admin_client, company):
    order = mk(company, load="2026-06-10T09:00:00Z")
    with tenant_context(company.id):
        item = _svc_cargo(name="Удалённый")
        item["points"][0]["window_from"] = datetime(2026, 6, 2, 9, 0, tzinfo=dt_tz.utc)
        create_consignment(order, item).delete()
    assert ids(admin_client.get(ORDERS, {"loading_from": "2026-06-10"})) == [order.pk]
    assert ids(admin_client.get(ORDERS, {"loading_to": "2026-06-05"})) == []


def test_created_and_completed_date_filters_local(admin_client, company):
    o1, o2, o3 = mk(company), mk(company), mk(company)
    set_created(company, o1, datetime(2026, 5, 31, 18, 59, tzinfo=dt_tz.utc))  # 23:59 31 мая
    set_created(company, o2, datetime(2026, 5, 31, 19, 0, tzinfo=dt_tz.utc))  # 00:00 1 июня
    set_created(company, o3, datetime(2026, 6, 1, 18, 59, tzinfo=dt_tz.utc))  # 23:59 1 июня
    got = lambda **p: set(ids(admin_client.get(ORDERS, p)))  # noqa: E731
    assert got(created_from="2026-06-01") == {o2.pk, o3.pk}
    assert got(created_to="2026-05-31") == {o1.pk}
    assert got(created_from="2026-06-01", created_to="2026-06-01") == {o2.pk, o3.pk}
    to_status(company, o2, "Завершён")  # completed_at = NOW (17:00 1 июня по Алматы)
    assert got(completed_from="2026-06-01", completed_to="2026-06-01") == {o2.pk}
    assert got(completed_from="2026-06-02") == set()
    assert got(completed_to="2026-05-31") == set()


def test_company_timezone_is_used(admin_client, company):
    order = mk(company)
    set_created(company, order, datetime(2026, 5, 31, 19, 0, tzinfo=dt_tz.utc))
    Company.objects.filter(pk=company.pk).update(timezone="UTC")
    assert ids(admin_client.get(ORDERS, {"created_to": "2026-05-31"})) == [order.pk]
    assert ids(admin_client.get(ORDERS, {"created_from": "2026-06-01"})) == []


def test_from_after_to_is_allowed_and_empty(admin_client, company):
    mk(company)
    r = admin_client.get(ORDERS, {"created_from": "2026-07-01", "created_to": "2026-01-01"})
    assert r.status_code == 200 and r.data["count"] == 0


@pytest.mark.parametrize(
    "param,value",
    [
        ("client", "x"),
        ("client", "1;"),
        ("client", "99999999999999999999999"),
        ("status", "1,x"),
        ("status", "-1"),
        ("status", "1,99999999999999999999999"),
        ("carrier", "abc"),
        ("carrier", "-3"),
        ("unassigned", "maybe"),
        ("loading_from", "2026-02-30"),
        ("loading_from", "garbage"),
        ("loading_to", "2026-13-01"),
        ("created_from", "0000-00-00"),
        ("created_to", "9999-99-99"),
        ("created_to", "2026-06-01T10:00:00"),
        ("completed_from", "01.06.2026"),
        ("completed_to", "99999999999999999999-01-01"),
        ("completed_to", "'; DROP TABLE x;--"),
    ],
)
def test_invalid_filter_values_are_400_naming_the_parameter(admin_client, param, value):
    r = admin_client.get(ORDERS, {param: value})
    assert r.status_code == 400, (param, value)
    assert param in r.data
    assert admin_client.get(BOARD, {param: value}).status_code == 400
    assert admin_client.get(EXPORT, {param: value}).status_code == 400


@pytest.mark.parametrize("value", ["0001-01-01", "9999-12-31"])
def test_extreme_valid_dates_do_not_crash(admin_client, company, value):
    mk(company)
    for param in ("loading_from", "loading_to", "created_from", "created_to", "completed_to"):
        assert admin_client.get(ORDERS, {param: value}).status_code == 200, (param, value)


def test_filters_combine_with_and(admin_client, company):
    x = make_carrier(company, "Х")
    c1, c2 = make_client(company, "Альфа"), make_client(company, "Бета")
    hit, other_client, other_status = mk(company, c1), mk(company, c2), mk(company, c1)
    for order in (hit, other_client, other_status):
        carry(company, order, x)
    for order in (hit, other_client):
        to_status(company, order, "В работе")
    work = status_id(company, "В работе")
    got = ids(
        admin_client.get(ORDERS, {"status": work, "client": c1.pk, "carrier": x.pk, "q": "груз"})
    )
    assert got == [hit.pk]


def test_unknown_foreign_ids_match_nothing(two):
    (a, api_a), (b, api_b) = [(c, cl) for c, _, cl in two]
    foreign_client = make_client(b, "Чужой")
    foreign_carrier = make_carrier(b, "Чужой")
    mk(a)
    order_b = mk(b, foreign_client)
    carry(b, order_b, foreign_carrier)
    foreign_status = status_id(b, "В работе")
    for params in (
        {"client": foreign_client.pk},
        {"carrier": foreign_carrier.pk},
        {"status": foreign_status},
    ):
        for url in (ORDERS, BOARD):
            r = api_a.get(url, params)
            assert r.status_code == 200, r.content
        assert api_a.get(ORDERS, params).data["count"] == 0
    assert ids(api_b.get(ORDERS, {"carrier": foreign_carrier.pk})) == [order_b.pk]


def test_filtered_list_has_no_duplicates(admin_client, company):
    x = make_carrier(company, "Х")
    order = make_order(
        company,
        consignments=[_svc_cargo(name="Мука А"), _svc_cargo(name="Мука Б")],
    )
    carry(company, order, x)
    carry(company, order, x)
    r = admin_client.get(
        ORDERS,
        {
            "carrier": x.pk,
            "q": "мука",
            "loading_from": "2026-06-01",
            "created_from": "2026-06-01",
            "status": [status_id(company, "Новый"), status_id(company, "В работе")],
        },
    )
    assert ids(r) == [order.pk] and r.data["count"] == 1


def test_list_query_count_with_all_filters(admin_client, company, django_assert_max_num_queries):
    from apps.forwarding.tests.test_orders import LIST_QUERY_BOUND

    x = make_carrier(company, "Х")
    for i in range(12):
        order = make_order(company, consignments=[_svc_cargo(), _svc_cargo(name="Второй")])
        carry(company, order, x)
    params = {
        "q": "Серв",
        "client": "",
        "status": [status_id(company, "Новый")],
        "carrier": x.pk,
        "loading_from": "2026-05-01",
        "loading_to": "2026-07-01",
        "created_from": "2026-05-01",
        "created_to": "2026-07-01",
        "completed_from": "2020-01-01",
        "completed_to": "2030-01-01",
    }
    with django_assert_max_num_queries(LIST_QUERY_BOUND):
        r = admin_client.get(ORDERS, {**params, "completed_from": "", "completed_to": ""})
    assert r.status_code == 200 and r.data["count"] == 12
    with django_assert_max_num_queries(LIST_QUERY_BOUND):
        r = admin_client.get(ORDERS, {"unassigned": "1", "loading_from": "2026-05-01"})
    assert r.status_code == 200 and r.data["count"] == 0


# --- канбан ---


def column(data, name):
    return next(c for c in data if c["status"]["name"] == name)


def test_board_columns_follow_handbook_order_including_empty(admin_client, company):
    mk(company)
    r = admin_client.get(BOARD)
    assert r.status_code == 200, r.content
    with tenant_context(company.id):
        expected = list(
            HandbookValue.objects.filter(handbook__code="order_status", is_active=True).values_list(
                "pk", "name"
            )
        )
    assert [(c["status"]["id"], c["status"]["name"]) for c in r.data] == expected
    assert column(r.data, "Новый")["count"] == 1
    empty = column(r.data, "Завершён")
    assert empty["count"] == 0 and empty["orders"] == [] and empty["has_more"] is False
    assert set(r.data[0]) == {"status", "count", "orders", "has_more"}


def test_board_inactive_status_only_with_orders(admin_client, company):
    order = mk(company)
    to_status(company, order, "В работе")
    with tenant_context(company.id):
        HandbookValue.objects.filter(
            handbook__code="order_status", name__in=["В работе", "На погрузке"]
        ).update(is_active=False)
    names = [c["status"]["name"] for c in admin_client.get(BOARD).data]
    # «Отменён» - системный статус, его деактивировать нельзя, поэтому берём «На погрузке»
    assert "В работе" in names and "На погрузке" not in names


def test_board_card_fields(admin_client, company):
    x, y = make_carrier(company, "Альфа-Транс"), make_carrier(company, "Бета-Транс")
    client = make_client(company, "ТОО Клиент")
    order = mk(company, client, client_rate=Decimal("1234567.89"), load="2026-06-02T20:00:00Z")
    carry(company, order, x)
    carry(company, order, y)
    carry(company, order, x)  # тот же перевозчик: в списке один раз
    bare = mk(company)
    data = admin_client.get(BOARD).data
    cards = {c["id"]: c for c in column(data, "Новый")["orders"]}
    card = cards[order.pk]
    assert set(card) == {
        "id",
        "number",
        "client",
        "route",
        "carriers",
        "rate",
        "currency",
        "loading_at",
        "has_carrier",
    }
    assert card["number"] == order.number and card["client"] == "ТОО Клиент"
    assert card["route"] == "Шымкент → Алматы"
    assert card["carriers"] == ["Альфа-Транс", "Бета-Транс"]
    assert card["rate"] == "1234567.89" and card["currency"] == "KZT"
    assert card["loading_at"] == "2026-06-03T01:00:00+05:00"
    assert card["has_carrier"] is True
    assert cards[bare.pk]["carriers"] == [] and cards[bare.pk]["has_carrier"] is False


def test_board_ignores_deleted_trips_and_orders(admin_client, company):
    x = make_carrier(company, "Х")
    order, gone = mk(company), mk(company)
    trip = carry(company, order, x)
    with tenant_context(company.id):
        Trip.objects.get(pk=trip.pk).delete()
        Order.objects.get(pk=gone.pk).delete()
    col = column(admin_client.get(BOARD).data, "Новый")
    assert col["count"] == 1
    assert col["orders"][0]["carriers"] == [] and col["orders"][0]["has_carrier"] is False


def test_board_limit_has_more_and_order(admin_client, company):
    made = []
    for i in range(5):
        order = mk(company)
        set_created(company, order, NOW + timedelta(minutes=i))
        made.append(order.pk)
    col = column(admin_client.get(BOARD, {"limit": 2}).data, "Новый")
    assert col["count"] == 5 and col["has_more"] is True
    assert [o["id"] for o in col["orders"]] == made[::-1][:2]
    col = column(admin_client.get(BOARD, {"limit": 5}).data, "Новый")
    assert col["has_more"] is False and len(col["orders"]) == 5
    assert len(column(admin_client.get(BOARD).data, "Новый")["orders"]) == 5  # limit 50


def test_board_limit_applies_per_column(admin_client, company):
    for i in range(3):
        to_status(company, mk(company), "В работе")
    for i in range(2):
        mk(company)
    data = admin_client.get(BOARD, {"limit": 2}).data
    assert len(column(data, "В работе")["orders"]) == 2 and column(data, "В работе")["count"] == 3
    assert len(column(data, "Новый")["orders"]) == 2 and column(data, "Новый")["has_more"] is False


@pytest.mark.parametrize("limit", ["0", "-1", "x", "201", "1.5", ""])
def test_board_invalid_limit_is_400(admin_client, limit):
    if limit == "":
        assert admin_client.get(BOARD, {"limit": limit}).status_code == 200
    else:
        r = admin_client.get(BOARD, {"limit": limit})
        assert r.status_code == 400 and "limit" in r.data


def test_board_max_limit_accepted(admin_client):
    assert admin_client.get(BOARD, {"limit": 200}).status_code == 200


def test_board_honours_list_filters(admin_client, company):
    x = make_carrier(company, "Х")
    c1, c2 = make_client(company, "Альфа"), make_client(company, "Бета")
    hit, miss = mk(company, c1, name="Консервы"), mk(company, c2)
    carry(company, hit, x)
    data = admin_client.get(BOARD, {"q": "консервы", "carrier": x.pk, "client": c1.pk}).data
    col = column(data, "Новый")
    assert col["count"] == 1 and [o["id"] for o in col["orders"]] == [hit.pk]
    assert miss.pk not in [o["id"] for c in data for o in c["orders"]]
    data = admin_client.get(BOARD, {"unassigned": "1"}).data
    assert [o["id"] for o in column(data, "Новый")["orders"]] == [miss.pk]
    data = admin_client.get(BOARD, {"status": status_id(company, "В работе")}).data
    assert column(data, "Новый")["count"] == 0  # колонки остаются, заказы отфильтрованы


BOARD_QUERY_BOUND = 11  # измерено: фиксированное число запросов, не зависит от числа заказов


def test_board_query_count_is_flat(admin_client, company, django_assert_max_num_queries):
    x = make_carrier(company, "Х")
    for i in range(30):
        order = make_order(company, consignments=[_svc_cargo(), _svc_cargo(name="Второй")])
        carry(company, order, x)
        if i % 3 == 0:
            to_status(company, order, "В работе")
    with django_assert_max_num_queries(BOARD_QUERY_BOUND):
        r = admin_client.get(BOARD, {"carrier": x.pk, "created_from": "2026-01-01"})
    assert r.status_code == 200
    assert sum(len(c["orders"]) for c in r.data) == 30
    assert all(o["carriers"] == ["Х"] for c in r.data for o in c["orders"])


def test_board_isolation(two):
    (a, _, api_a), (b, _, api_b) = two
    own, foreign = mk(a), mk(b)
    carry(b, foreign, make_carrier(b, "Чужой"))
    data = api_a.get(BOARD).data
    assert [o["id"] for c in data for o in c["orders"]] == [own.pk]
    assert {c["status"]["id"] for c in data}.isdisjoint(
        {c["status"]["id"] for c in api_b.get(BOARD).data}
    )
    assert "Чужой" not in str(data)


# --- выгрузка в Excel ---

HEAD = [
    "Номер",
    "Клиент",
    "Маршрут",
    "Перевозчик",
    "Статус",
    "Погрузка",
    "Ставка",
    "Валюта",
    "Создан",
]
FIN = ["Выручка", "Расходы", "Прибыль", "Маржа %"]


def test_export_headers_filename_and_rows(admin_client, company):
    x = make_carrier(company, "Альфа-Транс")
    o1 = mk(company, make_client(company, "ТОО Клиент"), load="2026-06-02T20:00:00Z")
    o2 = mk(company)
    carry(company, o1, x)
    r = admin_client.get(EXPORT)
    assert r["Content-Type"] == XLSX
    assert r["Content-Disposition"].startswith("attachment")
    assert 'filename="orders-2026-06-01.xlsx"' in r["Content-Disposition"]
    rows = sheet(r)
    assert rows[0] == HEAD + FIN  # администратор имеет finance.view
    assert len(rows) == 3
    by_number = {row[0]: row for row in rows[1:]}
    row = by_number[o1.number]
    assert row[1] == "ТОО Клиент" and row[2] == "Шымкент → Алматы" and row[3] == "Альфа-Транс"
    assert row[4] == "Новый" and row[7] == "KZT"
    assert row[5] == datetime(2026, 6, 3, 1, 0)  # локальное время компании, без пояса
    assert row[8] == datetime(2026, 6, 1, 17, 0)
    assert by_number[o2.number][3] in (None, "")


def test_export_filename_uses_company_date(admin_client, company):
    Company.objects.filter(pk=company.pk).update(timezone="Pacific/Auckland")
    r = admin_client.get(EXPORT)  # 12:00 UTC = 00:00 2 июня в Окленде
    assert 'filename="orders-2026-06-02.xlsx"' in r["Content-Disposition"]


def test_export_row_per_filtered_order_and_filters(admin_client, company):
    c1, c2 = make_client(company, "Альфа"), make_client(company, "Бета")
    hit = mk(company, c1, name="Консервы")
    mk(company, c2)
    gone = mk(company, c1)
    with tenant_context(company.id):
        Order.objects.get(pk=gone.pk).delete()
    rows = sheet(admin_client.get(EXPORT, {"q": "консервы", "client": c1.pk}))
    assert [r[0] for r in rows[1:]] == [hit.number]
    assert len(sheet(admin_client.get(EXPORT))) == 3  # удалённый исключён


def test_export_money_cells_are_exact_numbers(admin_client, company):
    order = mk(company, client_rate=Decimal("1234567.89"))
    with tenant_context(company.id):
        OrderService.objects.create(order=order, title="Расход", expense=Decimal("234567.89"))
    r = admin_client.get(EXPORT)
    row = sheet(r)[1]
    assert isinstance(row[6], (int, float)) and Decimal(str(row[6])) == Decimal("1234567.89")
    assert Decimal(str(row[9])) == Decimal("1234567.89")  # выручка
    assert Decimal(str(row[10])) == Decimal("234567.89")  # расходы
    assert Decimal(str(row[11])) == Decimal("1000000.00")  # прибыль
    assert Decimal(str(row[12])) == Decimal("81.00")  # маржа: 1000000 / 1234567.89
    import zipfile

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        xml = z.read("xl/worksheets/sheet1.xml").decode()
    assert "<v>1234567.89</v>" in xml  # число, а не строка и не округлённый float


def test_export_zero_revenue_margin_cell_is_empty(admin_client, company):
    mk(company)  # ставка 0
    row = sheet(admin_client.get(EXPORT))[1]
    assert row[12] in (None, "")


def test_export_finance_columns_only_with_finance_view(company):
    mk(company)
    _, dispatcher = client_with_role(company, "Диспетчер")
    rows = sheet(dispatcher.get(EXPORT))
    assert rows[0] == HEAD and len(rows[1]) == len(HEAD)
    _, manager = client_with_role(company, "Менеджер")  # finance.view есть
    assert sheet(manager.get(EXPORT))[0] == HEAD + FIN


@pytest.mark.parametrize(
    "evil", ['=HYPERLINK("http://evil","x")', "+1+1", "-2+3", "@SUM(A1)", "\tcmd", "\rcmd"]
)
def test_export_neutralises_formula_injection(admin_client, company, evil):
    client = make_client(company, evil)
    cargo = _svc_cargo()
    cargo["points"][0]["city"] = evil
    make_order(company, client, consignments=[cargo])
    carrier = make_carrier(company, evil)
    order = make_order(company, client, consignments=[_svc_cargo()])
    carry(company, order, carrier)
    rows = sheet(admin_client.get(EXPORT))[1:]
    texts = [c for row in rows for c in row if isinstance(c, str)]
    evil = evil.replace("\r", "\n")  # XML при чтении приводит CR к LF
    texts = [t.replace("\r", "\n") for t in texts]
    assert any(t.endswith(evil) for t in texts)
    for text in texts:
        assert text[0] not in "=+-@\t\r", text
    assert any(t == "'" + evil for t in texts)  # клиент
    assert any(t.startswith("'" + evil) for t in texts)  # маршрут
    wb = load_workbook(io.BytesIO(admin_client.get(EXPORT).content))
    for row in wb["Заказы"].iter_rows():
        for cell in row:
            assert cell.data_type != "f", cell.value


def test_export_limit_is_400_with_russian_message(admin_client, company, monkeypatch):
    from apps.forwarding.orders import export

    assert export.EXPORT_LIMIT == 10_000
    monkeypatch.setattr(export, "EXPORT_LIMIT", 2)
    for _ in range(3):
        mk(company)
    r = admin_client.get(EXPORT)
    assert r.status_code == 400
    assert "фильтр" in str(r.data).lower()
    assert sheet(admin_client.get(EXPORT, {"q": mk(company, name="Уникальный").number})) != []


def test_export_exactly_at_limit_passes(admin_client, company, monkeypatch):
    from apps.forwarding.orders import export

    monkeypatch.setattr(export, "EXPORT_LIMIT", 3)
    for _ in range(3):
        mk(company)
    assert len(sheet(admin_client.get(EXPORT))) == 4


EXPORT_QUERY_BOUND = 11  # 9 + дешёвая проверка лимита + режим учёта


def test_export_query_count_is_flat(admin_client, company, django_assert_max_num_queries):
    x = make_carrier(company, "Х")
    for _ in range(25):
        order = make_order(company, consignments=[_svc_cargo(), _svc_cargo(name="Второй")])
        carry(company, order, x)
    with django_assert_max_num_queries(EXPORT_QUERY_BOUND):
        r = admin_client.get(EXPORT, {"carrier": x.pk})
    assert len(sheet(r)) == 26


def test_export_isolation(two):
    (a, _, api_a), (b, _, api_b) = two
    own = mk(a, make_client(a, "Свой"))
    foreign = mk(b, make_client(b, "Чужой"))
    carry(b, foreign, make_carrier(b, "ЧужойПеревозчик"))
    rows = sheet(api_a.get(EXPORT))
    assert [r[0] for r in rows[1:]] == [own.number]
    assert "Чужой" not in str([c for r in rows for c in r])
    assert [r[0] for r in sheet(api_b.get(EXPORT))[1:]] == [foreign.number]


def test_export_and_board_permissions(company, admin_client):
    mk(company)
    for role in ("Механик", "Водитель"):
        _, api = client_with_role(company, role)
        assert api.get(EXPORT).status_code == 403, role
        assert api.get(BOARD).status_code == 403, role
    _, observer = client_with_role(company, "Наблюдатель")
    assert observer.get(EXPORT).status_code == 200 and observer.get(BOARD).status_code == 200
    from rest_framework.test import APIClient

    anon = APIClient()
    assert anon.get(EXPORT).status_code == 401 and anon.get(BOARD).status_code == 401
    assert admin_client.post(EXPORT).status_code == 405
    assert admin_client.post(BOARD).status_code == 405


def test_export_and_board_subscription_states(company, admin_client):
    mk(company)
    Subscription.objects.filter(company=company).update(ends_at=timezone.now() - timedelta(days=20))
    assert admin_client.get(EXPORT).status_code == 200  # только чтение
    assert admin_client.get(BOARD).status_code == 200
    Subscription.objects.filter(company=company).update(
        status=Subscription.BLOCKED, ends_at=timezone.now() + timedelta(days=20)
    )
    for url in (EXPORT, BOARD):
        r = admin_client.get(url)
        assert r.status_code == 403 and r.data["code"] == "subscription_blocked"


def test_module_disabled_blocks_board_and_export(make_company):
    _, _, api = make_company("Без модуля", modules=["fleet"])
    assert api.get(BOARD).status_code == 403 and api.get(EXPORT).status_code == 403


# --- RLS под ролью приложения ---


def test_list_board_export_work_under_app_role(db, api_client):
    from apps.core.services import create_company_with_defaults
    from apps.core.tests.test_rls import app_role
    from conftest import TEST_PASSWORD

    with app_role():
        admin = User.objects.create_user(email="rls-v@x.kz", password=TEST_PASSWORD)
        company = create_company_with_defaults("RLS V", admin, ["forwarding"])
        other = User.objects.create_user(email="rls-v2@x.kz", password=TEST_PASSWORD)
        other_company = create_company_with_defaults("RLS V2", other, ["forwarding"])
        with tenant_context(other_company.id):
            create_order({"client": make_client_in(other_company), "comment": "чужой"}, other)
        resp = api_client.post(
            "/api/auth/login/", {"login": "rls-v@x.kz", "password": TEST_PASSWORD}
        )
        assert resp.status_code == 200, resp.content
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
        cl = api_client.post("/api/clients/", {"name": "ТОО Тест"}, format="json")
        assert cl.status_code == 201, cl.content
        carrier = api_client.post("/api/carriers/", {"name": "Перевозчик"}, format="json")
        assert carrier.status_code == 201, carrier.content
        cargo = {
            "name": "Консервы",
            "weight_kg": "10",
            "volume_m3": "1",
            "points": [
                {"kind": "load", "window_from": "2026-06-02T09:00:00Z", "city": "А"},
                {"kind": "unload", "window_from": "2026-06-03T09:00:00Z", "city": "Б"},
            ],
        }
        order = api_client.post(
            ORDERS, {"client": cl.data["id"], "consignments": [cargo]}, format="json"
        )
        assert order.status_code == 201, order.content
        with tenant_context(company.id):
            ids_ = list(Consignment.objects.values_list("pk", flat=True))
        trip = api_client.post(
            "/api/trips/", {"consignments": ids_, "carrier": carrier.data["id"]}, format="json"
        )
        assert trip.status_code == 201, trip.content
        params = {"carrier": carrier.data["id"], "q": "консервы", "loading_from": "2026-06-02"}
        listing = api_client.get(ORDERS, params)
        assert listing.status_code == 200 and listing.data["count"] == 1
        board = api_client.get(BOARD, params)
        assert board.status_code == 200
        assert sum(c["count"] for c in board.data) == 1
        card = next(o for c in board.data for o in c["orders"])
        assert card["carriers"] == ["Перевозчик"] and card["has_carrier"] is True
        export = api_client.get(EXPORT, params)
        assert export.status_code == 200
        rows = sheet(export)
        assert len(rows) == 2 and rows[1][3] == "Перевозчик"
        assert api_client.get(ORDERS, {"unassigned": 1}).data["count"] == 0


def make_client_in(company):
    from apps.forwarding.models import Client

    return Client.objects.create(name="Чужой клиент")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ТОО \x0bКлиент", "ТОО Клиент"),
        ("\x0b=cmd", "'=cmd"),
        ("\x01\x1f@x", "'@x"),
        ("A\x08B\x0cC\x0eD", "ABCD"),
    ],
)
def test_export_strips_xml_illegal_characters(admin_client, company, raw, expected):
    cargo = _svc_cargo()
    cargo["points"][0]["city"] = raw
    make_order(company, make_client(company, raw), consignments=[cargo])
    r = admin_client.get(EXPORT)
    assert r.status_code == 200, r.content
    row = sheet(r)[1]
    assert row[1] == expected
    assert row[2].startswith(expected)


@pytest.mark.parametrize(
    "accept", [XLSX, "application/json", "*/*", None, "text/html", "application/xml"]
)
def test_export_ignores_accept_header(admin_client, company, accept):
    mk(company)
    extra = {"HTTP_ACCEPT": accept} if accept else {}
    r = admin_client.get(EXPORT, **extra)
    assert r.status_code == 200 and r["Content-Type"] == XLSX
    assert len(sheet(r)) == 2


def test_export_limit_checked_before_loading_rows(
    admin_client, company, monkeypatch, django_assert_max_num_queries
):
    from apps.forwarding.orders import export

    monkeypatch.setattr(export, "EXPORT_LIMIT", 2)
    for _ in range(3):
        mk(company)
    with django_assert_max_num_queries(
        8
    ):  # вход, подписка, savepoints, режим учёта, проверка лимита; без выборок
        r = admin_client.get(EXPORT)
    assert r.status_code == 400 and "фильтр" in str(r.data).lower()
