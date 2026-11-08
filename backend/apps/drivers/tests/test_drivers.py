"""Водители: CRUD, права, модуль, лимит, изоляция компаний, аудит, корзина, документы."""

import itertools
from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.billing.models import Plan
from apps.core import trash
from apps.core.api.auth import issue_tokens
from apps.core.audit.models import AuditLog
from apps.core.models import Membership, Role, User
from apps.core.module_services import set_company_modules
from apps.core.tenancy import tenant_context
from apps.drivers.models import Driver, DriverDocument

pytestmark = pytest.mark.django_db

URL = "/api/drivers/"
DOCS = "/api/driver-documents/"
_n = itertools.count(1)


@pytest.fixture
def dco(make_company):
    """Компания с модулем drivers: (компания, администратор, клиент)."""
    return make_company("Drv", modules=["drivers"])


def client_with_role(company, role_name):
    n = next(_n)
    user = User.objects.create_user(email=f"u{n}@drivers.kz", password="Str0ng-pass-91")
    with tenant_context(company.id):
        role = Role.objects.get(name=role_name)
    Membership.objects.create(user=user, company=company, role=role)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    return user, api


def make(company, name="Иванов Иван", **extra):
    with tenant_context(company.id):
        return Driver.objects.create(full_name=name, **extra)


def test_create_normalizes_phone_and_lists(dco):
    company, _, api = dco
    r = api.post(
        URL,
        {"full_name": "  Сериков Ерлан ", "phone": "8 700 111 22 33", "iin": "123456789012"},
        format="json",
    )
    assert r.status_code == 201, r.content
    assert r.json()["full_name"] == "Сериков Ерлан" and r.json()["phone"] == "+77001112233"
    listing = api.get(URL).json()
    assert listing["count"] == 1 and listing["results"][0]["id"] == r.json()["id"]


@pytest.mark.parametrize(
    "payload",
    [
        {"full_name": "   "},
        {"full_name": "A", "phone": "123"},
        {"full_name": "A", "iin": "12345"},
        {"full_name": "A", "iin": "12345678901a"},
    ],
)
def test_validation(dco, payload):
    _, _, api = dco
    assert api.post(URL, payload, format="json").status_code == 400


def test_duplicate_iin_is_400_not_500(dco):
    _, _, api = dco
    first = api.post(URL, {"full_name": "A", "iin": "123456789012"}, format="json")
    assert first.status_code == 201
    r = api.post(URL, {"full_name": "B", "iin": "123456789012"}, format="json")
    assert r.status_code == 400 and "iin" in r.json()


def test_search_status_ordering(dco):
    company, _, api = dco
    make(company, "Алма", status="active", phone="+77001112233")
    make(company, "Берик", status="inactive")
    assert api.get(URL, {"q": "алм"}).json()["count"] == 1
    assert api.get(URL, {"q": "7001112233"}).json()["count"] == 1
    assert [d["full_name"] for d in api.get(URL, {"status": "inactive"}).json()["results"]] == [
        "Берик"
    ]
    names = [d["full_name"] for d in api.get(URL, {"ordering": "-full_name"}).json()["results"]]
    assert names == ["Берик", "Алма"]
    assert api.get(URL, {"status": "zzz"}).status_code == 400
    assert api.get(URL, {"ordering": "bogus"}).status_code == 400


def test_module_disabled_blocks_api_but_keeps_data(dco):
    company, _, api = dco
    d = make(company)
    set_company_modules(company, [])
    r = api.get(URL)
    assert r.status_code == 403 and r.json()["code"] == "module_disabled"
    set_company_modules(company, ["drivers"])
    assert api.get(f"{URL}{d.pk}/").status_code == 200  # данные на месте


def test_permissions_by_role(dco):
    company, _, _ = dco
    make(company)
    _, mechanic = client_with_role(company, "Механик")  # прав на drivers нет
    assert mechanic.get(URL).status_code == 403
    _, manager = client_with_role(company, "Менеджер")  # только drivers.view
    assert manager.get(URL).status_code == 200
    assert manager.post(URL, {"full_name": "X"}, format="json").status_code == 403


def test_company_isolation(make_company):
    a, _, api_a = make_company("A", modules=["drivers"])
    b, _, api_b = make_company("B", modules=["drivers"])
    d = make(a)
    assert api_b.get(f"{URL}{d.pk}/").status_code == 404
    assert api_b.get(URL).json()["count"] == 0
    assert api_a.get(URL).json()["count"] == 1


def test_driver_limit_blocks_new_only(dco):
    company, _, api = dco
    Plan.objects.filter(code="start").update(
        limits={**Plan.objects.get(code="start").limits, "max_drivers": 1}
    )
    assert api.post(URL, {"full_name": "A"}, format="json").status_code == 201
    r = api.post(URL, {"full_name": "B"}, format="json")
    assert r.status_code == 402 and r.json()["code"] == "limit_exceeded"
    first = api.get(URL).json()["results"][0]["id"]
    assert api.patch(f"{URL}{first}/", {"notes": "ok"}, format="json").status_code == 200


def test_delete_goes_to_trash_and_restores(dco):
    company, _, api = dco
    d = make(company)
    assert api.delete(f"{URL}{d.pk}/").status_code == 204
    with tenant_context(company.id):
        assert Driver.trash.filter(pk=d.pk).exists()
    assert api.get(URL).json()["count"] == 0
    assert trash.registered()["drivers"] == (Driver, "drivers.view")


def test_audit_masks_personal_data(dco):
    company, _, api = dco
    r = api.post(
        URL, {"full_name": "A", "phone": "8 700 111 22 33", "iin": "123456789012"}, format="json"
    )
    with tenant_context(company.id):
        log = AuditLog.objects.get(object_type="drivers.driver", object_id=str(r.json()["id"]))
    dumped = str(log.changes)
    assert "+77001112233" not in dumped and "123456789012" not in dumped


def test_user_must_belong_to_company(make_company):
    a, _, api_a = make_company("A", modules=["drivers"])
    _, outsider, _ = make_company("B", modules=["drivers"])
    r = api_a.post(URL, {"full_name": "A", "user": outsider.pk}, format="json")
    assert r.status_code == 400 and "user" in r.json()


def test_documents_crud_and_dates(dco):
    company, _, api = dco
    d = make(company)
    r = api.post(
        DOCS,
        {"driver": d.pk, "kind": "license", "number": "AB123", "expires_at": "2030-01-01"},
        format="json",
    )
    assert r.status_code == 201, r.content
    bad = api.post(
        DOCS,
        {"driver": d.pk, "kind": "medical", "issued_at": "2026-02-01", "expires_at": "2026-01-01"},
        format="json",
    )
    assert bad.status_code == 400
    assert api.get(DOCS, {"driver": d.pk}).json()["count"] == 1
    assert api.get(f"{URL}{d.pk}/").json()["documents"][0]["number"] == "AB123"
    assert api.get(DOCS, {"driver": "x"}).status_code == 400
    assert api.delete(f"{DOCS}{r.json()['id']}/").status_code == 204
    with tenant_context(company.id):
        assert DriverDocument.objects.count() == 0


def test_document_of_foreign_driver_rejected(make_company):
    a, _, api_a = make_company("A", modules=["drivers"])
    b, _, _ = make_company("B", modules=["drivers"])
    foreign = make(b)
    r = api_a.post(DOCS, {"driver": foreign.pk, "kind": "other"}, format="json")
    assert r.status_code == 400


def test_documents_hidden_for_deleted_driver(dco):
    company, _, api = dco
    d = make(company)
    issued = str(date(2026, 1, 1))
    api.post(DOCS, {"driver": d.pk, "kind": "other", "issued_at": issued}, format="json")
    api.delete(f"{URL}{d.pk}/")
    assert api.get(DOCS).json()["count"] == 0
