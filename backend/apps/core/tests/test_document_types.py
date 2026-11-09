"""Типы документов техники и водителей: настройка компании, проверка записей, напоминания."""

from datetime import timedelta

import pytest

from apps.core.models import DocumentType
from apps.core.tenancy import tenant_context
from apps.fleet.services import company_today as _today

pytestmark = pytest.mark.django_db


def company_today(company):
    with tenant_context(company.id):
        return _today()


TYPES = "/api/document-types/"
VDOCS = "/api/vehicle-documents/"
DDOCS = "/api/driver-documents/"


@pytest.fixture
def co(make_company):
    return make_company("DT", modules=["fleet", "drivers"])


def create_type(api, **over):
    body = {"subject": "driver", "name": "Допуск", **over}
    r = api.post(TYPES, body, format="json")
    assert r.status_code == 201, r.json()
    return r.json()


def vehicle(api, kind="tractor", plate="111AAA01"):
    r = api.post("/api/vehicles/", {"kind": kind, "plate": plate}, format="json")
    assert r.status_code == 201, r.json()
    return r.json()["id"]


def driver(api, name="Иванов"):
    r = api.post("/api/drivers/", {"full_name": name}, format="json")
    assert r.status_code == 201, r.json()
    return r.json()["id"]


def test_start_set_is_created_per_company_and_isolated(make_company):
    a = make_company("A", modules=["fleet", "drivers"])
    b = make_company("B", modules=["fleet", "drivers"])
    names = {t["name"] for t in a[2].get(TYPES, {"subject": "driver"}).json()}
    assert "Водительское удостоверение" in names
    t = create_type(a[2], name="Только у A")
    assert t["name"] not in {x["name"] for x in b[2].get(TYPES, {"subject": "driver"}).json()}
    assert b[2].get(f"{TYPES}{t['id']}/").status_code == 404
    assert b[2].patch(f"{TYPES}{t['id']}/", {"name": "x"}, format="json").status_code == 404
    assert b[2].post(f"{TYPES}{t['id']}/archive/").status_code == 404


def test_rename_disable_and_settings_are_independent_per_subject(co):
    api = co[2]
    t = create_type(api, subject="trailer", name="ADR")
    r = api.patch(f"{TYPES}{t['id']}/", {"name": "ДОПОГ", "is_active": False}, format="json")
    assert r.status_code == 200 and r.json()["name"] == "ДОПОГ" and r.json()["is_active"] is False
    drivers = {x["name"] for x in api.get(TYPES, {"subject": "driver"}).json()}
    assert "ДОПОГ" not in drivers
    assert api.patch(f"{TYPES}{t['id']}/", {"subject": "driver"}, format="json").status_code == 400


def test_fields_are_optional_by_default_and_required_only_when_set(co):
    api = co[2]
    t = create_type(api)
    assert t["required"] == [] and set(t["fields"]) == set(DocumentType.STANDARD_FIELDS)
    d = driver(api)
    r = api.post(DDOCS, {"driver": d, "doc_type": t["id"]}, format="json")  # без единого поля
    assert r.status_code == 201
    strict = create_type(api, name="Строгий", required=["number", "expires_at"])
    r = api.post(DDOCS, {"driver": d, "doc_type": strict["id"]}, format="json")
    assert r.status_code == 400 and {"number", "expires_at"} <= set(r.json())
    ok = api.post(
        DDOCS,
        {"driver": d, "doc_type": strict["id"], "number": "1", "expires_at": "2030-01-01"},
        format="json",
    )
    assert ok.status_code == 201


def test_hidden_field_is_rejected_and_extra_fields_work(co):
    api = co[2]
    t = create_type(
        api,
        fields=["number", "expires_at"],
        extra=[{"key": "category", "label": "Категория", "required": True}],
    )
    d = driver(api)
    r = api.post(DDOCS, {"driver": d, "doc_type": t["id"], "issued_by": "ЦОН"}, format="json")
    assert r.status_code == 400 and "issued_by" in r.json() and "extra" in r.json()
    r = api.post(
        DDOCS,
        {"driver": d, "doc_type": t["id"], "number": "5", "extra": {"category": "CE"}},
        format="json",
    )
    assert r.status_code == 201 and r.json()["extra"] == {"category": "CE"}
    bad = api.post(
        DDOCS,
        {"driver": d, "doc_type": t["id"], "extra": {"category": "C", "zzz": "1"}},
        format="json",
    )
    assert bad.status_code == 400


def test_config_validation(co):
    api = co[2]
    base = {"subject": "driver", "name": "X"}
    for bad in (
        {"fields": ["nope"]},
        {"fields": ["number"], "required": ["expires_at"]},
        {"extra": [{"key": "Bad Key", "label": "a"}]},
        {"extra": [{"key": "a", "label": "a"}, {"key": "a", "label": "b"}]},
        {"remind": True},  # без сроков
        {"remind": True, "remind_days": [30], "fields": ["number"]},  # нет даты окончания
        {"remind_days": [0]},
    ):
        assert api.post(TYPES, {**base, **bad}, format="json").status_code == 400, bad
    ok = api.post(TYPES, {**base, "remind": True, "remind_days": [7, 30, 30]}, format="json")
    assert ok.status_code == 201 and ok.json()["remind_days"] == [30, 7]


def test_subject_must_match_object_and_vehicle_kind(co):
    api = co[2]
    tractor_type = create_type(api, subject="tractor", name="Т")
    trailer_type = create_type(api, subject="trailer", name="П")
    drv_type = create_type(api)
    tractor, trailer = vehicle(api), vehicle(api, "trailer", "222BBB02")
    assert (
        api.post(
            VDOCS, {"vehicle": tractor, "doc_type": tractor_type["id"]}, format="json"
        ).status_code
        == 201
    )
    assert (
        api.post(
            VDOCS, {"vehicle": trailer, "doc_type": trailer_type["id"]}, format="json"
        ).status_code
        == 201
    )
    for veh, wrong in ((tractor, trailer_type), (trailer, tractor_type), (tractor, drv_type)):
        r = api.post(VDOCS, {"vehicle": veh, "doc_type": wrong["id"]}, format="json")
        assert r.status_code == 400 and "doc_type" in r.json()
    d = driver(api)
    assert (
        api.post(DDOCS, {"driver": d, "doc_type": tractor_type["id"]}, format="json").status_code
        == 400
    )


def test_other_company_type_cannot_be_used(make_company):
    a = make_company("A", modules=["drivers"])
    b = make_company("B", modules=["drivers"])
    t = create_type(a[2])
    d = driver(b[2])
    r = b[2].post(DDOCS, {"driver": d, "doc_type": t["id"]}, format="json")
    assert r.status_code == 400


def test_disabled_and_archived_types_keep_records_but_reject_new_ones(co):
    api = co[2]
    t = create_type(api, name="Старый")
    d = driver(api)
    doc = api.post(DDOCS, {"driver": d, "doc_type": t["id"], "number": "7"}, format="json").json()
    r = api.post(f"{TYPES}{t['id']}/archive/")
    assert r.status_code == 200 and r.json()["archived_at"] and r.json()["is_active"] is False
    # запись и история сохранились, правка записи без смены типа работает
    kept = api.get(f"{DDOCS}{doc['id']}/").json()
    assert kept["doc_type"] == t["id"] and kept["number"] == "7"
    assert api.patch(f"{DDOCS}{doc['id']}/", {"notes": "ok"}, format="json").status_code == 200
    # новые записи по архивному типу - нет; в списке типов его не видно, с ?archived=1 видно
    assert api.post(DDOCS, {"driver": d, "doc_type": t["id"]}, format="json").status_code == 400
    listed = api.get(TYPES, {"subject": "driver"}).json()
    assert t["id"] not in [x["id"] for x in listed]
    shown = api.get(TYPES, {"subject": "driver", "archived": "1"}).json()
    assert t["id"] in [x["id"] for x in shown]
    assert api.patch(f"{TYPES}{t['id']}/", {"name": "N"}, format="json").status_code == 400
    # имя освободилось; возврат из архива при конфликте имён запрещён
    again = create_type(api, name="Старый")
    assert api.post(f"{TYPES}{t['id']}/unarchive/").status_code == 400
    api.post(f"{TYPES}{again['id']}/archive/")
    assert api.post(f"{TYPES}{t['id']}/unarchive/").json()["archived_at"] is None
    assert api.delete(f"{TYPES}{t['id']}/").status_code == 405  # физического удаления нет


def test_disabled_type_is_not_offered_for_new_records(co):
    api = co[2]
    t = create_type(api, name="Выкл")
    d = driver(api)
    api.patch(f"{TYPES}{t['id']}/", {"is_active": False}, format="json")
    assert api.post(DDOCS, {"driver": d, "doc_type": t["id"]}, format="json").status_code == 400


def test_module_and_permission_gates(make_company):
    only_drivers = make_company("D", modules=["drivers"])
    assert only_drivers[2].get(TYPES, {"subject": "tractor"}).status_code == 403
    body = {"subject": "tractor", "name": "X"}
    assert only_drivers[2].post(TYPES, body, format="json").status_code == 403
    only_drivers_list = only_drivers[2].get(TYPES).json()
    assert {t["subject"] for t in only_drivers_list} == {"driver"}


def test_reminders_follow_type_settings(co):
    api = co[2]
    today = company_today(co[0])
    near = (today + timedelta(days=20)).isoformat()
    on = create_type(api, subject="tractor", name="С напоминанием", remind=True, remind_days=[30])
    off = create_type(api, subject="tractor", name="Без напоминания")
    narrow = create_type(api, subject="tractor", name="Узкое окно", remind=True, remind_days=[7])
    v = vehicle(api)
    for t in (on, off, narrow):
        assert (
            api.post(
                VDOCS, {"vehicle": v, "doc_type": t["id"], "expires_at": near}, format="json"
            ).status_code
            == 201
        )
    items = api.get("/api/fleet/reminders/", {"days": 1}).json()["results"]
    titles = {i["title"] for i in items if i["type"] == "document"}
    assert titles == {"С напоминанием"}  # тип сам задаёт окно (30 дней), общий days игнорируется
    expired = (today - timedelta(days=1)).isoformat()
    api.post(VDOCS, {"vehicle": v, "doc_type": narrow["id"], "expires_at": expired}, format="json")
    states = {i["title"]: i["state"] for i in api.get("/api/fleet/reminders/").json()["results"]}
    assert states["Узкое окно"] == "overdue"


def test_driver_reminders(co):
    api = co[2]
    today = company_today(co[0])
    t = create_type(api, name="Права2", remind=True, remind_days=[30, 7])
    quiet = create_type(api, name="Тихий")
    d = driver(api)
    soon = (today + timedelta(days=10)).isoformat()
    far = (today + timedelta(days=100)).isoformat()
    api.post(DDOCS, {"driver": d, "doc_type": t["id"], "expires_at": soon}, format="json")
    api.post(DDOCS, {"driver": d, "doc_type": t["id"], "expires_at": far}, format="json")
    api.post(DDOCS, {"driver": d, "doc_type": quiet["id"], "expires_at": soon}, format="json")
    res = api.get("/api/drivers/reminders/").json()
    assert res["count"] == 1 and res["results"][0]["title"] == "Права2"
    assert res["results"][0]["state"] == "due_soon"


def test_reminders_isolated_between_companies(make_company):
    a = make_company("A", modules=["drivers"])
    b = make_company("B", modules=["drivers"])
    t = create_type(a[2], name="R", remind=True, remind_days=[30])
    d = driver(a[2])
    soon = (company_today(a[0]) + timedelta(days=3)).isoformat()
    a[2].post(DDOCS, {"driver": d, "doc_type": t["id"], "expires_at": soon}, format="json")
    assert a[2].get("/api/drivers/reminders/").json()["count"] == 1
    assert b[2].get("/api/drivers/reminders/").json()["count"] == 0
    with tenant_context(b[0].id):
        assert not DocumentType.objects.filter(name="R").exists()
