# ruff: noqa: E501
"""A7: универсальный субъект документа и реестр поставщиков (независимость documents)."""

import importlib
import io
import zipfile
from types import SimpleNamespace

import pytest
from django.apps import apps as django_apps
from django.core.cache import cache
from django.db import connection

from apps.billing.models import Plan
from apps.core.module_services import set_company_modules
from apps.core.tenancy import tenant_context
from apps.documents import providers
from apps.documents.builtin import FINANCE_PROVIDER, FORWARDING_PROVIDER, KIND_TO_SUBJECT
from apps.documents.models import KINDS, IssuedDocument
from apps.documents.providers import DocumentProvider, register_provider, unregister_provider
from apps.documents.tests.test_services import _trip, cargo, issue, make_order
from apps.finance.tests.helpers import first_user, issue_invoice, make_carrier, make_client

pytestmark = pytest.mark.django_db

backfill = importlib.import_module(
    "apps.documents.migrations.0004_issued_document_subject_backfill"
)
I = "/api/documents/issued/"  # noqa: E741
DRIVERS = {7: SimpleNamespace(id=7, full_name="Иванов Иван Иванович", license="KZ-123")}


class DriversProvider(DocumentProvider):
    """Тестовый поставщик модуля drivers: письмо-справка по водителю (без моделей forwarding)."""

    module_code = "drivers"
    subject_types = ("drivers.driver",)
    kinds = ("letter",)

    def required_permission(self, kind):
        return "documents.update"  # право сверх documents.create

    def load_subject(self, subject_type, subject_id):
        return DRIVERS.get(subject_id)

    def build_context(self, kind, subject, language):
        return {
            "letter": {
                "recipient": subject.full_name,
                "subject": "Справка о водителе",
                "body": f"Водитель {subject.full_name}, удостоверение {subject.license}",
            }
        }


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()


@pytest.fixture
def drivers_provider():
    provider = register_provider(DriversProvider())
    yield provider
    unregister_provider(provider)


@pytest.fixture
def plan_with_drivers(db):
    Plan.objects.filter(code="start").update(
        modules=["logistics", "forwarding", "fleet", "finance", "documents", "drivers"]
    )


def docx_text(response):
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        return z.read("word/document.xml").decode()


# --- реестр -----------------------------------------------------------------------------------


def test_builtin_providers_cover_seven_kinds_without_overlap():
    assert set(KIND_TO_SUBJECT) == set(KINDS)
    registered = providers.all_providers()
    assert FORWARDING_PROVIDER in registered and FINANCE_PROVIDER in registered
    assert set(FORWARDING_PROVIDER.kinds) == {
        "contract",
        "order_request",
        "carrier_order",
        "cmr",
        "letter",
    }
    assert set(FINANCE_PROVIDER.kinds) == {"act", "invoice_print"}
    assert FORWARDING_PROVIDER.module_code == "forwarding"
    assert FINANCE_PROVIDER.module_code == "finance"
    assert set(providers.available_kinds(["forwarding", "finance"])) == set(KINDS)
    assert providers.available_kinds(["documents"]) == []


def test_register_validates_and_is_idempotent(drivers_provider):
    assert providers.all_providers().count(drivers_provider) == 1
    register_provider(drivers_provider)
    assert providers.all_providers().count(drivers_provider) == 1

    class NoModule(DocumentProvider):
        subject_types = ("x.y",)
        kinds = ("letter",)

    with pytest.raises(ValueError, match="module_code"):
        register_provider(NoModule())

    class BadKind(DriversProvider):
        kinds = ("brand_new_kind",)

    with pytest.raises(ValueError, match="brand_new_kind"):
        register_provider(BadKind())
    assert providers.find_provider("letter", "drivers.driver") is drivers_provider
    assert providers.find_provider("letter", "forwarding.order") is FORWARDING_PROVIDER


def test_core_providers_module_has_no_foreign_model_imports():
    import apps.documents.access as access_mod
    import apps.documents.builtin as builtin_mod
    import apps.documents.issuing as issuing_mod
    import apps.documents.providers as providers_mod

    for mod in (providers_mod, builtin_mod, access_mod):
        source = open(mod.__file__, encoding="utf-8").read()
        assert "apps.forwarding" not in source and "apps.finance" not in source, mod.__name__
    source = open(issuing_mod.__file__, encoding="utf-8").read()
    assert "apps.forwarding" not in source and "apps.finance" not in source


# --- прежние виды заполняют пару ---------------------------------------------------------------


def test_new_issuance_fills_pair_and_legacy_fields(company):
    client = make_client(company)
    order = make_order(company, client, consignments=[cargo()])
    invoice = issue_invoice(company, order=order)
    _, trip = _trip(company, make_carrier(company))
    cases = {
        "contract": ({"client": client}, "forwarding.client", client.pk),
        "order_request": ({"order": order}, "forwarding.order", order.pk),
        "carrier_order": ({"trip": trip}, "forwarding.trip", trip.pk),
        "cmr": ({"trip": trip}, "forwarding.trip", trip.pk),
        "act": ({"invoice": invoice}, "finance.invoice", invoice.pk),
        "invoice_print": ({"invoice": invoice}, "finance.invoice", invoice.pk),
    }
    for kind, (kw, subject_type, subject_id) in cases.items():
        doc = issue(company, kind, **kw)
        assert (doc.subject_type, doc.subject_id) == (subject_type, subject_id), kind
        legacy = {"contract": "client_id", "order_request": "order_id", "carrier_order": "trip_id",
                  "cmr": "trip_id", "act": "invoice_id", "invoice_print": "invoice_id"}[kind]  # fmt: skip
        assert getattr(doc, legacy) == subject_id, kind  # прежнее поле заполнено как раньше
    with_order = issue(
        company, "letter", order=order, letter={"recipient": "a", "subject": "b", "body": "c"}
    )
    assert (with_order.subject_type, with_order.subject_id) == ("forwarding.order", order.pk)
    free = issue(company, "letter", letter={"recipient": "a", "subject": "b", "body": "c"})
    assert free.subject_type is None and free.subject_id is None


# --- миграция данных -----------------------------------------------------------------------------


def test_backfill_is_deterministic_idempotent_and_reversible(company):
    client = make_client(company)
    order = make_order(company, client, consignments=[cargo()])
    invoice = issue_invoice(company, order=order)
    _, trip = _trip(company, make_carrier(company))
    docs = {
        "contract": issue(company, "contract", client=client),
        "order_request": issue(company, "order_request", order=order),
        "carrier_order": issue(company, "carrier_order", trip=trip),
        "cmr": issue(company, "cmr", trip=trip),
        "act": issue(company, "act", invoice=invoice),
        "invoice_print": issue(company, "invoice_print", invoice=invoice),
        "letter+order": issue(company, "letter", order=order, letter={"recipient": "a", "subject": "b", "body": "c"}),
        "letter": issue(company, "letter", letter={"recipient": "a", "subject": "b", "body": "c"}),
    }  # fmt: skip
    legacy_before = {}
    with tenant_context(company.id):
        for key, doc in docs.items():
            row = IssuedDocument.objects.get(pk=doc.pk)
            legacy_before[key] = (row.client_id, row.order_id, row.trip_id, row.invoice_id)
        IssuedDocument.objects.update(subject_type=None, subject_id=None)  # как до миграции
    backfill.run_backfill(django_apps)
    backfill.run_backfill(django_apps)  # повтор ничего не меняет
    expected = {
        "contract": ("forwarding.client", client.pk),
        "order_request": ("forwarding.order", order.pk),
        "carrier_order": ("forwarding.trip", trip.pk),
        "cmr": ("forwarding.trip", trip.pk),
        "act": ("finance.invoice", invoice.pk),
        "invoice_print": ("finance.invoice", invoice.pk),
        "letter+order": ("forwarding.order", order.pk),
        "letter": (None, None),
    }
    with tenant_context(company.id):
        for key, doc in docs.items():
            row = IssuedDocument.objects.get(pk=doc.pk)
            assert (row.subject_type, row.subject_id) == expected[key], key
            assert (row.client_id, row.order_id, row.trip_id, row.invoice_id) == legacy_before[key]
    backfill.run_reverse(django_apps)
    with tenant_context(company.id):
        assert IssuedDocument.objects.filter(subject_type__isnull=False).count() == 0
        assert IssuedDocument.objects.count() == len(docs)


def test_backfill_leaves_foreign_subjects_untouched(company, drivers_provider, plan_with_drivers):
    set_company_modules(company, ["documents", "drivers"])
    with tenant_context(company.id):
        from apps.documents.issuing import issue_for_subject

        doc = issue_for_subject("letter", "drivers.driver", 7, user=first_user(company))
    backfill.run_backfill(django_apps)
    with tenant_context(company.id):
        row = IssuedDocument.objects.get(pk=doc.pk)
        assert (row.subject_type, row.subject_id) == ("drivers.driver", 7)


def test_subject_index_exists():
    with connection.cursor() as cur:
        cur.execute("SELECT indexdef FROM pg_indexes WHERE indexname = 'issueddoc_subject_idx'")
        definition = cur.fetchone()[0]
    assert "company_id, subject_type, subject_id" in definition


# --- независимость documents: субъект водитель при выключенном forwarding -------------------------


def configure(company, modules):
    set_company_modules(company, modules)


def test_driver_document_without_forwarding_end_to_end(
    company, admin_client, drivers_provider, plan_with_drivers
):
    configure(company, ["documents", "drivers"])  # forwarding и finance выключены
    caps = admin_client.get("/api/documents/kinds/").json()
    assert caps["available_kinds"] == ["letter"]
    created = admin_client.post(
        I, {"kind": "letter", "subject_type": "drivers.driver", "subject_id": 7}, format="json"
    )
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["subject_type"] == "drivers.driver" and body["subject_id"] == 7
    assert body["client"] is None and body["order"] is None and body["number"].startswith("ИСХ-")
    # журнал
    listed = admin_client.get(I, {"subject_type": "drivers.driver", "subject_id": 7}).json()
    assert [d["id"] for d in listed["results"]] == [body["id"]]
    assert admin_client.get(I).json()["count"] == 1
    # снимок
    with tenant_context(company.id):
        snap = IssuedDocument.objects.get(pk=body["id"]).snapshot
    assert snap["letter"]["recipient"] == "Иванов Иван Иванович"
    assert snap["doc"]["number"] == body["number"] and snap["company"]["name"]
    # скачивание DOCX
    file = admin_client.get(f"{I}{body['id']}/download/", {"format": "docx"})
    assert file.status_code == 200 and "wordprocessingml" in file["Content-Type"]
    assert "Иванов Иван Иванович" in docx_text(file)


def test_forwarding_kinds_unavailable_until_forwarding_enabled(
    company, admin_client, drivers_provider, plan_with_drivers
):
    configure(company, ["documents", "drivers"])
    client = make_client(company)
    denied = admin_client.post(I, {"kind": "contract", "client": client.pk}, format="json")
    assert denied.status_code == 403 and denied.json()["code"] == "module_disabled"
    denied = admin_client.post(
        I, {"kind": "letter", "subject_type": "forwarding.order", "subject_id": 1}, format="json"
    )
    assert denied.status_code in (400, 403)  # встроенный поставщик отдаёт вид только прежним путём
    # включение forwarding и finance добавляет их виды без перенастройки
    configure(company, ["documents", "drivers", "logistics", "forwarding", "finance"])
    caps = admin_client.get("/api/documents/kinds/").json()
    assert set(caps["available_kinds"]) == set(KINDS)
    ok = admin_client.post(I, {"kind": "contract", "client": client.pk}, format="json")
    assert ok.status_code == 201 and ok.json()["subject_type"] == "forwarding.client"
    # отключение forwarding не ломает журнал документов других субъектов
    configure(company, ["documents", "drivers"])
    listed = admin_client.get(I)
    assert listed.status_code == 200 and listed.json()["count"] == 1


def test_finance_kinds_follow_finance_module(company, admin_client):
    invoice = issue_invoice(company, order=make_order(company, consignments=[cargo()]))
    set_company_modules(company, ["forwarding", "documents"])  # без finance
    denied = admin_client.post(I, {"kind": "act", "invoice": invoice.pk}, format="json")
    assert denied.status_code == 403 and denied.json()["code"] == "module_disabled"
    set_company_modules(company, ["forwarding", "finance", "documents"])
    ok = admin_client.post(I, {"kind": "act", "invoice": invoice.pk}, format="json")
    assert ok.status_code == 201 and ok.json()["subject_type"] == "finance.invoice"


def test_documents_disabled_closes_api_but_keeps_data(
    company, admin_client, drivers_provider, plan_with_drivers
):
    configure(company, ["documents", "drivers"])
    created = admin_client.post(
        I, {"kind": "letter", "subject_type": "drivers.driver", "subject_id": 7}, format="json"
    ).json()
    configure(company, ["drivers"])  # documents выключен
    for path in (I, f"{I}{created['id']}/", f"{I}{created['id']}/download/", "/api/documents/templates/",
                 "/api/documents/capabilities/"):  # fmt: skip
        response = admin_client.get(path)
        assert response.status_code == 403 and response.json()["code"] == "module_disabled", path
    post = admin_client.post(
        I, {"kind": "letter", "subject_type": "drivers.driver", "subject_id": 7}, format="json"
    )
    assert post.status_code == 403 and post.json()["code"] == "module_disabled"
    with tenant_context(company.id):
        assert IssuedDocument.objects.filter(pk=created["id"]).exists()  # данные остаются
    configure(company, ["documents", "drivers"])  # повторное включение возвращает доступ
    again = admin_client.get(f"{I}{created['id']}/download/", {"format": "docx"})
    assert again.status_code == 200 and "Иванов" in docx_text(again)


def test_subject_request_validation(company, admin_client, drivers_provider, plan_with_drivers):
    configure(company, ["documents", "drivers"])
    bad = [
        {"kind": "letter", "subject_type": "drivers.driver"},  # нет subject_id
        {"kind": "letter", "subject_id": 7},  # нет subject_type
        {"kind": "letter", "subject_type": "drivers.driver", "subject_id": 7, "order": 1},
        {"kind": "letter", "subject_type": "drivers.nobody", "subject_id": 7},  # нет поставщика
        {
            "kind": "contract",
            "subject_type": "drivers.driver",
            "subject_id": 7,
        },  # вид не поставляется
    ]
    for payload in bad:
        response = admin_client.post(I, payload, format="json")
        assert response.status_code == 400, payload
    missing = admin_client.post(
        I, {"kind": "letter", "subject_type": "drivers.driver", "subject_id": 999}, format="json"
    )
    assert missing.status_code == 400 and missing.json()["code"] == "source_not_ready"
    with tenant_context(company.id):
        assert IssuedDocument.objects.count() == 0


def test_provider_permission_is_enforced(company, drivers_provider, plan_with_drivers):
    from rest_framework.test import APIClient

    from apps.core.api.auth import issue_tokens
    from apps.core.models import Membership, Role, User
    from apps.core.tenancy import set_current_company

    configure(company, ["documents", "drivers"])
    user = User.objects.create_user(email="creator@prov.kz", password="x")
    with tenant_context(company.id):
        role = Role.objects.create(
            name="Только выдача", permissions=["documents.view", "documents.create"]
        )
    Membership.objects.create(user=user, company=company, role=role, is_active=True)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    set_current_company(None)
    payload = {"kind": "letter", "subject_type": "drivers.driver", "subject_id": 7}
    assert api.post(I, payload, format="json").status_code == 403  # нет documents.update
    with tenant_context(company.id):
        role.permissions = [*role.permissions, "documents.update"]
        role.save(update_fields=["permissions"])
    assert api.post(I, payload, format="json").status_code == 201


def test_subject_documents_are_isolated_between_companies(
    company, admin_client, make_company, drivers_provider, plan_with_drivers
):
    configure(company, ["documents", "drivers"])
    created = admin_client.post(
        I, {"kind": "letter", "subject_type": "drivers.driver", "subject_id": 7}, format="json"
    ).json()
    other, _, other_api = make_company("Other docs", modules=["forwarding"])
    set_company_modules(other, ["documents", "drivers"])
    assert other_api.get(I).json()["count"] == 0
    assert other_api.get(f"{I}{created['id']}/").status_code == 404
