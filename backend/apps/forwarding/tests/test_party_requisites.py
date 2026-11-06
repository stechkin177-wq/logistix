import pytest

from apps.forwarding.tests.test_parties import URLS, audit_rows

pytestmark = pytest.mark.django_db

REQ = {
    "address": "г. Алматы, ул. Абая 1, оф. 5",
    "bank": "АО Народный банк Казахстана",
    "iban": "KZ86125KZT5004100100",
}


def test_client_requisites_roundtrip(admin_client):
    r = admin_client.post(URLS["clients"], {"name": "ТОО Алма", **REQ}, format="json")
    assert r.status_code == 201, r.content
    d = admin_client.get(f"{URLS['clients']}{r.data['id']}/").data
    assert {k: d[k] for k in REQ} == REQ
    lst = admin_client.get(URLS["clients"]).data
    row = (lst["results"] if isinstance(lst, dict) else lst)[0]
    assert {k: row[k] for k in REQ} == REQ


def test_carrier_requisites_roundtrip(admin_client):
    r = admin_client.post(URLS["carriers"], {"name": "ИП Жол", **REQ}, format="json")
    assert r.status_code == 201, r.content
    d = admin_client.get(f"{URLS['carriers']}{r.data['id']}/").data
    assert {k: d[k] for k in REQ} == REQ
    r2 = admin_client.patch(f"{URLS['carriers']}{r.data['id']}/", {"bank": "Kaspi"}, format="json")
    assert r2.status_code == 200 and r2.data["bank"] == "Kaspi" and r2.data["iban"] == REQ["iban"]


def test_iban_masked_in_audit(admin_client, company):
    r = admin_client.post(URLS["clients"], {"name": "Секрет", **REQ}, format="json")
    assert r.status_code == 201, r.content
    rows = audit_rows(company, object_type="forwarding.client")
    create = rows[0]
    assert create.changes["iban"] == "***"
    assert REQ["iban"] not in str(create.changes)


def test_requisites_optional(admin_client):
    r = admin_client.post(URLS["clients"], {"name": "Старый запрос"}, format="json")
    assert r.status_code == 201, r.content
    assert r.data["address"] == "" and r.data["bank"] == "" and r.data["iban"] == ""


@pytest.mark.parametrize("resource", ["clients", "carriers"])
def test_iban_too_long_is_400(admin_client, resource):
    r = admin_client.post(URLS[resource], {"name": "X", "iban": "K" * 35}, format="json")
    assert r.status_code == 400
    assert "iban" in r.data
