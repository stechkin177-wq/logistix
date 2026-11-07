import threading
from datetime import datetime, timedelta
from datetime import timezone as dt_tz

import pytest
import time_machine
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.billing.models import Subscription
from apps.core import trash
from apps.core.audit.models import AuditLog
from apps.core.handbooks.models import HandbookValue
from apps.core.models import Membership, Role, User
from apps.core.numbering.models import NumberingRule
from apps.core.tenancy import tenant_context
from apps.forwarding.models import Carrier, Consignment, Trip, TripConsignment
from apps.forwarding.tests.test_orders import (
    CONSIGNMENTS,
    ORDERS,
    _svc_cargo,
    cargo,
    hv,
    make_client,
    make_order,
    new_order,
)
from apps.forwarding.tests.test_parties import client_with_role
from apps.forwarding.trips.services import change_trip_status, create_trip, reassign

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=dt_tz.utc)
TRIPS = "/api/trips/"


@pytest.fixture(autouse=True)
def frozen():
    with time_machine.travel(NOW, tick=False):
        yield


@pytest.fixture
def two(make_company):
    return make_company("Co A"), make_company("Co B")


# --- помощники ---


def make_cargos(company, n=1, **order_extra):
    """Заказ с n грузами: (заказ, [id грузов по возрастанию])."""
    order = make_order(
        company, consignments=[_svc_cargo(name=f"Груз {i}") for i in range(n)], **order_extra
    )
    with tenant_context(company.id):
        ids = list(
            Consignment.objects.filter(order=order).order_by("id").values_list("pk", flat=True)
        )
    return order, ids


def make_carrier(company, name="Перевозчик", **extra):
    with tenant_context(company.id):
        return Carrier.objects.create(name=name, **extra)


def trip_status_id(company, name):
    return hv(company, "trip_status", name).pk


def new_trip(api, ids, **extra):
    r = api.post(TRIPS, {"consignments": ids, **extra}, format="json")
    assert r.status_code == 201, r.content
    return r.data


def trip_url(pk, suffix=""):
    return f"{TRIPS}{pk}/{suffix}"


def svc_create(company, ids, carrier=None, data=None, user=None):
    with tenant_context(company.id):
        user = user or Membership.objects.filter(company=company).first().user
        return create_trip(ids, carrier.pk if carrier else None, data or {}, user)


def counter(company, kind):
    with tenant_context(company.id):
        return NumberingRule.objects.get(kind=kind).next_value


def audit_rows(company, **filters):
    with tenant_context(company.id):
        return list(AuditLog.objects.filter(**filters).order_by("id"))


def trip_count(company):
    with tenant_context(company.id):
        return Trip.all_objects.filter(company=company).count()


# --- нумерация ---


def test_trip_of_one_order_gets_order_number_and_sequence(admin_client, company):
    order, ids = make_cargos(company, 2)
    assert order.number == "ORD-2026-00001"
    first = new_trip(admin_client, [ids[0]])
    assert first["number"] == "ORD-2026-00001-1" and first["is_consolidated"] is False
    second = new_trip(admin_client, [ids[1]])
    assert second["number"] == "ORD-2026-00001-2"
    # рейс с двумя грузами одного заказа считается один раз
    third = new_trip(admin_client, ids)
    assert third["number"] == "ORD-2026-00001-3"


def test_soft_deleted_trips_still_count_for_n(admin_client, company):
    _, ids = make_cargos(company, 1)
    first = new_trip(admin_client, ids)
    second = new_trip(admin_client, ids)
    assert admin_client.delete(trip_url(first["id"])).status_code == 204
    assert second["number"] == "ORD-2026-00001-2"
    third = new_trip(admin_client, ids)
    assert third["number"] == "ORD-2026-00001-3"


def test_other_order_has_own_sequence(admin_client, company):
    _, ids1 = make_cargos(company)
    _, ids2 = make_cargos(company)
    assert new_trip(admin_client, ids1)["number"] == "ORD-2026-00001-1"
    assert new_trip(admin_client, ids2)["number"] == "ORD-2026-00002-1"
    assert new_trip(admin_client, ids1)["number"] == "ORD-2026-00001-2"


def test_trip_with_cargos_of_two_orders_is_consolidated(admin_client, company):
    _, ids1 = make_cargos(company)
    _, ids2 = make_cargos(company)
    first = new_trip(admin_client, ids1 + ids2)
    assert first["number"] == "C1" and first["is_consolidated"] is True
    second = new_trip(admin_client, ids2 + ids1)
    assert second["number"] == "C2" and second["is_consolidated"] is True
    # обычные рейсы счётчик сборных не трогают; сборные рейсы заказа входят в его n
    assert new_trip(admin_client, ids1)["number"] == "ORD-2026-00001-3"
    assert new_trip(admin_client, ids1 + ids2)["number"] == "C3"


def test_cargo_may_be_in_several_trips(admin_client, company):
    _, ids = make_cargos(company)
    new_trip(admin_client, ids)
    new_trip(admin_client, ids)
    assert admin_client.get(CONSIGNMENTS).data["results"][0]["trips_count"] == 2
    with tenant_context(company.id):
        assert TripConsignment.objects.count() == 2


def test_duplicate_ids_in_request_are_collapsed(admin_client, company):
    _, ids = make_cargos(company)
    d = new_trip(admin_client, ids + ids)
    assert [c["id"] for c in d["consignments"]] == ids


# --- проверка грузов при создании ---


def test_foreign_cargo_is_400_and_consumes_no_number(two):
    (comp_a, _, api_a), (comp_b, _, api_b) = two
    _, ids_a = make_cargos(comp_a)
    _, ids_b = make_cargos(comp_b)
    _, ids_a2 = make_cargos(comp_a)
    before_c, before_t = counter(comp_a, "consolidated_trip"), trip_count(comp_a)
    for payload in ([ids_b[0]], ids_a + ids_b, ids_a + ids_a2 + ids_b):
        r = api_a.post(TRIPS, {"consignments": payload}, format="json")
        assert r.status_code == 400, r.content
        assert str(ids_b[0]) in str(r.data["consignments"])
    assert counter(comp_a, "consolidated_trip") == before_c
    assert trip_count(comp_a) == before_t == 0
    assert counter(comp_b, "consolidated_trip") == 1


def test_missing_cargo_id_is_400_naming_ids(admin_client, company):
    _, ids = make_cargos(company)
    r = admin_client.post(TRIPS, {"consignments": [*ids, 999999]}, format="json")
    assert r.status_code == 400 and "999999" in str(r.data["consignments"])
    assert str(ids[0]) not in str(r.data["consignments"])


def test_deleted_cargo_or_deleted_order_cargo_is_400(admin_client, company):
    order1, ids1 = make_cargos(company, 2)
    order2, ids2 = make_cargos(company)
    assert admin_client.delete(f"{CONSIGNMENTS}{ids1[0]}/").status_code == 204
    r = admin_client.post(TRIPS, {"consignments": [ids1[0]]}, format="json")
    assert r.status_code == 400 and str(ids1[0]) in str(r.data["consignments"])
    assert admin_client.delete(f"{ORDERS}{order2.pk}/").status_code == 204
    r = admin_client.post(TRIPS, {"consignments": [ids1[1], ids2[0]]}, format="json")
    assert r.status_code == 400 and str(ids2[0]) in str(r.data["consignments"])
    assert trip_count(company) == 0


@pytest.mark.parametrize("payload", [{}, {"consignments": []}, {"consignments": "1"}])
def test_trip_needs_at_least_one_consignment(admin_client, company, payload):
    r = admin_client.post(TRIPS, payload, format="json")
    assert r.status_code == 400 and "consignments" in r.data


def test_non_numeric_consignment_id_is_400(admin_client):
    r = admin_client.post(TRIPS, {"consignments": ["x"]}, format="json")
    assert r.status_code == 400 and "consignments" in r.data


@pytest.mark.parametrize("field", ["number", "status", "is_consolidated"])
def test_create_rejects_server_fields(admin_client, company, field):
    _, ids = make_cargos(company)
    r = admin_client.post(TRIPS, {"consignments": ids, field: 1}, format="json")
    assert r.status_code == 400 and field in r.data


# --- создание: поля ---


def test_create_with_carrier_and_fields(admin_client, company, admin_user):
    _, ids = make_cargos(company)
    carrier = make_carrier(company, "ТОО Транс")
    usd = hv(company, "currency", code="USD")
    d = new_trip(
        admin_client,
        ids,
        carrier=carrier.pk,
        vehicle_plate="123ABC01",
        driver_name="Иван Иванов",
        price="150000.50",
        currency=usd.pk,
    )
    assert d["carrier"] == carrier.pk and d["carrier_name"] == "ТОО Транс"
    assert (d["vehicle_plate"], d["driver_name"]) == ("123ABC01", "Иван Иванов")
    assert d["price"] == "150000.50" and d["currency"] == usd.pk
    assert d["status_name"] == "Планируется" and d["created_by"] == admin_user.pk
    audit = audit_rows(company, action="create", object_type="forwarding.trip")
    assert len(audit) == 1
    changes = audit[0].changes
    assert changes["driver_name"] == "***" and changes["vehicle_plate"] == [None, "123ABC01"]
    assert changes["consignments"] == [[], ids]
    assert "Иван" not in str(audit[0].changes)


def test_create_defaults(admin_client, company):
    _, ids = make_cargos(company)
    d = new_trip(admin_client, ids)
    assert d["carrier"] is None and d["carrier_name"] is None
    assert d["price"] == "0.00" and d["vehicle_plate"] == "" and d["driver_name"] == ""
    assert hv(company, "currency", pk=d["currency"]).code == "KZT"
    assert hv(company, "trip_status", pk=d["status"]).is_initial


def test_create_output_shape(admin_client, company):
    order1, ids1 = make_cargos(company, 2)
    order2, ids2 = make_cargos(company)
    d = new_trip(admin_client, [ids1[0], ids2[0]])
    assert d["orders"] == [
        {"id": order1.pk, "number": order1.number},
        {"id": order2.pk, "number": order2.number},
    ]
    assert d["consignments"] == [
        {"id": ids1[0], "name": "Груз 0", "order": order1.pk, "order_number": order1.number},
        {"id": ids2[0], "name": "Груз 0", "order": order2.pk, "order_number": order2.number},
    ]
    assert admin_client.get(trip_url(d["id"])).data == d


@pytest.mark.parametrize(
    "extra",
    [{"price": "-1"}, {"price": "abc"}, {"carrier": 999999}, {"currency": 999999}],
)
def test_invalid_fields_are_400_and_create_nothing(admin_client, company, extra):
    _, ids = make_cargos(company)
    r = admin_client.post(TRIPS, {"consignments": ids, **extra}, format="json")
    assert r.status_code == 400
    assert trip_count(company) == 0 and counter(company, "consolidated_trip") == 1


def test_carrier_must_be_active_and_not_deleted(admin_client, company):
    _, ids = make_cargos(company)
    inactive = make_carrier(company, "Н", status=Carrier.INACTIVE)
    deleted = make_carrier(company, "У")
    with tenant_context(company.id):
        deleted.delete()
    for carrier in (inactive, deleted):
        r = admin_client.post(TRIPS, {"consignments": ids, "carrier": carrier.pk}, format="json")
        assert r.status_code == 400 and "carrier" in r.data


def test_currency_must_be_active_currency_value(admin_client, company):
    _, ids = make_cargos(company)
    other = hv(company, "trip_status", "Планируется")
    r = admin_client.post(TRIPS, {"consignments": ids, "currency": other.pk}, format="json")
    assert r.status_code == 400 and "currency" in r.data
    rub = hv(company, "currency", code="RUB")
    with tenant_context(company.id):
        HandbookValue.objects.filter(pk=rub.pk).update(is_active=False)
    r = admin_client.post(TRIPS, {"consignments": ids, "currency": rub.pk}, format="json")
    assert r.status_code == 400 and "currency" in r.data


def test_service_validates_carrier_and_price_itself(company):
    _, ids = make_cargos(company)
    inactive = make_carrier(company, "Н", status=Carrier.INACTIVE)
    with pytest.raises(ValidationError):
        svc_create(company, ids, inactive)
    with pytest.raises(ValidationError):
        svc_create(company, ids, data={"price": -5})
    with pytest.raises(ValidationError):
        svc_create(company, [])
    assert trip_count(company) == 0


def test_db_checks_on_trip(company):
    _, ids = make_cargos(company)
    trip = svc_create(company, ids)
    with tenant_context(company.id), pytest.raises(IntegrityError), transaction.atomic():
        Trip.objects.filter(pk=trip.pk).update(carrier_price=-1)
    with tenant_context(company.id), pytest.raises(IntegrityError), transaction.atomic():
        Trip(company=company, number=trip.number, currency=trip.currency, status=trip.status).save()


def test_trip_cargo_link_is_unique(company):
    _, ids = make_cargos(company)
    trip = svc_create(company, ids)
    with tenant_context(company.id), pytest.raises(IntegrityError), transaction.atomic():
        TripConsignment(trip=trip, consignment_id=ids[0]).save()


def test_number_conflict_is_409_and_rolls_back(admin_client, company):
    _, ids1 = make_cargos(company)
    _, ids2 = make_cargos(company)
    new_trip(admin_client, ids1 + ids2)  # C1
    with tenant_context(company.id):
        NumberingRule.objects.filter(kind="consolidated_trip").update(next_value=1)
    before = trip_count(company)
    r = admin_client.post(TRIPS, {"consignments": ids1 + ids2}, format="json")
    assert r.status_code == 409 and r.data["code"] == "number_conflict"
    assert trip_count(company) == before and counter(company, "consolidated_trip") == 1


# --- очередь распределения и trips_count ---


def test_without_trip_queue_lifecycle(admin_client, company):
    _, ids = make_cargos(company, 2)

    def queue():
        r = admin_client.get(CONSIGNMENTS, {"without_trip": "1"})
        assert r.status_code == 200
        return sorted(c["id"] for c in r.data["results"])

    assert queue() == ids
    trip = new_trip(admin_client, [ids[0]])
    assert queue() == [ids[1]]
    assert admin_client.delete(trip_url(trip["id"])).status_code == 204
    assert queue() == ids
    assert admin_client.post(f"/api/trash/trips/{trip['id']}/restore/").status_code == 200
    assert queue() == [ids[1]]
    assert admin_client.get(CONSIGNMENTS).data["count"] == 2  # без фильтра - все


def test_without_trip_zero_and_bad_values(admin_client, company):
    _, ids = make_cargos(company)
    new_trip(admin_client, ids)
    assert admin_client.get(CONSIGNMENTS, {"without_trip": "0"}).data["count"] == 1
    assert admin_client.get(CONSIGNMENTS, {"without_trip": "1"}).data["count"] == 0
    assert admin_client.get(CONSIGNMENTS, {"without_trip": "x"}).status_code == 400


def test_trips_count_ignores_deleted_trips(admin_client, company):
    _, ids = make_cargos(company)
    t1 = new_trip(admin_client, ids)
    new_trip(admin_client, ids)
    url = f"{CONSIGNMENTS}{ids[0]}/"
    assert admin_client.get(url).data["trips_count"] == 2
    admin_client.delete(trip_url(t1["id"]))
    assert admin_client.get(url).data["trips_count"] == 1
    assert admin_client.get(CONSIGNMENTS).data["results"][0]["trips_count"] == 1


def test_trips_count_in_create_and_patch_responses(admin_client, company):
    order = new_order(admin_client, make_client(company))
    r = admin_client.post(CONSIGNMENTS, {**cargo(), "order": order["id"]}, format="json")
    assert r.status_code == 201 and r.data["trips_count"] == 0
    new_trip(admin_client, [r.data["id"]])
    r = admin_client.patch(f"{CONSIGNMENTS}{r.data['id']}/", {"name": "Н"}, format="json")
    assert r.status_code == 200 and r.data["trips_count"] == 1


def test_without_trip_queue_isolated_between_companies(two):
    (comp_a, _, api_a), (comp_b, _, api_b) = two
    make_cargos(comp_a)
    assert api_a.get(CONSIGNMENTS, {"without_trip": "1"}).data["count"] == 1
    assert api_b.get(CONSIGNMENTS, {"without_trip": "1"}).data["count"] == 0


# --- has_carrier у заказа ---


def has_carrier(api, order_id):
    return api.get(f"{ORDERS}{order_id}/").data["has_carrier"]


def test_has_carrier_after_trip_with_carrier(admin_client, company):
    order, ids = make_cargos(company, 2)
    assert has_carrier(admin_client, order.pk) is False
    # рейс без перевозчика не считается
    t1 = new_trip(admin_client, [ids[0]])
    assert has_carrier(admin_client, order.pk) is False
    carrier = make_carrier(company)
    t2 = new_trip(admin_client, [ids[1]], carrier=carrier.pk)
    assert has_carrier(admin_client, order.pk) is True
    listed = admin_client.get(ORDERS).data["results"][0]
    assert listed["has_carrier"] is True
    # мягко удалённый рейс не считается
    admin_client.delete(trip_url(t2["id"]))
    assert has_carrier(admin_client, order.pk) is False
    # назначили перевозчика через PATCH
    r = admin_client.patch(trip_url(t1["id"]), {"carrier": carrier.pk}, format="json")
    assert r.status_code == 200 and has_carrier(admin_client, order.pk) is True
    r = admin_client.patch(trip_url(t1["id"]), {"carrier": None}, format="json")
    assert r.status_code == 200 and has_carrier(admin_client, order.pk) is False


def test_has_carrier_for_consolidated_trip_covers_all_orders(admin_client, company):
    order1, ids1 = make_cargos(company)
    order2, ids2 = make_cargos(company)
    order3, _ = make_cargos(company)
    carrier = make_carrier(company)
    new_trip(admin_client, ids1 + ids2, carrier=carrier.pk)
    assert has_carrier(admin_client, order1.pk) and has_carrier(admin_client, order2.pk)
    assert has_carrier(admin_client, order3.pk) is False


def test_has_carrier_ignores_deleted_cargo(admin_client, company):
    order, ids = make_cargos(company, 2)
    carrier = make_carrier(company)
    new_trip(admin_client, [ids[0]], carrier=carrier.pk)
    assert has_carrier(admin_client, order.pk) is True
    admin_client.delete(f"{CONSIGNMENTS}{ids[0]}/")
    assert has_carrier(admin_client, order.pk) is False


def test_has_carrier_in_order_create_response(admin_client, company):
    d = new_order(admin_client, make_client(company), consignments=[cargo()])
    assert d["has_carrier"] is False


# --- reassign ---


def reassign_url(pk):
    return trip_url(pk, "reassign/")


def test_reassign_single_order_trip_to_two_orders_keeps_number(admin_client, company):
    _, ids1 = make_cargos(company)
    _, ids2 = make_cargos(company)
    trip = new_trip(admin_client, ids1)
    assert trip["number"] == "ORD-2026-00001-1"
    r = admin_client.post(reassign_url(trip["id"]), {"consignment_ids": ids1 + ids2}, format="json")
    assert r.status_code == 200, r.content
    assert r.data["is_consolidated"] is True and r.data["number"] == "ORD-2026-00001-1"
    assert [c["id"] for c in r.data["consignments"]] == ids1 + ids2
    assert len(r.data["orders"]) == 2
    # и обратно: номер прежний, флаг снят
    r = admin_client.post(reassign_url(trip["id"]), {"consignment_ids": ids2}, format="json")
    assert r.status_code == 200
    assert r.data["is_consolidated"] is False and r.data["number"] == "ORD-2026-00001-1"
    assert [c["id"] for c in r.data["consignments"]] == ids2
    assert counter(company, "consolidated_trip") == 1


def test_reassign_audits_old_and_new_ids(admin_client, company):
    _, ids = make_cargos(company, 3)
    trip = new_trip(admin_client, ids[:2])
    admin_client.post(reassign_url(trip["id"]), {"consignment_ids": ids[1:]}, format="json")
    row = audit_rows(company, action="update", object_type="forwarding.trip")[-1]
    assert row.changes == {"consignments": [ids[:2], ids[1:]]}


def test_reassign_same_set_writes_no_audit(admin_client, company):
    _, ids = make_cargos(company, 2)
    trip = new_trip(admin_client, ids)
    r = admin_client.post(reassign_url(trip["id"]), {"consignment_ids": ids[::-1]}, format="json")
    assert r.status_code == 200
    assert audit_rows(company, action="update", object_type="forwarding.trip") == []


@pytest.mark.parametrize("payload", [{}, {"consignment_ids": []}, {"consignment_ids": "x"}])
def test_reassign_empty_is_400_and_unchanged(admin_client, company, payload):
    _, ids = make_cargos(company)
    trip = new_trip(admin_client, ids)
    r = admin_client.post(reassign_url(trip["id"]), payload, format="json")
    assert r.status_code == 400 and "consignment_ids" in r.data
    assert admin_client.get(trip_url(trip["id"])).data["consignments"][0]["id"] == ids[0]


def test_reassign_with_foreign_or_deleted_cargo_is_400_and_unchanged(two):
    (comp_a, _, api_a), (comp_b, _, _) = two
    _, ids = make_cargos(comp_a, 2)
    _, ids_b = make_cargos(comp_b)
    trip = new_trip(api_a, [ids[0]])
    api_a.delete(f"{CONSIGNMENTS}{ids[1]}/")
    for bad in (ids_b, [ids[0], *ids_b], [ids[1]], [999999]):
        r = api_a.post(reassign_url(trip["id"]), {"consignment_ids": bad}, format="json")
        assert r.status_code == 400, bad
    got = api_a.get(trip_url(trip["id"])).data
    assert [c["id"] for c in got["consignments"]] == [ids[0]]


def test_number_after_reassign_away_does_not_collide(admin_client, company):
    """Рейс №1 заказа ушёл в другой заказ: число рейсов заказа уменьшилось, но номер -1 занят."""
    _, ids1 = make_cargos(company)
    _, ids2 = make_cargos(company)
    trip = new_trip(admin_client, ids1)
    admin_client.post(reassign_url(trip["id"]), {"consignment_ids": ids2}, format="json")
    again = new_trip(admin_client, ids1)
    assert again["number"] == "ORD-2026-00001-2"


def test_reassign_unknown_or_deleted_trip_is_404(admin_client, company):
    _, ids = make_cargos(company)
    trip = new_trip(admin_client, ids)
    admin_client.delete(trip_url(trip["id"]))
    for pk in (trip["id"], 999999):
        r = admin_client.post(reassign_url(pk), {"consignment_ids": ids}, format="json")
        assert r.status_code == 404


def test_reassign_service_directly(company):
    _, ids1 = make_cargos(company)
    _, ids2 = make_cargos(company)
    trip = svc_create(company, ids1)
    with tenant_context(company.id):
        user = Membership.objects.filter(company=company).first().user
        out = reassign(trip, ids1 + ids2, user)
        assert out.is_consolidated and out.number == trip.number
        with pytest.raises(ValidationError):
            reassign(out, [], user)
        assert TripConsignment.objects.filter(trip=out).count() == 2


# --- статус ---


def status_url(pk):
    return trip_url(pk, "status/")


def test_status_change_and_audit(admin_client, company):
    _, ids = make_cargos(company)
    trip = new_trip(admin_client, ids)
    on_way = trip_status_id(company, "В пути")
    r = admin_client.post(status_url(trip["id"]), {"status": on_way}, format="json")
    assert r.status_code == 200, r.content
    assert r.data["status"] == on_way and r.data["status_name"] == "В пути"
    row = audit_rows(company, action="update", object_type="forwarding.trip")[-1]
    assert row.changes["status_id"] == [trip["status"], on_way]


def test_same_status_is_400(admin_client, company):
    _, ids = make_cargos(company)
    trip = new_trip(admin_client, ids)
    r = admin_client.post(status_url(trip["id"]), {"status": trip["status"]}, format="json")
    assert r.status_code == 400 and "status" in r.data


def test_status_value_validation(two):
    (comp_a, _, api_a), (comp_b, _, _) = two
    _, ids = make_cargos(comp_a)
    trip = new_trip(api_a, ids)
    foreign = trip_status_id(comp_b, "В пути")
    wrong_handbook = hv(comp_a, "order_status", "В работе").pk
    inactive = hv(comp_a, "trip_status", "Выгрузка")
    with tenant_context(comp_a.id):
        HandbookValue.objects.filter(pk=inactive.pk).update(is_active=False)
    for bad in (foreign, wrong_handbook, inactive.pk, 999999, "x", None):
        r = api_a.post(status_url(trip["id"]), {"status": bad}, format="json")
        assert r.status_code == 400, bad
    assert api_a.get(trip_url(trip["id"])).data["status"] == trip["status"]


def test_status_service_validates_itself(company):
    _, ids = make_cargos(company)
    trip = svc_create(company, ids)
    with tenant_context(company.id):
        user = Membership.objects.filter(company=company).first().user
        order_status = hv(company, "order_status", "В работе")
        with pytest.raises(ValidationError):
            change_trip_status(trip, order_status, user)
        with pytest.raises(ValidationError):
            change_trip_status(trip, trip.status, user)


def test_status_unknown_trip_404(admin_client):
    assert admin_client.post(status_url(999999), {"status": 1}, format="json").status_code == 404


# --- PATCH ---


def test_patch_updates_allowed_fields_and_audits(admin_client, company):
    _, ids = make_cargos(company)
    trip = new_trip(admin_client, ids, driver_name="Старый")
    carrier = make_carrier(company, "Новый перевозчик")
    eur = hv(company, "currency", code="EUR").pk
    r = admin_client.patch(
        trip_url(trip["id"]),
        {
            "carrier": carrier.pk,
            "vehicle_plate": "777AAA02",
            "driver_name": "Пётр Секретов",
            "price": "999.90",
            "currency": eur,
        },
        format="json",
    )
    assert r.status_code == 200, r.content
    assert r.data["carrier_name"] == "Новый перевозчик" and r.data["price"] == "999.90"
    assert r.data["number"] == trip["number"]
    row = audit_rows(company, action="update", object_type="forwarding.trip")[-1]
    assert row.changes["driver_name"] == "***"
    assert row.changes["vehicle_plate"] == ["", "777AAA02"]
    assert "price" not in row.changes  # новые записи аудита пишут carrier_price
    assert row.changes["carrier_price"] == ["0.00", "999.90"] or row.changes["carrier_price"][
        1
    ] in (
        "999.90",
        "999.9",
    )
    assert "Секретов" not in str(row.changes) and "Старый" not in str(row.changes)


@pytest.mark.parametrize(
    "field,value",
    [
        ("consignments", [1]),
        ("status", 1),
        ("number", "X-1"),
        ("is_consolidated", True),
    ],
)
def test_patch_rejects_server_fields(admin_client, company, field, value):
    _, ids = make_cargos(company)
    trip = new_trip(admin_client, ids)
    r = admin_client.patch(trip_url(trip["id"]), {field: value}, format="json")
    assert r.status_code == 400 and field in r.data
    after = admin_client.get(trip_url(trip["id"])).data
    assert after["number"] == trip["number"] and after["status"] == trip["status"]


def test_patch_validation(admin_client, company):
    _, ids = make_cargos(company)
    trip = new_trip(admin_client, ids)
    inactive = make_carrier(company, "Н", status=Carrier.INACTIVE)
    for body in (
        {"price": "-1"},
        {"carrier": inactive.pk},
        {"carrier": 999999},
        {"currency": None},
        {"currency": 999999},
    ):
        assert admin_client.patch(trip_url(trip["id"]), body, format="json").status_code == 400, (
            body
        )


def test_patch_keeps_unchanged_inactive_carrier(admin_client, company):
    _, ids = make_cargos(company)
    carrier = make_carrier(company)
    trip = new_trip(admin_client, ids, carrier=carrier.pk)
    with tenant_context(company.id):
        Carrier.objects.filter(pk=carrier.pk).update(status=Carrier.INACTIVE)
    r = admin_client.patch(
        trip_url(trip["id"]), {"carrier": carrier.pk, "vehicle_plate": "1"}, format="json"
    )
    assert r.status_code == 200


def test_patch_without_changes_writes_no_audit(admin_client, company):
    _, ids = make_cargos(company)
    trip = new_trip(admin_client, ids)
    admin_client.patch(trip_url(trip["id"]), {"vehicle_plate": ""}, format="json")
    assert audit_rows(company, action="update", object_type="forwarding.trip") == []


# --- список ---


def test_list_default_order_pagination_and_filters(admin_client, company):
    _, ids = make_cargos(company, 3)
    _, ids_c = make_cargos(company)
    carrier = make_carrier(company, "Карго Плюс")
    created = []
    for i, cid in enumerate(ids):
        with time_machine.travel(NOW + timedelta(seconds=10 * i), tick=False):
            created.append(new_trip(admin_client, [cid], carrier=carrier.pk if i == 0 else None))
    with time_machine.travel(NOW + timedelta(seconds=60), tick=False):
        cons = new_trip(admin_client, [ids[0], ids_c[0]])
    r = admin_client.get(TRIPS)
    assert r.status_code == 200 and r.data["count"] == 4
    assert [t["id"] for t in r.data["results"]] == [cons["id"], *[t["id"] for t in created[::-1]]]
    assert admin_client.get(TRIPS, {"only_consolidated": "1"}).data["count"] == 1
    assert admin_client.get(TRIPS, {"only_consolidated": "0"}).data["count"] == 4
    assert admin_client.get(TRIPS, {"carrier": carrier.pk}).data["count"] == 1
    on_way = trip_status_id(company, "В пути")
    admin_client.post(status_url(created[1]["id"]), {"status": on_way}, format="json")
    got = admin_client.get(TRIPS, {"status": on_way}).data
    assert [t["id"] for t in got["results"]] == [created[1]["id"]]
    for q, expected in (
        ("карго", 1),
        ("ORD-2026-00001-2", 1),
        ("c1", 1),
        ("Груз 0", 2),  # по названию груза; рейс с двумя «Груз 0» не дублируется
        ("нет такого", 0),
    ):
        assert admin_client.get(TRIPS, {"q": q}).data["count"] == expected, q
    assert admin_client.get(TRIPS, {"status": "x"}).status_code == 400
    assert admin_client.get(TRIPS, {"carrier": "x"}).status_code == 400
    assert admin_client.get(TRIPS, {"only_consolidated": "x"}).status_code == 400


# верхняя граница запросов списка рейсов: аутентификация и подписка, count, рейсы (с
# перевозчиком и статусом), одним запросом грузы с заказами = 5 измеренных запросов, остальное
# запас; число запросов не зависит от числа рейсов и грузов
TRIP_LIST_QUERY_BOUND = 8


def test_list_query_count_is_flat(admin_client, company, django_assert_max_num_queries):
    carrier = make_carrier(company, "Перевозчик")
    for _ in range(25):
        _, ids = make_cargos(company, 2)
        svc_create(company, ids, carrier)
    with django_assert_max_num_queries(TRIP_LIST_QUERY_BOUND):
        r = admin_client.get(TRIPS, {"q": "Груз"})
    assert r.status_code == 200 and len(r.data["results"]) == 25
    for t in r.data["results"]:
        assert len(t["consignments"]) == 2 and len(t["orders"]) == 1
        assert t["carrier_name"] == "Перевозчик" and t["status_name"] == "Планируется"


def test_detail_query_count_is_flat(admin_client, company, django_assert_max_num_queries):
    _, ids = make_cargos(company, 6)
    trip = svc_create(company, ids)
    with django_assert_max_num_queries(TRIP_LIST_QUERY_BOUND):
        r = admin_client.get(trip_url(trip.pk))
    assert r.status_code == 200 and len(r.data["consignments"]) == 6


def test_consignment_list_query_count_with_trips_count(
    admin_client, company, django_assert_max_num_queries
):
    for _ in range(10):
        _, ids = make_cargos(company, 2)
        svc_create(company, ids)
    with django_assert_max_num_queries(10):
        r = admin_client.get(CONSIGNMENTS, {"without_trip": "0"})
    assert r.status_code == 200 and len(r.data["results"]) == 20


# --- мягкое удаление, корзина ---


def test_trash_registered():
    assert trash.registered()["trips"] == (Trip, "trips.view")


def test_delete_is_soft_restorable_and_keeps_links(admin_client, company):
    _, ids = make_cargos(company)
    trip = new_trip(admin_client, ids)
    url = trip_url(trip["id"])
    assert admin_client.delete(url).status_code == 204
    assert admin_client.get(url).status_code == 404
    assert admin_client.get(TRIPS).data["count"] == 0
    with tenant_context(company.id):
        assert Trip.trash.filter(pk=trip["id"]).exists()
        assert TripConsignment.objects.filter(trip_id=trip["id"]).count() == 1
        assert Consignment.objects.filter(pk=ids[0]).exists()
    item = admin_client.get("/api/trash/").data["results"][0]
    assert (item["code"], item["id"], item["label"]) == ("trips", trip["id"], trip["number"])
    r = admin_client.post(f"/api/trash/trips/{trip['id']}/restore/")
    assert r.status_code == 200, r.content
    assert admin_client.get(url).data["consignments"][0]["id"] == ids[0]
    assert len(audit_rows(company, action="delete", object_type="forwarding.trip")) == 1
    assert len(audit_rows(company, action="restore", object_type="forwarding.trip")) == 1


def test_numbers_not_reused_after_delete_and_restore(admin_client, company):
    _, ids1 = make_cargos(company)
    _, ids2 = make_cargos(company)
    a = new_trip(admin_client, ids1 + ids2)
    admin_client.delete(trip_url(a["id"]))
    assert new_trip(admin_client, ids1 + ids2)["number"] == "C2"
    assert admin_client.post(f"/api/trash/trips/{a['id']}/restore/").status_code == 200


def test_restore_blocked_when_all_cargos_deleted(admin_client, company):
    _, ids = make_cargos(company, 2)
    trip = new_trip(admin_client, ids)
    admin_client.delete(trip_url(trip["id"]))
    for cid in ids:
        assert admin_client.delete(f"{CONSIGNMENTS}{cid}/").status_code == 204
    r = admin_client.post(f"/api/trash/trips/{trip['id']}/restore/")
    assert r.status_code == 409 and "груз" in r.data["detail"].lower()
    with tenant_context(company.id):
        assert Trip.trash.filter(pk=trip["id"]).exists()
    # хотя бы один груз вернули - можно
    assert admin_client.post(f"/api/trash/consignments/{ids[0]}/restore/").status_code == 200
    assert admin_client.post(f"/api/trash/trips/{trip['id']}/restore/").status_code == 200
    assert [c["id"] for c in admin_client.get(trip_url(trip["id"])).data["consignments"]] == [
        ids[0]
    ]


def test_restore_blocked_when_orders_of_all_cargos_deleted(admin_client, company):
    order, ids = make_cargos(company)
    trip = new_trip(admin_client, ids)
    admin_client.delete(trip_url(trip["id"]))
    admin_client.delete(f"{ORDERS}{order.pk}/")
    assert admin_client.post(f"/api/trash/trips/{trip['id']}/restore/").status_code == 409


def test_deleted_cargo_disappears_from_active_trip(admin_client, company):
    order1, ids1 = make_cargos(company, 2)
    order2, ids2 = make_cargos(company)
    trip = new_trip(admin_client, [*ids1, *ids2])
    admin_client.delete(f"{CONSIGNMENTS}{ids2[0]}/")
    got = admin_client.get(trip_url(trip["id"])).data
    assert [c["id"] for c in got["consignments"]] == ids1
    assert [o["id"] for o in got["orders"]] == [order1.pk]
    # то же при удалении заказа
    admin_client.delete(f"{ORDERS}{order1.pk}/")
    got = admin_client.get(trip_url(trip["id"])).data
    assert got["consignments"] == [] and got["orders"] == []
    assert admin_client.get(TRIPS).data["results"][0]["consignments"] == []
    # restore заказа возвращает грузы в рейс
    admin_client.post(f"/api/trash/orders/{order1.pk}/restore/")
    assert len(admin_client.get(trip_url(trip["id"])).data["consignments"]) == 2


def test_trash_listing_hidden_without_trips_view(company, admin_client):
    _, ids = make_cargos(company)
    trip = new_trip(admin_client, ids)
    admin_client.delete(trip_url(trip["id"]))
    with tenant_context(company.id):
        role = Role.objects.get(name="Механик")
    user = User.objects.create_user(email="mech-trash@x.kz", password="x")
    Membership.objects.create(user=user, company=company, role=role)
    from apps.core.api.auth import issue_tokens

    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    assert api.get("/api/trash/").status_code == 403  # нет trash.view


# --- изоляция компаний ---


def test_trips_isolation_between_companies(two):
    (comp_a, _, api_a), (comp_b, _, api_b) = two
    _, ids_a = make_cargos(comp_a)
    carrier_a = make_carrier(comp_a, "Секретный перевозчик")
    trip = new_trip(api_a, ids_a, carrier=carrier_a.pk, vehicle_plate="СЕКРЕТ")
    url = trip_url(trip["id"])
    assert api_a.get(url).status_code == 200
    assert api_b.get(url).status_code == 404
    assert api_b.patch(url, {"vehicle_plate": "hack"}, format="json").status_code == 404
    assert api_b.put(url, {"vehicle_plate": "hack"}, format="json").status_code == 404
    assert api_b.delete(url).status_code == 404
    _, ids_b = make_cargos(comp_b)
    r = api_b.post(reassign_url(trip["id"]), {"consignment_ids": ids_b}, format="json")
    assert r.status_code == 404
    on_way = trip_status_id(comp_b, "В пути")
    assert api_b.post(status_url(trip["id"]), {"status": on_way}, format="json").status_code == 404
    assert api_b.get(TRIPS).data["count"] == 0
    for params in (
        {"q": "Секретный"},
        {"q": "СЕКРЕТ"},
        {"q": "ORD"},
        {"q": "Груз"},
        {"carrier": carrier_a.pk},
        {"status": trip["status"]},
        {"only_consolidated": "1"},
    ):
        assert api_b.get(TRIPS, params).data["count"] == 0, params
    assert "Секретный" not in api_b.get(TRIPS).content.decode()
    # данные A не изменились
    got = api_a.get(url).data
    assert got["vehicle_plate"] == "СЕКРЕТ" and got["status"] == trip["status"]
    assert [c["id"] for c in got["consignments"]] == ids_a
    # корзина
    api_a.delete(url)
    assert api_b.get("/api/trash/").data["results"] == []
    assert api_b.post(f"/api/trash/trips/{trip['id']}/restore/").status_code == 404
    with tenant_context(comp_a.id):
        assert Trip.trash.filter(pk=trip["id"]).exists()


def test_create_with_foreign_references_is_400(two):
    (comp_a, _, api_a), (comp_b, _, api_b) = two
    _, ids_a = make_cargos(comp_a)
    _, ids_b = make_cargos(comp_b)
    carrier_a = make_carrier(comp_a)
    assert api_b.post(TRIPS, {"consignments": ids_a}, format="json").status_code == 400
    r = api_b.post(TRIPS, {"consignments": ids_b, "carrier": carrier_a.pk}, format="json")
    assert r.status_code == 400 and "carrier" in r.data
    foreign_currency = hv(comp_a, "currency", code="KZT").pk
    r = api_b.post(TRIPS, {"consignments": ids_b, "currency": foreign_currency}, format="json")
    assert r.status_code == 400
    assert trip_count(comp_a) == 0 and trip_count(comp_b) == 0
    # у компании B своя нумерация
    assert new_trip(api_b, ids_b)["number"] == "ORD-2026-00001-1"


def test_service_rejects_foreign_cargo_without_context_leak(two):
    (comp_a, _, _), (comp_b, _, _) = two
    _, ids_a = make_cargos(comp_a)
    with pytest.raises(ValidationError):
        svc_create(comp_b, ids_a)
    assert trip_count(comp_b) == 0


# --- права, модули, подписка ---


def test_manager_and_dispatcher_create_update_but_not_delete(company):
    _, ids = make_cargos(company, 3)
    for i, role in enumerate(("Менеджер", "Диспетчер")):
        _, api = client_with_role(company, role)
        r = api.post(TRIPS, {"consignments": [ids[i]]}, format="json")
        assert r.status_code == 201, role
        url = trip_url(r.data["id"])
        assert api.get(url).status_code == 200
        assert api.patch(url, {"vehicle_plate": "1"}, format="json").status_code == 200
        r2 = api.post(reassign_url(r.data["id"]), {"consignment_ids": [ids[2]]}, format="json")
        assert r2.status_code == 200
        on_way = trip_status_id(company, "В пути")
        assert (
            api.post(status_url(r.data["id"]), {"status": on_way}, format="json").status_code == 200
        )
        assert api.delete(url).status_code == 403


@pytest.mark.parametrize("role", ["Механик", "Наблюдатель", "Бухгалтер"])
def test_read_only_roles(company, role):
    _, ids = make_cargos(company)
    trip = svc_create(company, ids)
    _, api = client_with_role(company, role)
    url = trip_url(trip.pk)
    assert api.get(TRIPS).status_code == 200 and api.get(url).status_code == 200
    assert api.post(TRIPS, {"consignments": ids}, format="json").status_code == 403
    assert api.patch(url, {"vehicle_plate": "x"}, format="json").status_code == 403
    assert api.delete(url).status_code == 403
    assert (
        api.post(reassign_url(trip.pk), {"consignment_ids": ids}, format="json").status_code == 403
    )
    on_way = trip_status_id(company, "В пути")
    assert api.post(status_url(trip.pk), {"status": on_way}, format="json").status_code == 403


def test_driver_without_permissions_gets_403(company):
    _, api = client_with_role(company, "Водитель")
    assert api.get(TRIPS).status_code == 403


def test_unauthenticated_is_401():
    assert APIClient().get(TRIPS).status_code in (401, 403)


def test_module_disabled(make_company):
    _, _, api = make_company("Fleet only", modules=["fleet"])
    for method, url, body in (
        ("get", TRIPS, None),
        ("post", TRIPS, {"consignments": [1]}),
        ("post", reassign_url(1), {"consignment_ids": [1]}),
        ("post", status_url(1), {"status": 1}),
        ("get", trip_url(1), None),
    ):
        r = getattr(api, method)(url, body, format="json") if body else getattr(api, method)(url)
        assert r.status_code == 403 and r.data["code"] == "module_disabled", url


def test_readonly_subscription_blocks_writes_but_not_reads(company, admin_client):
    _, ids = make_cargos(company, 2)
    trip = new_trip(admin_client, [ids[0]])
    Subscription.objects.filter(company=company).update(ends_at=timezone.now() - timedelta(days=20))
    assert admin_client.get(TRIPS).status_code == 200
    on_way = trip_status_id(company, "В пути")
    attempts = (
        admin_client.post(TRIPS, {"consignments": ids}, format="json"),
        admin_client.patch(trip_url(trip["id"]), {"vehicle_plate": "y"}, format="json"),
        admin_client.post(reassign_url(trip["id"]), {"consignment_ids": ids}, format="json"),
        admin_client.post(status_url(trip["id"]), {"status": on_way}, format="json"),
        admin_client.delete(trip_url(trip["id"])),
    )
    for r in attempts:
        assert r.status_code == 403 and r.data["code"] == "subscription_readonly"


def test_blocked_subscription_blocks_reads(company, admin_client):
    Subscription.objects.filter(company=company).update(status=Subscription.BLOCKED)
    r = admin_client.get(TRIPS)
    assert r.status_code == 403 and r.data["code"] == "subscription_blocked"


# --- аудит ---


def test_delete_audit_masks_driver(admin_client, company):
    _, ids = make_cargos(company)
    trip = new_trip(admin_client, ids, driver_name="Имя Водителя", vehicle_plate="999ZZZ")
    admin_client.delete(trip_url(trip["id"]))
    row = audit_rows(company, action="delete", object_type="forwarding.trip")[0]
    assert row.changes["driver_name"] == "***" and "Водителя" not in str(row.changes)
    assert row.changes["vehicle_plate"] == ["999ZZZ", None]


# --- RLS ---


def test_rls_guard_covers_trip_tables():
    from apps.core import rls

    tables = ["forwarding_trip", "forwarding_tripconsignment"]
    assert set(tables) <= set(rls.tenant_tables())
    assert rls.tables_missing_rls(tables) == []


def test_trip_flows_work_under_app_role(db, api_client):
    from apps.core.services import create_company_with_defaults
    from apps.core.tests.test_rls import app_role, raw
    from conftest import TEST_PASSWORD

    with app_role():
        admin = User.objects.create_user(email="rls-trip@x.kz", password=TEST_PASSWORD)
        company = create_company_with_defaults("RLS Trip", admin, ["forwarding"])
        other = User.objects.create_user(email="rls-trip2@x.kz", password=TEST_PASSWORD)
        create_company_with_defaults("RLS Trip 2", other, ["forwarding"])
        resp = api_client.post(
            "/api/auth/login/", {"login": "rls-trip@x.kz", "password": TEST_PASSWORD}
        )
        assert resp.status_code == 200, resp.content
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
        cl = api_client.post("/api/clients/", {"name": "ТОО Тест"}, format="json")
        carrier = api_client.post("/api/carriers/", {"name": "Перевозчик"}, format="json")
        assert cl.status_code == 201 and carrier.status_code == 201
        ids = []
        for _ in range(2):
            o = api_client.post(
                ORDERS, {"client": cl.data["id"], "consignments": [cargo()]}, format="json"
            )
            assert o.status_code == 201, o.content
            ids.append(o.data["consignments"][0]["id"])
        created = api_client.post(
            TRIPS, {"consignments": [ids[0]], "carrier": carrier.data["id"]}, format="json"
        )
        assert created.status_code == 201, created.content
        assert created.data["number"] == "ORD-2026-00001-1"
        tid = created.data["id"]
        r = api_client.post(reassign_url(tid), {"consignment_ids": ids}, format="json")
        assert r.status_code == 200 and r.data["is_consolidated"] is True, r.content
        assert r.data["number"] == "ORD-2026-00001-1"
        on_way = trip_status_id(company, "В пути")
        r = api_client.post(status_url(tid), {"status": on_way}, format="json")
        assert r.status_code == 200, r.content
        assert api_client.get(CONSIGNMENTS, {"without_trip": "1"}).data["count"] == 0
        assert api_client.get(f"{ORDERS}{o.data['id']}/").data["has_carrier"] is True
        cons = api_client.post(TRIPS, {"consignments": ids}, format="json")
        assert cons.status_code == 201 and cons.data["number"] == "C1", cons.content
        assert api_client.delete(trip_url(tid)).status_code == 204
        assert api_client.get("/api/trash/").data["count"] == 1
        restored = api_client.post(f"/api/trash/trips/{tid}/restore/")
        assert restored.status_code == 200, restored.content
        assert api_client.get(trip_url(tid)).status_code == 200
        for table in ("trip", "tripconsignment"):
            assert raw(f"SELECT count(*) FROM forwarding_{table}")[0][0] == 0, table


# --- параллелизм ---


def _run_trip_threads(company, user_id, jobs, workers):
    """jobs - списки id грузов; каждый поток берёт следующее задание и создаёт рейс."""
    results, errors = [], []
    lock = threading.Lock()
    queue = iter(jobs)

    def worker():
        try:
            while True:
                with lock:
                    try:
                        ids = next(queue)
                    except StopIteration:
                        return
                with tenant_context(company.id):
                    trip = create_trip(ids, None, {}, User.objects.get(pk=user_id))
                with lock:
                    results.append(trip.number)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    return results


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_trips_of_same_order_get_distinct_gap_free_n(make_company):
    company, admin, _ = make_company("ConcTripsSame")
    order, ids = make_cargos(company, 2)
    results = _run_trip_threads(company, admin.pk, [[ids[0]], [ids[1]]], 2)
    assert sorted(results) == [f"{order.number}-1", f"{order.number}-2"]
    results += _run_trip_threads(company, admin.pk, [[ids[i % 2]] for i in range(6)], 3)
    assert sorted(results) == sorted(f"{order.number}-{n}" for n in range(1, 9))
    with tenant_context(company.id):
        assert Trip.objects.count() == 8


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_consolidated_trips_get_distinct_gap_free_numbers(make_company):
    company, admin, _ = make_company("ConcTripsCons")
    _, ids1 = make_cargos(company)
    _, ids2 = make_cargos(company)
    results = _run_trip_threads(company, admin.pk, [ids1 + ids2 for _ in range(6)], 3)
    assert sorted(results) == sorted(f"C{i}" for i in range(1, 7))
    assert counter(company, "consolidated_trip") == 7


# --- порядок блокировок и взаимоблокировки ---


def test_locking_query_is_ordered_by_pk(company):
    from apps.forwarding.trips.services import locked_consignments_qs

    with tenant_context(company.id):
        qs = locked_consignments_qs([5, 3, 9])
    assert qs.query.order_by == ("pk",)
    assert qs.query.select_for_update and 'ORDER BY "forwarding_consignment"."id"' in str(qs.query)


def _race(company, user_id, jobs):
    """jobs - вызываемые (user) -> результат; запускаются одновременно, возвращают ошибки."""
    errors = []
    barrier = threading.Barrier(len(jobs))

    def worker(job):
        try:
            with tenant_context(company.id):
                barrier.wait(timeout=10)
                job(User.objects.get(pk=user_id))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(j,)) for j in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_overlapping_cargo_sets_in_opposite_order_do_not_deadlock(make_company):
    company, admin, _ = make_company("DeadlockCo")
    _, ids1 = make_cargos(company, 2)
    _, ids2 = make_cargos(company, 2)
    cargos = [ids1[0], ids2[0], ids1[1], ids2[1]]
    with tenant_context(company.id):
        base = create_trip([cargos[0]], None, {}, User.objects.get(pk=admin.pk))
    for _ in range(5):
        errors = _race(
            company,
            admin.pk,
            [
                lambda u: create_trip(cargos, None, {}, u),
                lambda u: create_trip(cargos[::-1], None, {}, u),
                lambda u: reassign(base, cargos[::-1], u),
                lambda u: reassign(base, cargos, u),
            ],
        )
        assert not errors, errors


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_same_order_overlapping_creates_do_not_deadlock(make_company):
    company, admin, _ = make_company("DeadlockSame")
    _, ids = make_cargos(company, 3)
    for _ in range(5):
        errors = _race(
            company,
            admin.pk,
            [
                lambda u: create_trip(ids, None, {}, u),
                lambda u: create_trip(ids[::-1], None, {}, u),
            ],
        )
        assert not errors, errors


def test_deadlock_maps_to_409(admin_client, company, monkeypatch):
    from django.db.utils import OperationalError

    from apps.forwarding.trips import serializers

    class Cause(Exception):
        sqlstate = "40P01"

    def boom(*args, **kwargs):
        raise OperationalError("deadlock detected") from Cause()

    monkeypatch.setattr(serializers, "create_trip", boom)
    _, ids = make_cargos(company)
    r = admin_client.post(TRIPS, {"consignments": ids}, format="json")
    assert r.status_code == 409 and r.data["code"] == "concurrent_change"
    assert "повторите" in r.data["detail"]


def test_other_operational_errors_are_not_mapped(admin_client, company, monkeypatch):
    from django.db.utils import OperationalError

    from apps.forwarding.trips.services import is_concurrency_failure

    assert not is_concurrency_failure(OperationalError("x"))
    assert not is_concurrency_failure(ValueError("x"))


# --- фильтр ?order= (fix round 1, 16a) ---


def listed_ids(api, **params):
    r = api.get(TRIPS, params)
    assert r.status_code == 200, r.content
    return {t["id"] for t in r.data["results"]}


def test_filter_by_order_finds_single_and_consolidated_without_duplicates(admin_client, company):
    order1, ids1 = make_cargos(company, n=2)
    order2, ids2 = make_cargos(company)
    single = new_trip(admin_client, ids1[:1])
    both_cargos = new_trip(admin_client, ids1)  # два груза одного заказа: рейс не дублируется
    consolidated = new_trip(admin_client, ids1[:1] + ids2)
    only2 = new_trip(admin_client, ids2)
    r = admin_client.get(TRIPS, {"order": order1.pk})
    assert r.data["count"] == 3
    assert {t["id"] for t in r.data["results"]} == {
        single["id"],
        both_cargos["id"],
        consolidated["id"],
    }
    assert listed_ids(admin_client, order=order2.pk) == {consolidated["id"], only2["id"]}


def test_filter_by_order_ignores_deleted_trips_and_cargos(admin_client, company):
    order, ids = make_cargos(company, n=2)
    keep = new_trip(admin_client, ids[:1])
    gone = new_trip(admin_client, ids[1:])
    with tenant_context(company.id):
        Trip.objects.get(pk=gone["id"]).delete()
    assert listed_ids(admin_client, order=order.pk) == {keep["id"]}
    with tenant_context(company.id):
        Consignment.objects.get(pk=ids[0]).delete()
    assert listed_ids(admin_client, order=order.pk) == set()


@pytest.mark.parametrize("bad", ["abc", "-1", "1.5", "٣", str(2**70)])
def test_filter_by_order_bad_value_is_400_naming_order(admin_client, bad):
    r = admin_client.get(TRIPS, {"order": bad})
    assert r.status_code == 400 and "order" in r.data


def test_filter_by_order_of_other_company_matches_nothing(two):
    (comp_a, _, api_a), (comp_b, _, api_b) = two
    order_a, ids_a = make_cargos(comp_a)
    new_trip(api_a, ids_a)
    assert api_b.get(TRIPS, {"order": order_a.pk}).data["count"] == 0
    assert api_a.get(TRIPS, {"order": order_a.pk}).data["count"] == 1


def test_list_query_bound_holds_with_order_filter(
    admin_client, company, django_assert_max_num_queries
):
    order, ids = make_cargos(company, n=3)
    for cargo_id in ids:
        new_trip(admin_client, [cargo_id])
    with django_assert_max_num_queries(TRIP_LIST_QUERY_BOUND):
        assert admin_client.get(TRIPS, {"order": order.pk}).data["count"] == 3


# --- грузы: фильтр client и поля client/client_name ---

# верхняя граница запросов списка грузов с клиентом: аутентификация и подписка, count, грузы
# (с заказом, клиентом, статусом, упаковкой), точки, страны/способы точек = измеренный минимум
# плюс запас; число запросов не зависит от числа грузов и клиентов
CONSIGNMENT_LIST_QUERY_BOUND = 10


def test_consignments_client_filter_and_fields(admin_client, company):
    c1, c2 = make_client(company, "ТОО Один"), make_client(company, "ТОО Два")
    o1 = make_order(company, c1, consignments=[_svc_cargo(name="Груз 1")])
    make_order(company, c2, consignments=[_svc_cargo(name="Груз 2")])
    r = admin_client.get(CONSIGNMENTS, {"client": c1.pk})
    assert r.status_code == 200 and r.data["count"] == 1
    row = r.data["results"][0]
    assert row["client"] == c1.pk and row["client_name"] == "ТОО Один"
    assert row["order"] == o1.pk
    assert admin_client.get(CONSIGNMENTS, {"client": c2.pk}).data["count"] == 1
    assert admin_client.get(CONSIGNMENTS, {"client": 999999}).data["count"] == 0
    assert admin_client.get(CONSIGNMENTS).data["count"] == 2


def test_consignments_client_filter_bad_value(admin_client):
    for bad in ("abc", "-1", "1.5", "1,2"):
        r = admin_client.get(CONSIGNMENTS, {"client": bad})
        assert r.status_code == 400 and "client" in r.data


def test_consignments_client_filter_isolated_between_companies(two):
    (comp_a, _, api_a), (comp_b, _, api_b) = two
    client_a = make_client(comp_a, "Клиент A")
    make_cargos(comp_a)  # свой заказ с другим клиентом
    make_order(comp_a, client_a, consignments=[_svc_cargo(name="Груз A")])
    assert api_a.get(CONSIGNMENTS, {"client": client_a.pk}).data["count"] == 1
    # id клиента чужой компании: пусто, а у чужого сотрудника ничего не раскрывается
    assert api_b.get(CONSIGNMENTS, {"client": client_a.pk}).data["count"] == 0
    assert api_b.get(CONSIGNMENTS).data["count"] == 0


def test_consignments_client_filter_hides_deleted(admin_client, company):
    client = make_client(company, "ТОО Удаляемый")
    order, _ = make_cargos(company, 2, client=client)
    assert admin_client.get(CONSIGNMENTS, {"client": client.pk}).data["count"] == 2
    with tenant_context(company.id):
        Consignment.objects.filter(order=order).order_by("id").first().delete()
    assert admin_client.get(CONSIGNMENTS, {"client": client.pk}).data["count"] == 1
    admin_client.delete(f"{ORDERS}{order.pk}/")
    assert admin_client.get(CONSIGNMENTS, {"client": client.pk}).data["count"] == 0


def test_consignment_list_query_count_with_client(
    admin_client, company, django_assert_max_num_queries
):
    for i in range(10):
        make_cargos(company, 2, client=make_client(company, f"Клиент {i}"))
    with django_assert_max_num_queries(CONSIGNMENT_LIST_QUERY_BOUND):
        r = admin_client.get(CONSIGNMENTS)
    assert r.status_code == 200 and len(r.data["results"]) == 20
    assert all(row["client_name"].startswith("Клиент") for row in r.data["results"])
    with django_assert_max_num_queries(CONSIGNMENT_LIST_QUERY_BOUND):
        assert admin_client.get(CONSIGNMENTS, {"without_trip": "1", "client": 1}).status_code == 200


# --- carrier_price и устаревший алиас price (задача 1.1) ---


def test_response_has_carrier_price_and_price_alias_equal(admin_client, company):
    _, ids = make_cargos(company)
    d = new_trip(admin_client, ids, carrier_price="1200.50")
    assert d["carrier_price"] == "1200.50" and d["price"] == "1200.50"
    got = admin_client.get(trip_url(d["id"])).data
    assert got["carrier_price"] == got["price"] == "1200.50"
    listed = admin_client.get(TRIPS).data["results"][0]
    assert listed["carrier_price"] == listed["price"] == "1200.50"


def test_old_client_sending_only_price_still_works(admin_client, company):
    _, ids = make_cargos(company)
    d = new_trip(admin_client, ids, price="777.00")  # создание только с price
    assert d["carrier_price"] == "777.00" and d["price"] == "777.00"
    r = admin_client.patch(trip_url(d["id"]), {"price": "888.10"}, format="json")  # PATCH тоже
    assert r.status_code == 200, r.content
    assert r.data["carrier_price"] == r.data["price"] == "888.10"
    with tenant_context(company.id):
        assert str(Trip.objects.get(pk=d["id"]).carrier_price) == "888.10"


def test_new_client_sending_only_carrier_price(admin_client, company):
    _, ids = make_cargos(company)
    d = new_trip(admin_client, ids)
    r = admin_client.patch(trip_url(d["id"]), {"carrier_price": "5.00"}, format="json")
    assert r.status_code == 200 and r.data["price"] == "5.00"


def test_both_equal_values_accepted_even_with_different_notation(admin_client, company):
    _, ids = make_cargos(company)
    d = new_trip(admin_client, ids, price="10", carrier_price="10.00")  # Decimal равны
    assert d["carrier_price"] == d["price"] == "10.00"
    r = admin_client.patch(
        trip_url(d["id"]), {"price": "11.5", "carrier_price": "11.50"}, format="json"
    )
    assert r.status_code == 200 and r.data["price"] == "11.50"


def test_conflicting_price_and_carrier_price_is_400_on_price(admin_client, company):
    _, ids = make_cargos(company)
    r = admin_client.post(
        TRIPS, {"consignments": ids, "price": "1", "carrier_price": "2"}, format="json"
    )
    assert r.status_code == 400 and "price" in r.data and trip_count(company) == 0
    d = new_trip(admin_client, ids, carrier_price="3.00")
    r = admin_client.patch(
        trip_url(d["id"]), {"price": "4.00", "carrier_price": "5.00"}, format="json"
    )
    assert r.status_code == 400 and "price" in r.data
    assert admin_client.get(trip_url(d["id"])).data["carrier_price"] == "3.00"


@pytest.mark.parametrize("field", ["price", "carrier_price"])
def test_negative_and_garbage_rejected_for_both_fields(admin_client, company, field):
    _, ids = make_cargos(company)
    for bad in ("-1", "abc", "1e400"):
        r = admin_client.post(TRIPS, {"consignments": ids, field: bad}, format="json")
        assert r.status_code == 400 and field in r.data, (field, bad)
    d = new_trip(admin_client, ids)
    r = admin_client.patch(trip_url(d["id"]), {field: "-0.01"}, format="json")
    assert r.status_code == 400 and field in r.data
    assert trip_count(company) == 1


def test_service_accepts_both_keys_and_rejects_conflict(company):
    _, ids = make_cargos(company, 3)
    a = svc_create(company, [ids[0]], data={"carrier_price": 10})
    b = svc_create(company, [ids[1]], data={"price": 20})
    c = svc_create(company, [ids[2]], data={"price": "30.00", "carrier_price": 30})
    assert (a.carrier_price, b.carrier_price, c.carrier_price) == (10, 20, 30)
    with pytest.raises(ValidationError) as ei:
        svc_create(company, ids, data={"price": 1, "carrier_price": 2})
    assert "price" in ei.value.detail
    with pytest.raises(ValidationError):
        svc_create(company, ids, data={"carrier_price": -1})
    assert trip_count(company) == 3


def test_db_column_stays_price_and_constraint_kept(company):
    with connection.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='forwarding_trip'"
        )
        cols = {r[0] for r in cur.fetchall()}
        cur.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid='forwarding_trip'::regclass "
            "AND contype='c'"
        )
        checks = {r[0] for r in cur.fetchall()}
    assert "price" in cols and "carrier_price" not in cols
    assert "trip_price_gte_0" in checks
    assert Trip._meta.get_field("carrier_price").column == "price"


def test_new_audit_writes_carrier_price_old_key_is_labelled_too(admin_client, company):
    from apps.core.audit.labels import changes_labels
    from apps.core.audit.services import log

    _, ids = make_cargos(company)
    d = new_trip(admin_client, ids, price="9.00")
    created = audit_rows(company, action="create", object_type="forwarding.trip")[0]
    assert created.changes["carrier_price"] == [None, "9.00"] and "price" not in created.changes
    # старая запись (ключ price) остаётся как есть и получает ту же подпись
    with tenant_context(company.id):
        trip = Trip.objects.get(pk=d["id"])
        old = log("update", trip, None, {"price": ["1.00", "2.00"]})
    assert old.changes == {"price": ["1.00", "2.00"]}
    assert changes_labels("forwarding.trip", old.changes) == {"price": "Стоимость перевозчика"}
    assert changes_labels("forwarding.trip", created.changes)["carrier_price"] == (
        "Стоимость перевозчика"
    )
    assert changes_labels("forwarding.client", {"price": 1}) == {}


def test_audit_api_exposes_labels(admin_client, company):
    _, ids = make_cargos(company)
    new_trip(admin_client, ids, carrier_price="9.00")
    r = admin_client.get("/api/audit/", {"object_type": "forwarding.trip", "action": "create"})
    assert r.status_code == 200
    row = r.data["results"][0]
    assert row["changes_labels"]["carrier_price"] == "Стоимость перевозчика"
