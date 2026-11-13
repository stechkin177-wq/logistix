"""Единые источники: банковские счета и договоры (API, зеркало bank/iban, перенос)."""

import importlib
from datetime import date
from types import SimpleNamespace

import pytest
from django.apps import apps as global_apps
from django.db import connection

from apps.core.models import LegalEntity
from apps.core.tenancy import tenant_context
from apps.documents.models import IssuedDocument
from apps.forwarding.models import BankAccount, Carrier, Client, Contract, Order, Trip
from apps.forwarding.tests.test_orders import ORDERS, make_client, make_order
from apps.forwarding.tests.test_parties import client_with_role
from apps.forwarding.tests.test_trips import make_cargos, make_carrier, new_trip, trip_url

pytestmark = pytest.mark.django_db

ACCOUNTS = "/api/bank-accounts/"
CONTRACTS = "/api/contracts/"


def mirror(company, model, pk):
    with tenant_context(company.id):
        obj = model.objects.get(pk=pk)
        return obj.bank, obj.iban


def add_account(api, **payload):
    return api.post(ACCOUNTS, payload, format="json")


# --- банковские счета ---


def test_first_account_is_default_and_updates_mirror(admin_client, company):
    client = make_client(company)
    r = add_account(admin_client, client=client.pk, bank="Halyk", iban="kz 12 3456")
    assert r.status_code == 201, r.content
    assert r.json()["is_default"] is True and r.json()["iban"] == "KZ123456"
    assert mirror(company, Client, client.pk) == ("Halyk", "KZ123456")
    shown = admin_client.get(f"/api/clients/{client.pk}/").json()
    assert shown["bank"] == "Halyk" and len(shown["accounts"]) == 1


def test_second_default_switches_mirror_and_delete_promotes_other(admin_client, company):
    client = make_client(company)
    first = add_account(admin_client, client=client.pk, bank="Halyk", iban="KZ1").json()
    second = add_account(
        admin_client, client=client.pk, bank="Kaspi", iban="KZ2", is_default=True
    ).json()
    assert mirror(company, Client, client.pk) == ("Kaspi", "KZ2")
    listed = admin_client.get(ACCOUNTS, {"client": client.pk}).json()
    assert [a["is_default"] for a in listed] == [True, False] and listed[0]["id"] == second["id"]
    assert admin_client.delete(f"{ACCOUNTS}{second['id']}/").status_code == 204
    assert mirror(company, Client, client.pk) == ("Halyk", "KZ1")
    assert admin_client.delete(f"{ACCOUNTS}{first['id']}/").status_code == 204
    assert mirror(company, Client, client.pk) == ("", "")


def test_legacy_patch_of_bank_iban_updates_default_account(admin_client, company):
    client = make_client(company)
    r = admin_client.patch(
        f"/api/clients/{client.pk}/", {"bank": "Halyk", "iban": "KZ1"}, format="json"
    )
    assert r.status_code == 200
    with tenant_context(company.id):
        (acc,) = BankAccount.objects.filter(client=client)
        assert acc.is_default and (acc.bank, acc.iban) == ("Halyk", "KZ1")
    admin_client.patch(f"/api/clients/{client.pk}/", {"iban": "KZ9"}, format="json")
    with tenant_context(company.id):
        assert BankAccount.objects.filter(client=client).count() == 1
        assert BankAccount.objects.get(client=client).iban == "KZ9"


def test_create_party_with_legacy_bank_creates_account(admin_client, company):
    r = admin_client.post(
        "/api/clients/", {"name": "Новый", "bank": "Halyk", "iban": "KZ5"}, format="json"
    )
    assert r.status_code == 201
    with tenant_context(company.id):
        assert BankAccount.objects.filter(client_id=r.json()["id"], is_default=True).count() == 1


def test_account_validation_owner_and_duplicates(admin_client, company):
    client = make_client(company)
    carrier = make_carrier(company)
    assert add_account(admin_client, bank="X").status_code == 400  # нет владельца
    assert (
        add_account(admin_client, client=client.pk, carrier=carrier.pk, bank="X").status_code == 400
    )
    assert add_account(admin_client, client=client.pk).status_code == 400  # ни банка, ни IBAN
    ok = add_account(admin_client, client=client.pk, iban="KZ1").json()
    assert add_account(admin_client, client=client.pk, iban="kz1").status_code == 400  # дубль IBAN
    assert (
        add_account(admin_client, client=client.pk, iban="KZ2", currency="kzt").json()["currency"]
        == "KZT"
    )
    assert add_account(admin_client, client=client.pk, iban="KZ3", currency="ТГ").status_code == 400
    moved = admin_client.patch(f"{ACCOUNTS}{ok['id']}/", {"carrier": carrier.pk}, format="json")
    assert moved.status_code == 400  # владельца менять нельзя
    assert admin_client.get(ACCOUNTS).status_code == 400  # без владельца список не отдаётся


def test_account_permissions_follow_owner_section(company):
    client = make_client(company)
    carrier = make_carrier(company)
    _, manager = client_with_role(company, "Менеджер")  # clients.update есть, carriers.update есть
    _, observer = client_with_role(company, "Наблюдатель")  # только view
    assert observer.get(ACCOUNTS, {"client": client.pk}).status_code == 200
    assert add_account(observer, client=client.pk, iban="KZ1").status_code == 403
    assert add_account(manager, client=client.pk, iban="KZ1").status_code == 201
    assert add_account(manager, carrier=carrier.pk, iban="KZ2").status_code == 201
    _, accountant = client_with_role(company, "Бухгалтер")  # clients.view без update
    assert add_account(accountant, client=client.pk, iban="KZ3").status_code == 403


def test_account_isolation_between_companies(make_company):
    a, _, api_a = make_company("A")
    b, _, api_b = make_company("B")
    client_a = make_client(a)
    add_account(api_a, client=client_a.pk, iban="KZ1")
    assert api_b.get(ACCOUNTS, {"client": client_a.pk}).json() == []
    assert add_account(api_b, client=client_a.pk, iban="KZ2").status_code == 400  # чужой клиент


def test_legal_entity_accounts_mirror_and_company_permission(admin_client, company):
    with tenant_context(company.id):
        entity = LegalEntity.objects.filter(is_default=True).first() or LegalEntity.objects.create(
            name="Мы", is_default=True
        )
    r = add_account(admin_client, legal_entity=entity.pk, bank="Kaspi", iban="KZ77")
    assert r.status_code == 201, r.content
    assert mirror(company, LegalEntity, entity.pk) == ("Kaspi", "KZ77")


# --- договоры ---


def new_contract(api, **payload):
    return api.post(CONTRACTS, {"number": "Д-1", "date": "2026-01-10", **payload}, format="json")


def test_contract_crud_rules(admin_client, company):
    client = make_client(company)
    r = new_contract(admin_client, client=client.pk, valid_until="2026-12-31")
    assert r.status_code == 201, r.content
    cid = r.json()["id"]
    assert r.json()["source"] == "manual" and r.json()["party_name"] == client.name
    assert new_contract(admin_client, client=client.pk).status_code == 400  # дубль номера у клиента
    assert (
        new_contract(
            admin_client, client=client.pk, number="Д-2", valid_until="2025-01-01"
        ).status_code
        == 400
    )
    assert new_contract(admin_client, number="Д-3").status_code == 400  # нет стороны
    other = make_client(company, "Другой")
    assert (
        new_contract(admin_client, client=other.pk).status_code == 201
    )  # тот же номер у другого - можно
    moved = admin_client.patch(f"{CONTRACTS}{cid}/", {"client": other.pk}, format="json")
    assert moved.status_code == 400
    assert admin_client.get(CONTRACTS).status_code == 400
    listed = admin_client.get(CONTRACTS, {"client": client.pk}).json()
    assert [c["number"] for c in listed["results"]] == ["Д-1"]
    assert admin_client.delete(f"{CONTRACTS}{cid}/").status_code == 204
    assert admin_client.get(CONTRACTS, {"client": client.pk}).json()["count"] == 0


def test_active_filter_hides_expired(admin_client, company):
    client = make_client(company)
    new_contract(admin_client, client=client.pk, number="old", valid_until="2020-01-01")
    new_contract(admin_client, client=client.pk, number="open")
    got = admin_client.get(CONTRACTS, {"client": client.pk, "active": "1"}).json()
    assert [c["number"] for c in got["results"]] == ["open"]


def test_order_uses_contract_of_its_client_and_keeps_text_compat(admin_client, company):
    client = make_client(company)
    other = make_client(company, "Другой")
    mine = new_contract(admin_client, client=client.pk, number="Д-10").json()
    foreign = new_contract(admin_client, client=other.pk, number="Д-99").json()
    bad = admin_client.post(ORDERS, {"client": client.pk, "contract": foreign["id"]}, format="json")
    assert bad.status_code == 400 and "contract" in bad.json()
    ok = admin_client.post(ORDERS, {"client": client.pk, "contract": mine["id"]}, format="json")
    assert ok.status_code == 201, ok.content
    assert ok.json()["contract"] == mine["id"] and ok.json()["contract_number"] == "Д-10"
    # прежний путь: только текст, без договора
    legacy = admin_client.post(
        ORDERS, {"client": client.pk, "contract_number": "вручную"}, format="json"
    )
    assert legacy.status_code == 201 and legacy.json()["contract"] is None
    # перенос на другого клиента снимает договор прежнего
    moved = admin_client.patch(f"{ORDERS}{ok.json()['id']}/", {"client": other.pk}, format="json")
    assert moved.status_code == 200 and moved.json()["contract"] is None


def test_contract_in_use_cannot_be_deleted(admin_client, company):
    client = make_client(company)
    c = new_contract(admin_client, client=client.pk, number="Д-5").json()
    admin_client.post(ORDERS, {"client": client.pk, "contract": c["id"]}, format="json")
    r = admin_client.delete(f"{CONTRACTS}{c['id']}/")
    assert r.status_code == 409 and r.json()["code"] == "contract_in_use"


def test_trip_contract_belongs_to_trips_carrier(admin_client, company):
    carrier = make_carrier(company, "Свой")
    other = make_carrier(company, "Чужой")
    mine = new_contract(admin_client, carrier=carrier.pk, number="П-1").json()
    foreign = new_contract(admin_client, carrier=other.pk, number="П-2").json()
    _, ids = make_cargos(company)
    # при создании рейса договор не принимается: выбирается после создания
    refused = admin_client.post(
        "/api/trips/",
        {"consignments": ids, "carrier": carrier.pk, "contract": mine["id"]},
        format="json",
    )
    assert refused.status_code == 400
    trip = new_trip(admin_client, ids, carrier=carrier.pk)
    bad = admin_client.patch(trip_url(trip["id"]), {"contract": foreign["id"]}, format="json")
    assert bad.status_code == 400 and "contract" in bad.json()
    ok = admin_client.patch(trip_url(trip["id"]), {"contract": mine["id"]}, format="json")
    assert ok.status_code == 200 and ok.json()["contract"] == mine["id"]
    # смена перевозчика снимает договор прежнего
    swapped = admin_client.patch(trip_url(trip["id"]), {"carrier": other.pk}, format="json")
    assert swapped.status_code == 200 and swapped.json()["contract"] is None
    assert admin_client.get(f"/api/carriers/{carrier.pk}/").json()["accounts"] == []


# --- перенос данных (миграция 0018) ---

SHIM = SimpleNamespace(connection=connection)


def run_backfill():
    importlib.import_module(
        "apps.forwarding.migrations.0018_requisites_contracts_backfill"
    ).forwards(global_apps, SHIM)


def test_backfill_creates_accounts_and_contracts_idempotently_without_touching_old_data(
    company, admin_user
):
    with tenant_context(company.id):
        client = Client.objects.create(name="К", bank="Halyk", iban="KZ1")
        carrier = Carrier.objects.create(name="П", iban="KZ2")
        Client.objects.create(name="Пустой")
        entity = LegalEntity.objects.create(name="Мы", bank="Kaspi", iban="KZ3")
    order = make_order(company, client, contract_number=" Д-77 ")
    make_order(company, client, contract_number=" Д-77 ")
    with tenant_context(company.id):
        from apps.documents.models import DocumentTemplateVersion

        version = DocumentTemplateVersion.objects.first()
        doc = IssuedDocument.objects.create(
            kind="contract", template_version=version, number="Д-5", issue_date=date(2026, 3, 1),
            client=client, created_by=admin_user,
        )  # fmt: skip
    run_backfill()
    run_backfill()  # идемпотентность
    with tenant_context(company.id):
        assert BankAccount.objects.filter(client=client, is_default=True).count() == 1
        assert BankAccount.objects.filter(carrier=carrier, is_default=True).count() == 1
        assert BankAccount.objects.filter(legal_entity=entity, is_default=True).count() == 1
        assert BankAccount.objects.count() == 3  # пустой клиент счёта не получил
        assert Client.objects.get(pk=client.pk).iban == "KZ1"  # прежние поля не тронуты
        numbers = sorted(Contract.objects.filter(client=client).values_list("number", flat=True))
        assert numbers == ["Д-5", "Д-77"]
        assert Contract.objects.get(number="Д-5").source == "imported"
        assert Contract.objects.get(number="Д-5").document_id == doc.pk
        assert Order.objects.filter(client=client, contract__number="Д-77").count() == 2
        assert Order.objects.get(pk=order.pk).contract_number == " Д-77 "  # текст не менялся
        assert Trip.objects.count() == 0
