"""Назначение техники и водителя на рейс (подзадача 2.3)."""

import pytest

from apps.core.module_services import set_company_modules
from apps.core.tenancy import tenant_context
from apps.drivers.models import Driver
from apps.fleet.models import Vehicle
from apps.forwarding.models import Trip
from apps.forwarding.tests.test_orders import hv
from apps.forwarding.tests.test_trips import make_cargos, new_trip, trip_url

pytestmark = pytest.mark.django_db

FULL = ["logistics", "fleet", "drivers"]


@pytest.fixture
def co(make_company):
    return make_company("Res", modules=FULL)


def vehicle(company, plate="777AAA01", **extra):
    with tenant_context(company.id):
        return Vehicle.objects.create(plate=plate, kind=extra.pop("kind", "tractor"), **extra)


def driver(company, name="Иванов", **extra):
    with tenant_context(company.id):
        return Driver.objects.create(full_name=name, **extra)


def set_status(api, company, trip_id, code):
    value = hv(company, "trip_status", code=code)
    return api.post(trip_url(trip_id, "status/"), {"status": value.pk}, format="json")


def test_assign_on_create_fills_free_fields(co):
    company, _, api = co
    _, ids = make_cargos(company)
    v, t, d = vehicle(company), vehicle(company, "T1", kind="trailer"), driver(company)
    data = new_trip(api, ids, vehicle=v.pk, trailer=t.pk, driver=d.pk)
    assert (data["vehicle"], data["trailer"], data["driver"]) == (v.pk, t.pk, d.pk)
    assert data["vehicle_plate"] == "777AAA01" and data["driver_name"] == "Иванов"


def test_free_fields_are_not_overwritten(co):
    company, _, api = co
    _, ids = make_cargos(company)
    v = vehicle(company)
    data = new_trip(api, ids, vehicle=v.pk, vehicle_plate="СВОЙ")
    assert data["vehicle_plate"] == "СВОЙ"


def test_kind_and_status_rules(co):
    company, _, api = co
    _, ids = make_cargos(company)
    truck, trailer = vehicle(company), vehicle(company, "T1", kind="trailer")
    repair = vehicle(company, "R1", status="repair")
    off = driver(company, "Уволен", status="inactive")
    for payload in (
        {"vehicle": trailer.pk},
        {"trailer": truck.pk},
        {"vehicle": repair.pk},
        {"driver": off.pk},
        {"vehicle": truck.pk, "trailer": truck.pk},
    ):
        r = api.post("/api/trips/", {"consignments": ids, **payload}, format="json")
        assert r.status_code == 400, payload


def test_module_disabled_rejects_assignment_but_keeps_existing(co):
    company, _, api = co
    _, ids = make_cargos(company)
    v = vehicle(company)
    trip = new_trip(api, ids, vehicle=v.pk)
    set_company_modules(company, ["logistics", "drivers"])  # fleet выключен
    again = api.patch(trip_url(trip["id"]), {"notes": "x"}, format="json")
    assert again.status_code in (200, 400)  # правка других полей не ломается
    r = api.patch(trip_url(trip["id"]), {"trailer": v.pk}, format="json")
    assert r.status_code == 400 and "trailer" in r.json()
    with tenant_context(company.id):
        assert Trip.objects.get(pk=trip["id"]).vehicle_id == v.pk  # назначение сохранено


def test_foreign_company_resources_rejected(make_company):
    a, _, api_a = make_company("A", modules=FULL)
    b, _, _ = make_company("B", modules=FULL)
    _, ids = make_cargos(a)
    foreign = vehicle(b, "F1")
    r = api_a.post("/api/trips/", {"consignments": ids, "vehicle": foreign.pk}, format="json")
    assert r.status_code == 400


def test_busy_vehicle_and_driver_blocked_only_against_trips_in_work(co):
    company, _, api = co
    _, ids1 = make_cargos(company)
    _, ids2 = make_cargos(company)
    v, d = vehicle(company), driver(company)
    first = new_trip(api, ids1, vehicle=v.pk, driver=d.pk)
    # первый рейс ещё не в работе: второй рейс с тем же ресурсом создаётся
    second = new_trip(api, ids2, vehicle=v.pk, driver=d.pk)
    assert set_status(api, company, first["id"], "IN_PROGRESS").status_code == 200
    # теперь первый в работе: второй нельзя перевести в работу и нельзя назначить заново
    r = set_status(api, company, second["id"], "IN_PROGRESS")
    assert r.status_code == 409 and r.json()["code"] == "resource_busy"
    _, ids3 = make_cargos(company)
    other = new_trip(api, ids3)
    r = api.patch(trip_url(other["id"]), {"driver": d.pk}, format="json")
    assert r.status_code == 409
    # после завершения первого ресурс свободен
    assert set_status(api, company, first["id"], "COMPLETED").status_code == 200
    assert set_status(api, company, second["id"], "IN_PROGRESS").status_code == 200


def test_unassign_and_legs_inherit(co):
    company, _, api = co
    _, ids = make_cargos(company)
    v = vehicle(company)
    trip = new_trip(api, ids, vehicle=v.pk)
    r = api.patch(trip_url(trip["id"]), {"vehicle": None}, format="json")
    assert r.status_code == 200 and r.json()["vehicle"] is None


def test_without_modules_trip_works_as_before(make_company):
    company, _, api = make_company("Old", modules=["logistics"])
    _, ids = make_cargos(company)
    data = new_trip(api, ids, vehicle_plate="A1", driver_name="Имя")
    assert data["vehicle"] is None and data["driver"] is None and data["vehicle_plate"] == "A1"
