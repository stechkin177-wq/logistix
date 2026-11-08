"""Официальный пробег: только выезд и завершение рейса; справочный пробег; сверка с GPS."""

import pytest

from apps.core.tenancy import tenant_context
from apps.fleet import services
from apps.fleet.models import MileageReading, Vehicle
from apps.forwarding.tests.test_orders import hv
from apps.forwarding.tests.test_trips import make_cargos, new_trip, trip_url

pytestmark = pytest.mark.django_db

FULL = ["logistics", "fleet"]


@pytest.fixture
def co(make_company):
    return make_company("Odo", modules=FULL)


def veh(company, plate="T1", **extra):
    with tenant_context(company.id):
        return Vehicle.objects.create(plate=plate, **extra)


def status(api, company, trip_id, code, **extra):
    value = hv(company, "trip_status", code=code)
    return api.post(trip_url(trip_id, "status/"), {"status": value.pk, **extra}, format="json")


def official(company, v):
    with tenant_context(company.id):
        return [(r.source, r.odometer_km) for r in MileageReading.objects.filter(vehicle=v)]


def test_departure_and_completion_record_official_mileage(co):
    company, _, api = co
    _, ids = make_cargos(company)
    tractor, trailer = veh(company), veh(company, "P1", kind="trailer")
    trip = new_trip(api, ids, vehicle=tractor.pk, trailer=trailer.pk)
    r = status(api, company, trip["id"], "IN_PROGRESS", vehicle_km=100000, trailer_km=40000)
    assert r.status_code == 200, r.content
    assert status(api, company, trip["id"], "UNLOADING").status_code == 200
    # возврат «Выгрузка» -> «В пути» не создаёт второго показания выезда
    assert status(api, company, trip["id"], "IN_PROGRESS", vehicle_km=100500).status_code == 400
    assert status(api, company, trip["id"], "IN_PROGRESS").status_code == 200
    r = status(api, company, trip["id"], "COMPLETED", vehicle_km=101200, trailer_km=41200)
    assert r.status_code == 200, r.content
    assert official(company, tractor) == [("trip_start", 100000), ("trip_end", 101200)]
    assert official(company, trailer) == [("trip_start", 40000), ("trip_end", 41200)]  # раздельно


def test_mileage_is_optional_and_only_for_departure_or_completion(co):
    company, _, api = co
    _, ids = make_cargos(company)
    v = veh(company)
    trip = new_trip(api, ids, vehicle=v.pk)
    assert status(api, company, trip["id"], "ASSIGNED", vehicle_km=1).status_code == 400
    assert status(api, company, trip["id"], "IN_PROGRESS").status_code == 200  # без пробега можно
    assert status(api, company, trip["id"], "COMPLETED").status_code == 200
    assert official(company, v) == []


def test_late_entry_correction_and_validation(co):
    company, _, api = co
    _, ids = make_cargos(company)
    v = veh(company)
    trip = new_trip(api, ids, vehicle=v.pk)
    odometer = trip_url(trip["id"], "odometer/")
    start = {"phase": "start", "vehicle_km": 5000}
    assert api.post(odometer, start, format="json").status_code == 400  # рейс ещё не выехал
    status(api, company, trip["id"], "IN_PROGRESS")
    assert api.post(odometer, start, format="json").status_code == 200
    fix = {"phase": "start", "vehicle_km": 5100}
    assert api.post(odometer, fix, format="json").status_code == 200
    assert official(company, v) == [("trip_start", 5100)]  # исправление, а не вторая запись
    end = {"phase": "end", "vehicle_km": 5500}
    assert api.post(odometer, end, format="json").status_code == 400  # не завершён
    status(api, company, trip["id"], "COMPLETED")
    low = {"phase": "end", "vehicle_km": 5000}
    assert api.post(odometer, low, format="json").status_code == 400
    assert api.post(odometer, end, format="json").status_code == 200
    assert api.post(odometer, {"phase": "start"}, format="json").status_code == 400  # нет значения
    assert api.post(odometer, {"phase": "start", "trailer_km": 1}, format="json").status_code == 400


def test_next_trip_cannot_start_below_previous_official_mileage(co):
    company, _, api = co
    v = veh(company)
    _, ids1 = make_cargos(company)
    _, ids2 = make_cargos(company)
    first = new_trip(api, ids1, vehicle=v.pk)
    status(api, company, first["id"], "IN_PROGRESS", vehicle_km=1000)
    status(api, company, first["id"], "COMPLETED", vehicle_km=1500)
    second = new_trip(api, ids2, vehicle=v.pk)
    r = status(api, company, second["id"], "IN_PROGRESS", vehicle_km=1400)
    assert r.status_code == 400
    # статус при ошибке пробега не меняется (одна транзакция)
    assert api.get(trip_url(second["id"])).json()["status_name"] != "В пути"
    assert status(api, company, second["id"], "IN_PROGRESS", vehicle_km=1500).status_code == 200


def test_mileage_api_is_read_only(co):
    company, _, api = co
    v = veh(company)
    r = api.post("/api/mileage/", {"vehicle": v.pk, "odometer_km": 1}, format="json")
    assert r.status_code == 405
    assert api.get("/api/mileage/").status_code == 200


# --- сверка с GPS ---


def test_gps_check_setting_off_shows_nothing(co):
    company, _, api = co
    v = veh(company)
    assert api.get(f"/api/vehicles/{v.pk}/mileage-check/").json() == {"enabled": False}


def test_gps_unavailable_when_no_source(co):
    company, _, api = co
    v = veh(company, gps_check=True)
    with tenant_context(company.id):
        MileageReading.objects.create(
            vehicle=v, odometer_km=1000, source="trip_end", recorded_at="2026-06-01T10:00:00Z"
        )
    data = api.get(f"/api/vehicles/{v.pk}/mileage-check/").json()
    assert data["enabled"] and data["gps_available"] is False
    assert data["official_km"] == 1000 and data["gps_km"] is None and data["warning"] is False


def test_gps_difference_warning_threshold_and_no_side_effects(co):
    company, _, api = co
    v = veh(company, gps_check=True)
    with tenant_context(company.id):
        MileageReading.objects.create(
            vehicle=v, odometer_km=10000, source="trip_end", recorded_at="2026-06-01T10:00:00Z"
        )
    source = lambda vehicle, at: 10080  # noqa: E731
    services.register_gps_source(source)
    try:
        data = api.get(f"/api/vehicles/{v.pk}/mileage-check/").json()
        assert (data["official_km"], data["gps_km"], data["difference_km"]) == (10000, 10080, 80)
        assert data["warning"] is False  # порог по умолчанию 100 км
        lowered = api.patch("/api/fleet/settings/", {"gps_mismatch_km": 50}, format="json")
        assert lowered.status_code == 200
        assert api.get(f"/api/vehicles/{v.pk}/mileage-check/").json()["warning"] is True
    finally:
        services.unregister_gps_source(source)
    # GPS ничего не записывает и не меняет в официальном пробеге
    assert official(company, v) == [("trip_end", 10000)]


def test_gps_check_is_independent_setting_of_vehicle(co):
    company, _, api = co
    v = veh(company)
    r = api.patch(f"/api/vehicles/{v.pk}/", {"gps_check": True}, format="json")
    assert r.status_code == 200 and r.json()["gps_check"] is True
    assert api.get(f"/api/vehicles/{v.pk}/mileage-check/").json()["enabled"] is True


def test_fleet_settings_validation_and_rights(co):
    company, _, api = co
    assert api.get("/api/fleet/settings/").json() == {"gps_mismatch_km": 100}
    for bad in (-1, "x", True, 10**7, None):
        r = api.patch("/api/fleet/settings/", {"gps_mismatch_km": bad}, format="json")
        assert r.status_code == 400, bad
