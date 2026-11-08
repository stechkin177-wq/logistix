"""Этап 1.5-B2: API груза - stops (полный маршрут) и устаревшее поле points."""

import pytest

from apps.core.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.forwarding.models import Consignment, ConsignmentPoint
from apps.forwarding.tests.test_orders import (
    CONSIGNMENTS,
    ORDERS,
    cargo,
    make_client,
    new_order,
    point,
)
from apps.forwarding.tests.test_parties import client_with_role

pytestmark = pytest.mark.django_db


def stop(kind, city, **extra):
    return point(kind, city, **extra)


def three(**extra):
    return [stop("load", "Астана"), stop("transit", "Караганда"), stop("unload", "Алматы")]


def stops_cargo(name="Груз", stops=None, **extra):
    base = cargo(name)
    base.pop("points")
    return {**base, "stops": stops if stops is not None else three(), **extra}


@pytest.fixture
def two(make_company):
    return make_company("Co A"), make_company("Co B")


def new_consignment(api, order_id, **kwargs):
    r = api.post(CONSIGNMENTS, {**stops_cargo(**kwargs), "order": order_id}, format="json")
    assert r.status_code == 201, r.content
    return r.data


def test_create_with_stops_reads_stops_and_legacy_points(admin_client, company):
    order = new_order(admin_client, make_client(company))
    c = new_consignment(admin_client, order["id"])
    assert [(s["seq"], s["kind"], s["city"], s["status"]) for s in c["stops"]] == [
        (1, "load", "Астана", "planned"),
        (2, "transit", "Караганда", "planned"),
        (3, "unload", "Алматы", "planned"),
    ]
    # устаревшее поле: первая погрузка и последняя выгрузка, как раньше
    assert [(p["kind"], p["city"]) for p in c["points"]] == [
        ("load", "Астана"),
        ("unload", "Алматы"),
    ]
    assert admin_client.get(f"{ORDERS}{order['id']}/").data["route"] == "Астана → Алматы"
    got = admin_client.get(f"{CONSIGNMENTS}{c['id']}/").data
    assert len(got["stops"]) == 3 and len(got["points"]) == 2
    with tenant_context(company.id):
        rows = list(AuditLog.objects.filter(object_type="forwarding.consignment").order_by("id"))
    assert rows[0].changes["points"] == "changed"


def test_order_create_with_nested_stops(admin_client, company):
    d = new_order(admin_client, make_client(company), consignments=[stops_cargo()])
    cons = d["consignments"][0]
    assert len(cons["stops"]) == 3 and len(cons["points"]) == 2
    assert d["route"] == "Астана → Алматы"


def test_old_client_with_points_only_works_unchanged(admin_client, company):
    order = new_order(admin_client, make_client(company))
    r = admin_client.post(CONSIGNMENTS, {**cargo(), "order": order["id"]}, format="json")
    assert r.status_code == 201, r.content
    assert [p["kind"] for p in r.data["points"]] == ["load", "unload"]
    assert [(s["seq"], s["kind"]) for s in r.data["stops"]] == [(1, "load"), (2, "unload")]
    r = admin_client.patch(
        f"{CONSIGNMENTS}{r.data['id']}/",
        {"points": [{"kind": "load", "city": "Тараз"}, {"kind": "unload"}]},
        format="json",
    )
    assert r.status_code == 200 and r.data["points"][0]["city"] == "Тараз"
    assert r.data["stops"][0]["city"] == "Тараз"


def test_legacy_points_patch_updates_edges_of_multistop_route(admin_client, company):
    order = new_order(admin_client, make_client(company))
    c = new_consignment(admin_client, order["id"])
    r = admin_client.patch(
        f"{CONSIGNMENTS}{c['id']}/",
        {"points": [{"kind": "load", "city": "Павлодар"}, {"kind": "unload", "city": "Тараз"}]},
        format="json",
    )
    assert r.status_code == 200, r.content
    assert [s["city"] for s in r.data["stops"]] == ["Павлодар", "Караганда", "Тараз"]
    assert [p["city"] for p in r.data["points"]] == ["Павлодар", "Тараз"]


def test_points_and_stops_together_are_rejected(admin_client, company):
    order = new_order(admin_client, make_client(company))
    body = {**stops_cargo(), "points": cargo()["points"], "order": order["id"]}
    r = admin_client.post(CONSIGNMENTS, body, format="json")
    assert r.status_code == 400 and "stops" in r.data
    c = new_consignment(admin_client, order["id"])
    r = admin_client.patch(
        f"{CONSIGNMENTS}{c['id']}/",
        {"stops": three(), "points": cargo()["points"]},
        format="json",
    )
    assert r.status_code == 400
    body = stops_cargo()
    del body["stops"]
    assert (
        admin_client.post(CONSIGNMENTS, {**body, "order": order["id"]}, format="json").status_code
        == 400
    )


@pytest.mark.parametrize(
    "bad",
    [
        [],
        [stop("load", "A")],
        [stop("unload", "A"), stop("load", "B")],
        [stop("load", "A"), stop("transit", "B")],
        [stop("load", "A"), stop("river", "B"), stop("unload", "C")],
        [stop("load", "A"), stop("unload", "B", window_to="2026-06-01T09:00:00Z")],
        [stop("load", "A"), stop("unload", "")],
    ],
)
def test_invalid_routes_are_400_and_create_nothing(admin_client, company, bad):
    order = new_order(admin_client, make_client(company))
    r = admin_client.post(
        CONSIGNMENTS, {**stops_cargo(stops=bad), "order": order["id"]}, format="json"
    )
    assert r.status_code == 400 and "stops" in r.data, bad
    with tenant_context(company.id):
        assert Consignment.objects.count() == 0 and ConsignmentPoint.objects.count() == 0


def test_patch_stops_inserts_reorders_and_deletes_transactionally(admin_client, company):
    order = new_order(admin_client, make_client(company))
    c = new_consignment(admin_client, order["id"])
    a, b, z = c["stops"]
    url = f"{CONSIGNMENTS}{c['id']}/"
    r = admin_client.patch(
        url,
        {
            "stops": [
                {"id": a["id"]},
                stop("customs", "Граница"),
                {"id": b["id"], "city": "Караганда-2", "weight_kg": "100"},
                {"id": z["id"]},
            ]
        },
        format="json",
    )
    assert r.status_code == 200, r.content
    got = r.data["stops"]
    assert [(s["seq"], s["kind"], s["city"]) for s in got] == [
        (1, "load", "Астана"),
        (2, "customs", "Граница"),
        (3, "transit", "Караганда-2"),
        (4, "unload", "Алматы"),
    ]
    assert got[0]["id"] == a["id"] and got[2]["id"] == b["id"] and got[3]["id"] == z["id"]
    assert got[2]["weight_kg"] == "100.00" and got[0]["weight_kg"] is None
    # перестановка и удаление
    r = admin_client.patch(
        url,
        {"stops": [{"id": a["id"]}, {"id": b["id"]}, {"id": z["id"]}]},
        format="json",
    )
    assert r.status_code == 200
    assert [s["city"] for s in r.data["stops"]] == ["Астана", "Караганда-2", "Алматы"]
    # некорректная замена откатывается целиком (первая остановка не погрузка)
    r = admin_client.patch(
        url,
        {"stops": [{"id": b["id"], "city": "Не сохранится"}, {"id": a["id"]}, {"id": z["id"]}]},
        format="json",
    )
    assert r.status_code == 400
    after = admin_client.get(url).data["stops"]
    assert [s["city"] for s in after] == ["Астана", "Караганда-2", "Алматы"]
    with tenant_context(company.id):
        last = list(AuditLog.objects.filter(object_type="forwarding.consignment").order_by("id"))[
            -1
        ]
    assert last.changes == {"points": "changed", "stops": "changed"}


def test_patch_stops_foreign_id_and_shares(admin_client, company):
    order = new_order(admin_client, make_client(company))
    c1 = new_consignment(admin_client, order["id"])
    c2 = new_consignment(admin_client, order["id"], name="Другой")
    url = f"{CONSIGNMENTS}{c1['id']}/"
    foreign = c2["stops"][1]["id"]
    r = admin_client.patch(
        url,
        {"stops": [{"id": c1["stops"][0]["id"]}, {"id": foreign}, {"id": c1["stops"][2]["id"]}]},
        format="json",
    )
    assert r.status_code == 400 and "stops" in r.data
    too_much = [{"id": s["id"]} for s in c1["stops"]]
    too_much[1]["weight_kg"] = "999999"
    assert admin_client.patch(url, {"stops": too_much}, format="json").status_code == 400


def test_isolation_and_permissions(two):
    (comp_a, _, api_a), (comp_b, _, api_b) = two
    order = new_order(api_a, make_client(comp_a))
    c = new_consignment(api_a, order["id"])
    url = f"{CONSIGNMENTS}{c['id']}/"
    assert api_b.get(url).status_code == 404
    r = api_b.patch(url, {"stops": three()}, format="json")
    assert r.status_code == 404
    # чужой id остановки в своём грузе
    order_b = new_order(api_b, make_client(comp_b))
    cb = new_consignment(api_b, order_b["id"])
    r = api_b.patch(
        f"{CONSIGNMENTS}{cb['id']}/",
        {"stops": [{"id": s["id"]} for s in c["stops"]]},
        format="json",
    )
    assert r.status_code == 400
    # права: водитель - 403 на запись, 403 на чтение (как у груза); менеджер пишет
    _, driver = client_with_role(comp_a, "Водитель")
    assert driver.patch(url, {"stops": three()}, format="json").status_code == 403
    _, manager = client_with_role(comp_a, "Менеджер")
    r = manager.patch(
        url,
        {"stops": [{"id": s["id"]} for s in c["stops"][:1]] + [stop("unload", "Омск")]},
        format="json",
    )
    assert r.status_code == 200, r.content
    assert [s["city"] for s in r.data["stops"]] == ["Астана", "Омск"]


def test_list_filters_and_route_use_first_load_and_last_unload(admin_client, company):
    order = new_order(admin_client, make_client(company))
    stops = [
        stop("load", "Первая", window_from="2026-06-05T09:00:00Z", window_to=None),
        stop("load", "Вторая", window_from="2026-06-03T09:00:00Z", window_to=None),
        stop("unload", "Предпоследняя", window_from="2026-06-08T09:00:00Z", window_to=None),
        stop("unload", "Последняя", window_from="2026-06-09T09:00:00Z", window_to=None),
    ]
    new_consignment(admin_client, order["id"], stops=stops)
    got = admin_client.get(f"{ORDERS}{order['id']}/").data
    assert got["route"] == "Первая → Последняя"
    # погрузка заказа - ПЕРВАЯ погрузка маршрута (5 июня), а не самое раннее окно (3 июня)
    listed = admin_client.get(ORDERS, {"loading_from": "2026-06-05", "loading_to": "2026-06-05"})
    assert [o["id"] for o in listed.data["results"]] == [order["id"]]
    listed = admin_client.get(ORDERS, {"loading_from": "2026-06-03", "loading_to": "2026-06-04"})
    assert listed.data["results"] == []
