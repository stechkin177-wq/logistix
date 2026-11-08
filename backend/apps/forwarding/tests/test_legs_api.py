"""Этап 1.5-C3: API рейса - legs (участки) при прежних consignments/orders."""

import pytest

from apps.core.tenancy import tenant_context
from apps.forwarding.tests.test_legs import make_cargos, stops_of
from apps.forwarding.tests.test_orders import CONSIGNMENTS, ORDERS
from apps.forwarding.tests.test_parties import client_with_role
from apps.forwarding.tests.test_trips import TRIPS, trip_url

pytestmark = pytest.mark.django_db


@pytest.fixture
def two(make_company):
    return make_company("Co A"), make_company("Co B")


def leg_body(c, a, b, **shares):
    body = {"consignment": c.pk, "from_stop": a.pk, "to_stop": b.pk}
    if shares:
        body["shares"] = {k: str(v) for k, v in shares.items()}
    return body


def post_trip(api, **body):
    return api.post(TRIPS, body, format="json")


def test_old_client_create_returns_whole_route_leg_and_old_fields(admin_client, company):
    order, (c,) = make_cargos(company)
    s1, s2, s3 = stops_of(company, c)
    r = post_trip(admin_client, consignments=[c.pk])
    assert r.status_code == 201, r.content
    d = r.data
    assert [x["id"] for x in d["consignments"]] == [c.pk]
    assert d["orders"] == [{"id": order.pk, "number": order.number}]
    (leg,) = d["legs"]
    assert leg["consignment"] == c.pk and leg["consignment_name"] == "Груз 0"
    assert leg["from_stop"] == {"id": s1.pk, "seq": 1, "kind": "load", "city": "Город 1"}
    assert leg["to_stop"]["id"] == s3.pk and leg["status"] == "planned" and leg["leg_seq"] == 1
    assert leg["weight_kg"] is None and leg["order_number"] == order.number


def test_create_with_legs_only_and_two_legs_in_one_trip(admin_client, company):
    _, (c,) = make_cargos(company, stops_per=4)
    s1, s2, s3, s4 = stops_of(company, c)
    r = post_trip(
        admin_client,
        legs=[leg_body(c, s2, s4, weight_kg="300.00"), leg_body(c, s1, s2)],
    )
    assert r.status_code == 201, r.content
    assert [x["id"] for x in r.data["consignments"]] == [c.pk]  # груз один, хотя участков два
    assert [(x["from_stop"]["seq"], x["to_stop"]["seq"], x["leg_seq"]) for x in r.data["legs"]] == [
        (1, 2, 1),
        (2, 4, 2),
    ]
    assert r.data["legs"][1]["weight_kg"] == "300.00"
    got = admin_client.get(trip_url(r.data["id"]))
    assert len(got.data["legs"]) == 2 and len(got.data["consignments"]) == 1
    cargo = admin_client.get(f"{CONSIGNMENTS}{c.pk}/").data
    assert cargo["trips_count"] == 1  # рейсов, а не участков
    assert cargo["route"]["coverage"]["fully_assigned"] is True


def test_create_needs_consignments_or_legs_and_validates_legs(admin_client, company):
    _, (c, other) = make_cargos(company, count=2)
    s1, s2, s3 = stops_of(company, c)
    o1, _, o3 = stops_of(company, other)
    assert post_trip(admin_client).status_code == 400
    assert post_trip(admin_client, consignments=[]).status_code == 400
    assert post_trip(admin_client, legs=[]).status_code == 400
    r = post_trip(admin_client, legs=[leg_body(c, s2, s1)])
    assert r.status_code == 400 and "legs" in r.data
    r = post_trip(admin_client, legs=[leg_body(c, o1, o3)])
    assert r.status_code == 400
    r = post_trip(admin_client, legs=[{"consignment": c.pk, "from_stop": s1.pk}])
    assert r.status_code == 400
    r = post_trip(admin_client, legs=[leg_body(c, s1, s3, weight_kg="-1")])
    assert r.status_code == 400
    r = post_trip(admin_client, legs=[leg_body(c, s1, s3, weight_kg="999999")])
    assert r.status_code == 400 and "legs" in r.data
    assert admin_client.get(TRIPS).data["count"] == 0


def test_reassign_with_legs_and_without(admin_client, company):
    _, (c,) = make_cargos(company)
    s1, s2, s3 = stops_of(company, c)
    trip = post_trip(admin_client, consignments=[c.pk]).data
    url = trip_url(trip["id"], "reassign/")
    r = admin_client.post(
        url, {"consignment_ids": [c.pk], "legs": [leg_body(c, s1, s2)]}, format="json"
    )
    assert r.status_code == 200, r.content
    assert [(x["from_stop"]["seq"], x["to_stop"]["seq"]) for x in r.data["legs"]] == [(1, 2)]
    # второй рейс берёт остаток; старый reassign без legs ничего не ломает
    t2 = post_trip(admin_client, legs=[leg_body(c, s2, s3)])
    assert t2.status_code == 201
    r = admin_client.post(url, {"consignment_ids": [c.pk]}, format="json")
    assert r.status_code == 200 and len(r.data["legs"]) == 1
    assert admin_client.post(url, {}, format="json").status_code == 400
    assert admin_client.post(url, {"consignment_ids": []}, format="json").status_code == 400
    r = admin_client.post(url, {"legs": [leg_body(c, s1, s3)]}, format="json")  # пересекается с t2
    assert r.status_code == 400 and "legs" in r.data


def test_patch_cannot_change_legs_or_consignments(admin_client, company):
    _, (c,) = make_cargos(company)
    s1, _s2, s3 = stops_of(company, c)
    trip = post_trip(admin_client, consignments=[c.pk]).data
    r = admin_client.patch(trip_url(trip["id"]), {"legs": [leg_body(c, s1, s3)]}, format="json")
    assert r.status_code == 400 and "legs" in r.data


def test_status_endpoint_updates_leg_statuses(admin_client, company):
    _, (c,) = make_cargos(company)
    trip = post_trip(admin_client, consignments=[c.pk]).data
    with tenant_context(company.id):
        from apps.core.handbooks.models import HandbookValue

        done = HandbookValue.objects.get(handbook__code="trip_status", code="COMPLETED").pk
        cancelled = HandbookValue.objects.get(handbook__code="trip_status", code="CANCELLED").pk
    r = admin_client.post(trip_url(trip["id"], "status/"), {"status": done}, format="json")
    assert r.status_code == 200 and [x["status"] for x in r.data["legs"]] == ["done"]
    r = admin_client.post(
        trip_url(trip["id"], "status/"), {"status": cancelled, "reason": "ошибка"}, format="json"
    )
    assert r.status_code == 200 and [x["status"] for x in r.data["legs"]] == ["cancelled"]
    cargo = admin_client.get(f"{CONSIGNMENTS}{c.pk}/").data
    assert cargo["route"]["coverage"]["fully_assigned"] is False
    assert len(cargo["route"]["coverage"]["uncovered"]) == 2


def test_consignment_and_order_expose_route_with_coverage(admin_client, company):
    order, (c,) = make_cargos(company, stops_per=3)
    s1, s2, s3 = stops_of(company, c)
    post_trip(admin_client, legs=[leg_body(c, s1, s2)])
    cargo = admin_client.get(f"{CONSIGNMENTS}{c.pk}/").data
    route = cargo["route"]
    assert [s["seq"] for s in route["stops"]] == [1, 2, 3]
    cov = route["coverage"]
    assert cov["fully_assigned"] is False
    assert [(x["from_stop"], x["to_stop"], x["covered"]) for x in cov["segments"]] == [
        (s1.pk, s2.pk, True),
        (s2.pk, s3.pk, False),
    ]
    assert [(u["from_stop"], u["to_stop"]) for u in cov["uncovered"]] == [(s2.pk, s3.pk)]
    in_order = admin_client.get(f"{ORDERS}{order.pk}/").data["consignments"][0]
    assert in_order["route"]["coverage"]["fully_assigned"] is False
    listed = admin_client.get(CONSIGNMENTS, {"order": order.pk}).data["results"][0]
    assert listed["route"]["coverage"]["uncovered"]


def test_permissions_and_isolation(two):
    (comp_a, _, api_a), (comp_b, _, api_b) = two
    _, (c,) = make_cargos(comp_a)
    s1, s2, s3 = stops_of(comp_a, c)
    _, (cb,) = make_cargos(comp_b)
    b1, b2, b3 = stops_of(comp_b, cb)
    trip = post_trip(api_a, legs=[leg_body(c, s1, s2)]).data
    # чужая компания не видит рейс и не может использовать чужие груз/остановки
    assert api_b.get(trip_url(trip["id"])).status_code == 404
    assert post_trip(api_b, legs=[leg_body(c, s1, s3)]).status_code == 400
    assert post_trip(api_b, legs=[leg_body(cb, s1, s3)]).status_code == 400  # чужие остановки
    assert post_trip(api_b, legs=[leg_body(cb, b1, b3)]).status_code == 201
    # водитель не создаёт рейсы, менеджер создаёт
    _, driver = client_with_role(comp_a, "Водитель")
    assert post_trip(driver, legs=[leg_body(c, s2, s3)]).status_code == 403
    _, manager = client_with_role(comp_a, "Менеджер")
    assert post_trip(manager, legs=[leg_body(c, s2, s3)]).status_code == 201


def test_stop_delete_blocked_via_consignment_api(admin_client, company):
    _, (c,) = make_cargos(company)
    s1, s2, s3 = stops_of(company, c)
    post_trip(admin_client, legs=[leg_body(c, s1, s2), leg_body(c, s2, s3)])
    r = admin_client.patch(
        f"{CONSIGNMENTS}{c.pk}/", {"stops": [{"id": s1.pk}, {"id": s3.pk}]}, format="json"
    )
    assert r.status_code == 400 and "участки" in str(r.data)
    cargo = admin_client.get(f"{CONSIGNMENTS}{c.pk}/").data
    assert len(cargo["stops"]) == 3


def test_trip_list_query_count_stays_flat_with_legs(
    admin_client, company, django_assert_max_num_queries
):
    for _ in range(8):
        _, (c,) = make_cargos(company, stops_per=3)
        s1, s2, s3 = stops_of(company, c)
        post_trip(admin_client, legs=[leg_body(c, s1, s2), leg_body(c, s2, s3)])
    with django_assert_max_num_queries(9):
        r = admin_client.get(TRIPS)
    assert r.status_code == 200 and all(len(t["legs"]) == 2 for t in r.data["results"])
