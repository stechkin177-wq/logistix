"""Техника: CRUD, права, модуль, лимит, изоляция, аудит, корзина, документы и страховки."""

import itertools

import pytest
from rest_framework.test import APIClient

from apps.billing.models import Plan
from apps.core import trash
from apps.core.api.auth import issue_tokens
from apps.core.audit.models import AuditLog
from apps.core.models import Membership, Role, User
from apps.core.module_services import set_company_modules
from apps.core.tenancy import tenant_context
from apps.fleet.models import Insurance, Vehicle, VehicleDocument

pytestmark = pytest.mark.django_db

URL = "/api/vehicles/"
DOCS = "/api/vehicle-documents/"
INS = "/api/insurances/"
_n = itertools.count(1)


@pytest.fixture
def fco(make_company):
    return make_company("Fleet", modules=["fleet"])


def client_with_role(company, role_name):
    n = next(_n)
    user = User.objects.create_user(email=f"u{n}@fleet.kz", password="Str0ng-pass-91")
    with tenant_context(company.id):
        role = Role.objects.get(name=role_name)
    Membership.objects.create(user=user, company=company, role=role)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    return api


def make(company, plate="777AAA01", **extra):
    with tenant_context(company.id):
        return Vehicle.objects.create(plate=plate, **extra)


def test_create_normalizes_plate_and_lists(fco):
    _, _, api = fco
    r = api.post(URL, {"plate": " 777 aaa-01 ", "kind": "tractor", "year": 2020}, format="json")
    assert r.status_code == 201, r.content
    assert r.json()["plate"] == "777AAA01"
    assert api.get(URL).json()["count"] == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"plate": "   "},
        {"plate": "A1", "kind": "boat"},
        {"plate": "A1", "year": 1800},
        {"plate": "A1", "volume_m3": "-1"},
        {"plate": "A1", "status": "lost"},
    ],
)
def test_validation(fco, payload):
    assert fco[2].post(URL, payload, format="json").status_code == 400


def test_duplicate_plate_is_400_not_500(fco):
    _, _, api = fco
    assert api.post(URL, {"plate": "A1"}, format="json").status_code == 201
    r = api.post(URL, {"plate": "a 1"}, format="json")
    assert r.status_code == 400 and "plate" in r.json()


def test_plate_can_be_reused_after_delete(fco):
    company, _, api = fco
    v = make(company, "A1")
    assert api.delete(f"{URL}{v.pk}/").status_code == 204
    assert api.post(URL, {"plate": "A1"}, format="json").status_code == 201


def test_search_filters_ordering(fco):
    company, _, api = fco
    make(company, "AAA1", kind="tractor", make="Volvo")
    make(company, "BBB2", kind="trailer", status="repair")
    assert api.get(URL, {"q": "volvo"}).json()["count"] == 1
    assert api.get(URL, {"q": "bbb 2"}).json()["count"] == 1
    assert api.get(URL, {"kind": "trailer"}).json()["count"] == 1
    assert api.get(URL, {"status": "repair"}).json()["count"] == 1
    plates = [v["plate"] for v in api.get(URL, {"ordering": "-plate"}).json()["results"]]
    assert plates == ["BBB2", "AAA1"]
    for bad in ({"kind": "x"}, {"status": "x"}, {"ordering": "x"}):
        assert api.get(URL, bad).status_code == 400


def test_module_disabled_blocks_api_but_keeps_data(fco):
    company, _, api = fco
    v = make(company)
    set_company_modules(company, [])
    r = api.get(URL)
    assert r.status_code == 403 and r.json()["code"] == "module_disabled"
    set_company_modules(company, ["fleet"])
    assert api.get(f"{URL}{v.pk}/").status_code == 200


def test_permissions_by_role(fco):
    company, _, _ = fco
    make(company)
    assert client_with_role(company, "Менеджер").get(URL).status_code == 200
    assert client_with_role(company, "Менеджер").post(URL, {"plate": "X"}).status_code == 403
    mech = client_with_role(company, "Механик")  # fleet.view/create/update
    assert mech.post(URL, {"plate": "M1"}, format="json").status_code == 201
    first = mech.get(URL).json()["results"][0]["id"]
    assert mech.delete(f"{URL}{first}/").status_code == 403
    driver_role = client_with_role(company, "Водитель")
    assert driver_role.get(URL).status_code == 403


def test_company_isolation(make_company):
    a, _, api_a = make_company("A", modules=["fleet"])
    _, _, api_b = make_company("B", modules=["fleet"])
    v = make(a)
    assert api_b.get(f"{URL}{v.pk}/").status_code == 404
    assert api_b.get(URL).json()["count"] == 0


def test_vehicle_limit_blocks_new_only(fco):
    _, _, api = fco
    limits = {**Plan.objects.get(code="start").limits, "max_vehicles": 1}
    Plan.objects.filter(code="start").update(limits=limits)
    assert api.post(URL, {"plate": "A1"}, format="json").status_code == 201
    r = api.post(URL, {"plate": "B2"}, format="json")
    assert r.status_code == 402 and r.json()["code"] == "limit_exceeded"
    first = api.get(URL).json()["results"][0]["id"]
    assert api.patch(f"{URL}{first}/", {"notes": "ok"}, format="json").status_code == 200


def test_delete_goes_to_trash(fco):
    company, _, api = fco
    v = make(company)
    assert api.delete(f"{URL}{v.pk}/").status_code == 204
    with tenant_context(company.id):
        assert Vehicle.trash.filter(pk=v.pk).exists()
    assert trash.registered()["vehicles"] == (Vehicle, "fleet.view")


def test_audit_masks_vin(fco):
    company, _, api = fco
    r = api.post(URL, {"plate": "A1", "vin": "WVWZZZ1JZXW000001"}, format="json")
    with tenant_context(company.id):
        log = AuditLog.objects.get(object_type="fleet.vehicle", object_id=str(r.json()["id"]))
    assert "WVWZZZ1JZXW000001" not in str(log.changes)


CHILDREN = [
    (DOCS, VehicleDocument, {"kind": "permit"}),
    (INS, Insurance, {"kind": "osago", "policy_number": "P1"}),
]


@pytest.mark.parametrize(("url", "model", "extra"), CHILDREN)
def test_children_crud_dates_and_foreign_vehicle(make_company, url, model, extra):
    a, _, api = make_company("A", modules=["fleet"])
    b, _, _ = make_company("B", modules=["fleet"])
    v, foreign = make(a), make(b, "F1")
    r = api.post(url, {"vehicle": v.pk, "expires_at": "2030-01-01", **extra}, format="json")
    assert r.status_code == 201, r.content
    wrong = {"vehicle": v.pk, "starts_at": "2026-02-01", "expires_at": "2026-01-01", **extra}
    bad = api.post(url, wrong, format="json")
    assert bad.status_code == 400
    assert api.post(url, {"vehicle": foreign.pk, **extra}, format="json").status_code == 400
    assert api.get(url, {"vehicle": v.pk}).json()["count"] == 1
    assert api.get(url, {"vehicle": "x"}).status_code == 400
    key = "documents" if model is VehicleDocument else "insurances"
    assert api.get(f"{URL}{v.pk}/").json()[key]
    assert api.delete(f"{url}{r.json()['id']}/").status_code == 204
    with tenant_context(a.id):
        assert model.objects.count() == 0


def test_children_hidden_for_deleted_vehicle(fco):
    company, _, api = fco
    v = make(company)
    api.post(DOCS, {"vehicle": v.pk, "kind": "other"}, format="json")
    api.delete(f"{URL}{v.pk}/")
    assert api.get(DOCS).json()["count"] == 0
