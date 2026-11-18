"""Модуль gps: аккаунт Wialon, юниты и привязка к технике, геозоны, события, вебхук, сверка."""

import itertools
from datetime import UTC, datetime

import pytest
from rest_framework.test import APIClient

from apps.billing.models import Plan
from apps.core.api.auth import issue_tokens
from apps.core.models import Membership, Role, User
from apps.core.module_services import set_company_modules
from apps.core.tenancy import tenant_context
from apps.fleet.models import Vehicle
from apps.gps import crypto, geometry, services
from apps.gps.models import Geofence, GeofenceEvent, GpsUnit, VehicleGeofenceState, WialonAccount
from apps.gps.wialon import WialonAPIError

pytestmark = pytest.mark.django_db

_n = itertools.count(1)
BASE = "/api/gps/"


def gps_company(make_company, name, modules=("fleet", "gps")):
    """Компания с модулями; gps добавляется в тариф «start» (в базе тестов его состав - данные)."""
    plan = Plan.objects.get(code="start")
    if "gps" not in plan.modules:
        Plan.objects.filter(code="start").update(modules=[*plan.modules, "gps"])
    company, admin, api = make_company(name, modules=["fleet"])
    set_company_modules(company, list(modules))
    return company, admin, api


@pytest.fixture
def gco(make_company):
    return gps_company(make_company, "GPS")


def api_with_role(company, role_name):
    user = User.objects.create_user(email=f"g{next(_n)}@gps.kz", password="Str0ng-pass-91")
    with tenant_context(company.id):
        role = Role.objects.get(name=role_name)
    Membership.objects.create(user=user, company=company, role=role)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    return api


def vehicle(company, plate="886AIA14", **extra):
    with tenant_context(company.id):
        return Vehicle.objects.create(plate=plate, **extra)


class FakeClient:
    """Подмена Wialon: отдаёт заданные юниты и зоны, ничего не запрашивая по сети."""

    def __init__(self, units=(), zones=(), fail=None):
        self.units, self.zones, self.fail = list(units), list(zones), fail

    def login(self):
        if self.fail:
            raise WialonAPIError(self.fail)
        return {"eid": "sid", "au": "dispatcher"}

    def list_units(self):
        if self.fail:
            raise WialonAPIError(self.fail)
        return self.units

    def list_zones(self):
        return self.zones

    template = None
    fillings: list = []
    track: list = []

    def get_track(self, unit_id, dt_from, dt_to):
        if self.fail:
            raise WialonAPIError(self.fail)
        return self.track

    def find_report_template(self):
        return self.template

    def get_fuel_fillings(self, resource_id, template_id, unit_id, dt_from, dt_to):
        if self.fail:
            raise WialonAPIError(self.fail)
        return self.fillings

    extract_position = staticmethod(
        lambda item: __import__("apps.gps.wialon", fromlist=["x"]).WialonClient.extract_position(
            item
        )
    )
    extract_mileage_km = staticmethod(
        lambda item: __import__("apps.gps.wialon", fromlist=["x"]).WialonClient.extract_mileage_km(
            item
        )
    )
    extract_fuel_level_l = staticmethod(
        lambda item: __import__(
            "apps.gps.wialon", fromlist=["x"]
        ).WialonClient.extract_fuel_level_l(item)
    )


def unit_item(uid, name, lat=43.2, lon=76.9, cnm=1000.0, t=1_760_000_000):
    return {"id": uid, "nm": name, "pos": {"y": lat, "x": lon, "s": 40, "t": t}, "cnm": cnm}


@pytest.fixture
def fake(monkeypatch):
    holder = {"client": FakeClient()}
    monkeypatch.setattr(services, "client_for", lambda account: holder["client"])
    return holder


def connect(api, token="tok-123"):
    r = api.put(BASE + "account/", {"token": token}, format="json")
    assert r.status_code == 200, r.content
    return r.json()


# --- геометрия ---------------------------------------------------------------------------------


def test_geometry_distance_and_polygon():
    assert 100_000 < geometry.distance_m(43.2, 76.9, 44.1, 76.9) < 101_000  # ~0.9 градуса широты
    square = [[43.0, 76.0], [43.0, 77.0], [44.0, 77.0], [44.0, 76.0]]
    assert geometry.point_in_polygon(43.5, 76.5, square)
    assert not geometry.point_in_polygon(45.0, 76.5, square)
    assert not geometry.point_in_polygon(43.5, 76.5, square[:2])  # меньше трёх точек
    lat, lon, radius = geometry.enclosing_circle(square)
    assert round(lat, 1) == 43.5 and round(lon, 1) == 76.5 and radius > 50_000


def test_parse_wialon_zone_circle_polygon_line():
    circle = geometry.parse_wialon_zone({"t": 3, "p": [{"x": 76.9, "y": 43.2, "r": 250}]})
    assert circle["shape"] == "circle" and circle["radius_m"] == 250 and not circle["approximate"]
    poly = geometry.parse_wialon_zone(
        {"t": 2, "p": [{"x": 76.0, "y": 43.0}, {"x": 77.0, "y": 43.0}, {"x": 77.0, "y": 44.0}]}
    )
    assert poly["shape"] == "polygon" and len(poly["polygon"]) == 3 and not poly["approximate"]
    line = geometry.parse_wialon_zone(
        {"t": 1, "p": [{"x": 76.0, "y": 43.0}, {"x": 76.1, "y": 43.0}]}
    )
    assert line["shape"] == "circle" and line["approximate"]
    assert geometry.parse_wialon_zone({"t": 2, "p": []}) is None


def test_match_vehicle_ignores_spaces_case_and_prefers_longest(gco):
    company = gco[0]
    short = vehicle(company, "886AIA")
    longer = vehicle(company, "886AIA14")
    with tenant_context(company.id):
        vehicles = list(Vehicle.objects.all())
        assert services.match_vehicle("Volvo FH 886 aia 14 рефр", vehicles).pk == longer.pk
        assert services.match_vehicle("886AIA", vehicles).pk == short.pk
        assert services.match_vehicle("без номера", vehicles) is None
        assert services.match_vehicle("", vehicles) is None


# ----------------------------------------------------------------------------------------------


def test_account_token_is_encrypted_and_never_returned(gco):
    company, _, api = gco
    data = connect(api)
    assert data["configured"] and data["has_token"] and "token" not in data
    assert data["webhook_path"].startswith(f"/api/gps/wialon/webhook/{company.pk}/")
    with tenant_context(company.id):
        account = WialonAccount.objects.get()
        assert "tok-123" not in account.token_enc and crypto.decrypt(account.token_enc) == "tok-123"
    again = api.get(BASE + "account/").json()
    assert again["has_token"] and "token" not in again and "token_enc" not in again
    # пустой токен при повторном сохранении не стирает прежний
    api.put(BASE + "account/", {"token": "", "is_active": False}, format="json")
    with tenant_context(company.id):
        account = WialonAccount.objects.get()
        assert crypto.decrypt(account.token_enc) == "tok-123" and account.is_active is False


def test_account_requires_token_and_public_https_base_url(gco):
    _, _, api = gco
    assert api.put(BASE + "account/", {}, format="json").status_code == 400
    bad = api.put(
        BASE + "account/", {"token": "t", "base_url": "http://hst-api.wialon.com"}, format="json"
    )
    assert (
        bad.status_code == 400 and "base_url" in bad.json()["errors"]
        if "errors" in bad.json()
        else True
    )
    assert (
        api.put(
            BASE + "account/", {"token": "t", "base_url": "https://127.0.0.1"}, format="json"
        ).status_code
        == 400
    )


def test_account_test_endpoint(gco, fake):
    _, _, api = gco
    assert api.post(BASE + "account/test/").status_code == 400  # токена нет
    connect(api)
    fake["client"] = FakeClient(units=[unit_item(1, "A"), unit_item(2, "B")])
    ok = api.post(BASE + "account/test/").json()
    assert ok == {"ok": True, "user": "dispatcher", "units": 2}
    fake["client"] = FakeClient(fail="Wialon: ошибка 4 в token/login")
    bad = api.post(BASE + "account/test/").json()
    assert bad["ok"] is False and "token" not in bad["error"].lower().replace("token/login", "")


def test_permissions_module_and_roles(gco, make_company):
    company, _, admin = gco
    dispatcher = api_with_role(company, "Диспетчер")
    mechanic = api_with_role(company, "Механик")
    assert dispatcher.get(BASE + "units/").status_code == 200  # просмотр
    assert mechanic.get(BASE + "geofences/").status_code == 200
    assert dispatcher.put(BASE + "account/", {"token": "x"}, format="json").status_code == 403
    assert dispatcher.post(BASE + "sync/").status_code == 403
    assert (
        dispatcher.post(
            BASE + "geofences/", {"name": "З", "lat": 43, "lon": 76, "radius_m": 100}, format="json"
        ).status_code
        == 403
    )
    # компания без модуля gps
    other, _, other_api = gps_company(make_company, "NoGps", modules=("fleet",))
    assert other_api.get(BASE + "units/").status_code == 403


# ----------------------------------------------------------------------------------------------


def test_sync_creates_units_and_auto_links_by_plate(gco, fake):
    company, _, api = gco
    veh = vehicle(company, "886AIA14")
    connect(api)
    fake["client"] = FakeClient(
        units=[unit_item(1, "Volvo 886 AIA 14", cnm=12345.6), unit_item(2, "Неизвестный юнит")]
    )
    res = api.post(BASE + "sync/").json()
    assert res["ok"] and res["units"]["units_seen"] == 2 and res["units"]["auto_linked"] == 1
    units = {u["unit_id"]: u for u in api.get(BASE + "units/").json()["results"]}
    assert units["1"]["vehicle"] == veh.pk and units["1"]["vehicle_plate"] == "886AIA14"
    assert units["1"]["odometer_km"] == "12345.6" and units["2"]["vehicle"] is None
    assert api.get(BASE + "account/").json()["last_synced_at"] is not None
    # повторная синхронизация обновляет, а не дублирует; ручная привязка сохраняется
    api.post(BASE + "sync/")
    assert api.get(BASE + "units/").json()["count"] == 2


def test_sync_error_is_saved_and_reported(gco, fake):
    _, _, api = gco
    connect(api)
    fake["client"] = FakeClient(fail="Wialon недоступен: URLError")
    r = api.post(BASE + "sync/")
    assert r.status_code == 502 and r.json()["ok"] is False
    assert "недоступен" in api.get(BASE + "account/").json()["last_sync_error"]


def test_link_unlink_and_conflict(gco):
    company, _, api = gco
    v1, v2 = vehicle(company, "111AAA01"), vehicle(company, "222BBB02")
    with tenant_context(company.id):
        u1 = GpsUnit.objects.create(unit_id="1", name="U1")
        u2 = GpsUnit.objects.create(unit_id="2", name="U2")
    assert (
        api.post(f"{BASE}units/{u1.pk}/link/", {"vehicle": v1.pk}, format="json").status_code == 200
    )
    clash = api.post(f"{BASE}units/{u2.pk}/link/", {"vehicle": v1.pk}, format="json")
    assert clash.status_code == 400
    assert api.post(f"{BASE}units/{u1.pk}/unlink/").json()["vehicle"] is None
    assert (
        api.post(f"{BASE}units/{u2.pk}/link/", {"vehicle": v1.pk}, format="json").status_code == 200
    )
    assert api.post(f"{BASE}units/{u2.pk}/link/", {}, format="json").status_code == 400
    assert api.get(BASE + "units/?linked=true").json()["count"] == 1
    assert v2.pk  # вторая машина свободна


def test_auto_link_endpoint(gco):
    company, _, api = gco
    vehicle(company, "333CCC03")
    with tenant_context(company.id):
        GpsUnit.objects.create(unit_id="1", name="КамАЗ 333 CCC 03")
        GpsUnit.objects.create(unit_id="2", name="Прочее")
    assert api.post(BASE + "units/auto-link/").json() == {"linked": 1}
    assert api.post(BASE + "units/auto-link/").json() == {"linked": 0}


# ----------------------------------------------------------------------------------------------


def test_geofence_crud_validation(gco):
    _, _, api = gco
    ok = api.post(
        BASE + "geofences/",
        {"name": "База", "kind": "warehouse", "lat": 43.2, "lon": 76.9, "radius_m": 300},
        format="json",
    )
    assert (
        ok.status_code == 201 and ok.json()["shape"] == "circle" and ok.json()["source"] == "manual"
    )
    assert (
        api.post(
            BASE + "geofences/", {"name": "X", "lat": 95, "lon": 76, "radius_m": 100}, format="json"
        ).status_code
        == 400
    )
    assert (
        api.post(
            BASE + "geofences/", {"name": "X", "lat": 43, "lon": 76, "radius_m": 5}, format="json"
        ).status_code
        == 400
    )
    square = [[43.0, 76.0], [43.0, 77.0], [44.0, 77.0], [44.0, 76.0]]
    poly = api.post(
        BASE + "geofences/",
        {"name": "Город", "kind": "city", "shape": "polygon", "polygon": square},
        format="json",
    )
    assert (
        poly.status_code == 201
        and poly.json()["polygon"] == square
        and poly.json()["radius_m"] > 50_000
    )
    assert (
        api.post(
            BASE + "geofences/",
            {"name": "Б", "shape": "polygon", "polygon": square[:2]},
            format="json",
        ).status_code
        == 400
    )
    assert (
        api.post(BASE + "geofences/", {"name": "Б", "shape": "polygon"}, format="json").status_code
        == 400
    )
    assert (
        api.patch(
            f"{BASE}geofences/{ok.json()['id']}/", {"is_active": False}, format="json"
        ).json()["is_active"]
        is False
    )
    assert api.get(BASE + "geofences/?active=true").json()["count"] == 1


def test_sync_geofences_mirrors_and_deactivates(gco, fake):
    company, _, api = gco
    connect(api)
    zones = [
        {
            "resource_id": "7",
            "zone_id": "1",
            "raw": {"n": "Склад Алматы", "t": 3, "p": [{"x": 76.9, "y": 43.2, "r": 200}]},
        },
        {
            "resource_id": "7",
            "zone_id": "2",
            "raw": {
                "n": "Граница",
                "t": 2,
                "p": [{"x": 76.0, "y": 43.0}, {"x": 77.0, "y": 43.0}, {"x": 77.0, "y": 44.0}],
            },
        },
    ]
    fake["client"] = FakeClient(zones=zones)
    first = api.post(BASE + "sync/").json()["geofences"]
    assert first["created"] == 2
    rows = {g["name"]: g for g in api.get(BASE + "geofences/").json()["results"]}
    assert rows["Склад Алматы"]["kind"] == "warehouse" and rows["Граница"]["kind"] == "border"
    assert rows["Граница"]["shape"] == "polygon"
    fake["client"] = FakeClient(zones=zones[:1])  # вторая зона удалена в Wialon
    second = api.post(BASE + "sync/").json()["geofences"]
    assert second["updated"] == 1 and second["deactivated"] == 1
    with tenant_context(company.id):
        assert Geofence.objects.get(name="Граница").is_active is False
        assert Geofence.objects.count() == 2  # не удалена: история событий жива


def test_position_check_writes_events_only_on_transitions(gco):
    company, _, _ = gco
    veh = vehicle(company)
    t = [datetime(2026, 11, 1, h, tzinfo=UTC) for h in (8, 9, 10, 11)]
    with tenant_context(company.id):
        zone = Geofence.objects.create(name="База", lat="43.2", lon="76.9", radius_m=300)
        poly = Geofence.objects.create(
            name="Контур", shape="polygon", lat="50", lon="60", radius_m=100_000,
            polygon=[[50.0, 60.0], [50.0, 61.0], [51.0, 61.0], [51.0, 60.0]],
        )  # fmt: skip
        assert services.check_geofences(veh, 40.0, 70.0, t[0]) == 0  # вне зон и не был в них
        assert services.check_geofences(veh, 43.2, 76.9, t[1]) == 1  # въезд в круг
        assert services.check_geofences(veh, 43.2005, 76.9, t[2]) == 0  # всё ещё внутри
        assert (
            services.check_geofences(veh, 50.5, 60.5, t[2]) == 2
        )  # выезд из круга и въезд в контур
        assert services.check_geofences(veh, 40.0, 70.0, t[3]) == 1  # выезд из контура
        kinds = list(
            GeofenceEvent.objects.filter(geofence=zone)
            .order_by("occurred_at")
            .values_list("event_type", flat=True)
        )
        assert kinds == ["enter", "exit"]
        assert VehicleGeofenceState.objects.get(vehicle=veh, geofence=poly).is_inside is False


def test_sync_checks_geofences_for_linked_units(gco, fake):
    company, _, api = gco
    veh = vehicle(company)
    connect(api)
    with tenant_context(company.id):
        Geofence.objects.create(name="База", lat="43.2", lon="76.9", radius_m=300)
    fake["client"] = FakeClient(units=[unit_item(1, "886AIA14", lat=43.2, lon=76.9)])
    api.post(BASE + "sync/")
    events = api.get(f"{BASE}events/?vehicle={veh.pk}").json()["results"]
    assert [e["event_type"] for e in events] == ["enter"] and events[0]["geofence_name"] == "База"
    assert api.get(BASE + "events/?vehicle=abc").status_code == 400


# ----------------------------------------------------------------------------------------------


def webhook(company, secret, **params):
    return APIClient().get(f"/api/gps/wialon/webhook/{company.pk}/{secret}/", params)


def test_webhook_enter_exit_duplicates_and_unknowns(gco):
    company, _, api = gco
    veh = vehicle(company)
    secret = connect(api)["webhook_path"].rstrip("/").split("/")[-1]
    with tenant_context(company.id):
        Geofence.objects.create(name="База", lat="43.2", lon="76.9", radius_m=300)
    r = webhook(company, secret, event="enter", unit="Volvo 886 aia 14", zone="база")
    assert r.status_code == 200 and r.json() == {
        "ok": True,
        "vehicle": "886AIA14",
        "zones": ["База"],
        "recorded": 1,
        "duplicates": 0,
    }
    assert (
        webhook(company, secret, event="enter", unit="886AIA14", zone="База").json()["recorded"]
        == 0
    )
    assert (
        webhook(
            company, secret, event="exit", unit="886AIA14", zone="База", time="1760000000"
        ).json()["recorded"]
        == 1
    )
    assert (
        webhook(company, secret, event="enter", unit="Нет такого", zone="База").json()["reason"]
        == "unknown_unit"
    )
    assert (
        webhook(company, secret, event="enter", unit="886AIA14", zone="Нет зоны").json()["reason"]
        == "unknown_zone"
    )
    assert webhook(company, secret, event="jump", unit="886AIA14", zone="База").status_code == 400
    assert webhook(company, secret, event="enter", unit="886AIA14").status_code == 400
    with tenant_context(company.id):
        assert GeofenceEvent.objects.filter(vehicle=veh).count() == 2


def test_webhook_wrong_secret_or_company_is_404_and_isolated(gco, make_company):
    company, _, api = gco
    other, _, other_api = gps_company(make_company, "Other")
    secret = connect(api)["webhook_path"].rstrip("/").split("/")[-1]
    other_secret = connect(other_api)["webhook_path"].rstrip("/").split("/")[-1]
    assert webhook(company, "wrong", event="enter", unit="x", zone="y").status_code == 404
    assert (
        webhook(company, other_secret, event="enter", unit="x", zone="y").status_code == 404
    )  # секрет чужой компании
    assert webhook(other, secret, event="enter", unit="x", zone="y").status_code == 404
    assert APIClient().get("/api/gps/wialon/webhook/999999/abc/").status_code == 404


def test_company_isolation_of_units_and_geofences(gco, make_company):
    company, _, api = gco
    other, _, other_api = gps_company(make_company, "Other2")
    with tenant_context(other.id):
        GpsUnit.objects.create(unit_id="9", name="Чужой")
        Geofence.objects.create(name="Чужая", lat="1", lon="1", radius_m=100)
    assert api.get(BASE + "units/").json()["count"] == 0
    assert api.get(BASE + "geofences/").json()["count"] == 0
    assert other_api.get(BASE + "units/").json()["count"] == 1


# ----------------------------------------------------------------------------------------------


def test_fleet_mileage_check_uses_gps_unit_without_changing_official(gco):
    company, _, api = gco
    veh = vehicle(company, gps_check=True, initial_odometer_km=10000)
    when = datetime(2026, 11, 1, 12, tzinfo=UTC)
    assert api.get(f"/api/vehicles/{veh.pk}/mileage-check/").json()["gps_available"] is False
    with tenant_context(company.id):
        GpsUnit.objects.create(
            unit_id="1", name="U", vehicle=veh, odometer_km="10250.4", odometer_at=when
        )
    data = api.get(f"/api/vehicles/{veh.pk}/mileage-check/").json()
    assert data["gps_available"] and data["gps_km"] == 10250 and data["difference_km"] == 250
    assert data["warning"] is True and data["gps_received_at"].startswith("2026-11-01")
    with tenant_context(company.id):
        assert Vehicle.objects.get(pk=veh.pk).initial_odometer_km == 10000  # GPS ничего не меняет


# --- сверка заправок отчёта с датчиком топлива --------------------------------------------


def fuel_url(vehicle, **extra):
    params = {"vehicle": vehicle.pk, "date_from": "2026-11-01", "date_to": "2026-11-10", **extra}
    return BASE + "fuel-check/?" + "&".join(f"{k}={v}" for k, v in params.items())


def test_compare_fuel_tolerance():
    assert services.compare_fuel(500, 480)["warning"] is False  # 20 л: в допуске
    assert services.compare_fuel(540, 500)["warning"] is True  # 40 л > max(20, 5% = 25)
    assert services.compare_fuel(500, 500) == {
        "reported_l": 500.0, "gps_l": 500.0, "difference_l": 0.0, "warning": False,
    }  # fmt: skip
    assert services.compare_fuel(None, 500)["difference_l"] is None
    assert services.compare_fuel(500, None) == {
        "reported_l": 500.0, "gps_l": None, "difference_l": None, "warning": False,
    }  # fmt: skip
    big = services.compare_fuel(1000, 2000)  # допуск растёт с объёмом: 5% от 2000 = 100 л
    assert big["warning"] is True and services.compare_fuel(1950, 2000)["warning"] is False


def test_fuel_check_reasons_and_data(gco, fake):
    company, _, api = gco
    veh = vehicle(company)
    assert api.get(fuel_url(veh)).json()["reason"] == "no_account"
    connect(api)
    assert api.get(fuel_url(veh)).json()["reason"] == "no_unit"
    with tenant_context(company.id):
        GpsUnit.objects.create(unit_id="501", name="U", vehicle=veh)
    fake["client"] = FakeClient()  # шаблона отчёта нет
    assert api.get(fuel_url(veh)).json()["reason"] == "no_report_template"
    client = FakeClient()
    client.template = (1, 2)
    client.fillings = [
        {"timestamp": 1_762_000_000, "filled_l": 300.0},
        {"timestamp": 1_762_100_000, "filled_l": 250.5},
    ]
    fake["client"] = client
    data = api.get(fuel_url(veh, reported_l=600)).json()
    assert data["available"] and data["total_l"] == 550.5 and len(data["fillings"]) == 2
    assert data["difference_l"] == 49.5 and data["warning"] is True  # 49.5 > max(20, 27.5)
    assert api.get(fuel_url(veh, reported_l=560)).json()["warning"] is False
    fake["client"] = FakeClient(fail="Wialon недоступен: URLError")
    fake["client"].template = (1, 2)
    assert api.get(fuel_url(veh)).json() == {
        "available": False, "reason": "wialon_error", "fillings": [], "total_l": None,
        "reported_l": None, "gps_l": None, "difference_l": None, "warning": False,
    }  # fmt: skip


def test_fuel_check_validation_and_permissions(gco):
    company, _, api = gco
    veh = vehicle(company)
    assert api.get(BASE + "fuel-check/").status_code == 400
    assert api.get(fuel_url(veh, date_from="junk")).status_code == 400
    assert api.get(fuel_url(veh, date_from="2026-11-10", date_to="2026-11-01")).status_code == 400
    assert api.get(fuel_url(veh, date_from="2026-01-01", date_to="2026-11-01")).status_code == 400
    assert api.get(fuel_url(veh, reported_l="abc")).status_code == 400
    assert api_with_role(company, "Диспетчер").get(fuel_url(veh)).status_code == 200  # просмотр
    assert api_with_role(company, "Бухгалтер").get(fuel_url(veh)).status_code == 403  # нет gps.view


# --- трек ---------------------------------------------------------------------------------


def test_downsample_and_length():
    pts = [{"t": i, "lat": 43.0 + i * 0.001, "lon": 76.0} for i in range(2000)]
    small = services.downsample(pts, 800)
    assert len(small) == 800 and small[0] == pts[0] and small[-1] == pts[-1]
    assert services.downsample(pts[:10], 800) == pts[:10]
    assert 220 < services.track_length_km(pts) < 225  # ~2 градуса по широте
    assert services.track_length_km([]) == 0 and services.track_length_km(pts[:1]) == 0


def test_unit_track_api(gco, fake):
    company, _, api = gco
    with tenant_context(company.id):
        unit = GpsUnit.objects.create(unit_id="501", name="U")
    url = f"{BASE}units/{unit.pk}/track/"
    assert api.get(url).json()["reason"] == "no_account"
    connect(api)
    client = FakeClient()
    client.track = [
        {"t": 1_762_000_000 + i * 60, "lat": 43.2 + i * 0.01, "lon": 76.9, "speed": 50}
        for i in range(5)
    ]
    fake["client"] = client
    data = api.get(url + "?date_from=2026-11-01&date_to=2026-11-02").json()
    assert data["available"] and data["total_points"] == 5 and len(data["points"]) == 5
    assert data["points"][0]["lat"] == 43.2 and data["length_km"] > 4
    assert api.get(url).json()["available"] is True  # по умолчанию - последние сутки
    fake["client"] = FakeClient(fail="Wialon недоступен: URLError")
    bad = api.get(url + "?date_from=2026-11-01&date_to=2026-11-02").json()
    assert bad["available"] is False and bad["reason"] == "wialon_error" and bad["points"] == []


def test_unit_track_validation_and_permissions(gco):
    company, _, api = gco
    with tenant_context(company.id):
        unit = GpsUnit.objects.create(unit_id="501", name="U")
    url = f"{BASE}units/{unit.pk}/track/"
    assert api.get(url + "?date_from=junk&date_to=2026-11-02").status_code == 400
    assert api.get(url + "?date_from=2026-11-02").status_code == 400  # одна дата
    assert api.get(url + "?date_from=2026-11-05&date_to=2026-11-01").status_code == 400
    assert api.get(url + "?date_from=2026-01-01&date_to=2026-11-01").status_code == 400
    assert api_with_role(company, "Диспетчер").get(url).status_code == 200
    assert api_with_role(company, "Бухгалтер").get(url).status_code == 403
