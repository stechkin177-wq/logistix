"""API документов: шаблоны, журнал, capabilities, права, изоляция, лимиты."""

import io
import zipfile
from urllib.parse import quote

import pytest
from django.core.cache import cache

from apps.core.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.core.tests.test_rls import app_role
from apps.documents import catalog, pdf
from apps.documents.api.http import PdfDownloadThrottle, TemplateUploadThrottle
from apps.documents.errors import DocumentError
from apps.documents.models import DocumentTemplate, IssuedDocument
from apps.documents.tests.test_services import (
    _trip,
    cargo,
    docx_with_text,
    make_order,
)
from apps.finance.tests.helpers import issue_invoice, make_carrier, make_client
from apps.forwarding.tests.test_parties import client_with_role

pytestmark = pytest.mark.django_db

T = "/api/documents/templates/"
I = "/api/documents/issued/"  # noqa: E741
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()


def tid(company, kind="act", language="ru"):
    with tenant_context(company.id):
        return DocumentTemplate.objects.get(kind=kind, language=language, is_active=True).pk


def upload(api, pk, data, name="t.docx"):
    f = io.BytesIO(data)
    f.name = name
    return api.post(f"{T}{pk}/versions/", {"file": f}, format="multipart")


def sources(company):
    """Источники для всех 7 видов: {kind: тело POST}."""
    client = make_client(company)
    order = make_order(company, client, consignments=[cargo()])
    invoice = issue_invoice(company, order=order)
    _, trip = _trip(company, make_carrier(company))
    return {
        "contract": {"client": client.pk},
        "order_request": {"order": order.pk},
        "carrier_order": {"trip": trip.pk},
        "act": {"invoice": invoice.pk},
        "invoice_print": {"invoice": invoice.pk},
        "cmr": {"trip": trip.pk},
        "letter": {
            "letter": {"recipient": "ТОО Ромашка", "subject": "Тема", "body": "Текст письма"},
            "order": order.pk,
        },
    }


# --- шаблоны ----------------------------------------------------------------------------------


def test_templates_list_has_starter_set(admin_client):
    r = admin_client.get(T)
    assert r.status_code == 200
    assert {t["kind"] for t in r.data} == set(catalog.KINDS)
    t = r.data[0]
    assert t["versions_count"] == 1 and t["is_active"]
    cv = t["current_version"]
    assert cv["number"] == 1 and cv["is_starter"] and len(cv["sha256"]) == 64
    assert set(cv) == {"id", "number", "sha256", "is_starter", "uploaded_by", "created_at"}


def test_upload_version_and_download(admin_client, company):
    pk = tid(company)
    data = docx_with_text("Акт {{ doc.number }}", "act")
    r = upload(admin_client, pk, data)
    assert r.status_code == 201, r.content
    assert r.data["current_version"]["number"] == 2 and r.data["versions_count"] == 2
    assert not r.data["current_version"]["is_starter"]
    d = admin_client.get(f"{T}{pk}/download/")
    assert d.status_code == 200 and d.content == data and d["Content-Type"] == DOCX
    assert d["Cache-Control"] == "private, no-store"
    assert "filename*=UTF-8''" in d["Content-Disposition"]


def test_upload_invalid_is_400_with_code(admin_client, company, monkeypatch):
    pk = tid(company)
    r = upload(admin_client, pk, b"not a docx")
    assert r.status_code == 400 and r.data["code"] == "template_invalid"
    r = upload(admin_client, pk, docx_with_text("{{ unknown.label }}", "act"))
    assert r.status_code == 400 and r.data["code"] == "template_invalid"
    r = upload(admin_client, pk, b"x" * (2 * 1024 * 1024 + 1))
    assert r.status_code == 400 and r.data["code"] == "template_too_large"
    r = admin_client.post(f"{T}{pk}/versions/", {}, format="multipart")
    assert r.status_code == 400
    assert admin_client.get(T).data[0]["versions_count"] >= 1


def test_render_unavailable_maps_to_503(admin_client, company, monkeypatch):
    def boom(*a, **k):
        raise DocumentError("render_unavailable", "нет", status_code=503)

    monkeypatch.setattr("apps.documents.services.engine.validate_upload", boom)
    r = upload(admin_client, tid(company), docx_with_text("x", "act"))
    assert r.status_code == 503 and r.data["code"] == "render_unavailable"


def test_reset_returns_starter(admin_client, company):
    pk = tid(company)
    upload(admin_client, pk, docx_with_text("свой {{ doc.number }}", "act"))
    r = admin_client.post(f"{T}{pk}/reset/")
    assert r.status_code == 200
    assert r.data["current_version"]["number"] == 3 and r.data["current_version"]["is_starter"]


def test_patch_name_and_active_rules(admin_client, company):
    pk = tid(company)
    r = admin_client.patch(f"{T}{pk}/", {"name": "Новое имя"}, format="json")
    assert r.status_code == 200 and r.data["name"] == "Новое имя"
    r = admin_client.patch(f"{T}{pk}/", {"name": "  "}, format="json")
    assert r.status_code == 400
    r = admin_client.patch(f"{T}{pk}/", {"is_active": False}, format="json")
    assert r.status_code == 200 and r.data["is_active"] is False
    with tenant_context(company.id):
        other = DocumentTemplate.objects.create(
            kind="act", language="ru", name="Второй", is_active=True
        )
    r = admin_client.patch(f"{T}{pk}/", {"is_active": True}, format="json")
    assert r.status_code == 400
    assert other.pk


def test_placeholders_endpoint(admin_client):
    r = admin_client.get(f"{T}placeholders/?kind=act")
    assert r.status_code == 200
    assert [p["name"] for p in r.data] == [p["name"] for p in catalog.placeholders("act")]
    assert admin_client.get(f"{T}placeholders/?kind=zzz").status_code == 400
    assert admin_client.get(f"{T}placeholders/").status_code == 400


# --- выдача -----------------------------------------------------------------------------------


def test_issue_requires_exactly_one_source(admin_client, company):
    s = sources(company)
    r = admin_client.post(I, {"kind": "act"}, format="json")
    assert r.status_code == 400
    r = admin_client.post(
        I, {"kind": "act", **s["act"], "order": s["letter"]["order"]}, format="json"
    )
    assert r.status_code == 400
    r = admin_client.post(I, {"kind": "contract", **s["act"]}, format="json")
    assert r.status_code == 400
    r = admin_client.post(I, {"kind": "nope"}, format="json")
    assert r.status_code == 400
    r = admin_client.post(I, {"kind": "letter", "client": 1, "letter": {}}, format="json")
    assert r.status_code == 400


def test_issue_each_kind_and_download_docx(admin_client, company):
    for kind, body in sources(company).items():
        r = admin_client.post(I, {"kind": kind, **body}, format="json")
        assert r.status_code == 201, (kind, r.content)
        assert r.data["kind"] == kind and r.data["template_version"]["number"] == 1
        d = admin_client.get(f"{I}{r.data['id']}/download/")
        assert d.status_code == 200 and d["Content-Type"] == DOCX
        cd = d["Content-Disposition"]
        assert cd.startswith('attachment; filename="') and "filename*=UTF-8''" in cd
        assert quote(r.data["number"], safe="") in cd
        assert zipfile.is_zipfile(io.BytesIO(d.content))
        assert d["Cache-Control"] == "private, no-store"
    r = admin_client.post(
        I,
        {"kind": "letter", "letter": {"recipient": "", "subject": "а", "body": "б"}},
        format="json",
    )
    assert r.status_code == 400 and r.data["code"] == "letter_invalid"


def test_issue_source_not_ready_and_template_missing(admin_client, company):
    carrier_less = _trip(company, None)[1]
    r = admin_client.post(I, {"kind": "carrier_order", "trip": carrier_less.pk}, format="json")
    assert r.status_code == 400 and r.data["code"] == "source_not_ready"
    with tenant_context(company.id):
        DocumentTemplate.objects.filter(kind="contract").update(is_active=False)
    client = make_client(company)
    r = admin_client.post(I, {"kind": "contract", "client": client.pk}, format="json")
    assert r.status_code == 400 and r.data["code"] == "template_missing"


def test_download_pdf_unavailable_is_503_but_docx_ok(admin_client, company, monkeypatch):
    doc = admin_client.post(
        I, {"kind": "contract", "client": make_client(company).pk}, format="json"
    ).data

    def unavailable(_):
        raise DocumentError("pdf_unavailable", "нет", status_code=503)

    monkeypatch.setattr(pdf, "convert_to_pdf", unavailable)
    r = admin_client.get(f"{I}{doc['id']}/download/?format=pdf")
    assert r.status_code == 503 and r.data["code"] == "pdf_unavailable"
    assert admin_client.get(f"{I}{doc['id']}/download/?format=docx").status_code == 200
    assert admin_client.get(f"{I}{doc['id']}/download/?format=odt").status_code == 400
    monkeypatch.setattr(pdf, "convert_to_pdf", lambda d: b"%PDF-fake")
    r = admin_client.get(f"{I}{doc['id']}/download/?format=pdf")
    assert r.status_code == 200 and r["Content-Type"] == "application/pdf"
    assert r.content == b"%PDF-fake"


def test_capabilities_flag(admin_client, monkeypatch):
    monkeypatch.setattr(pdf, "pdf_available", lambda: False)
    assert admin_client.get("/api/documents/capabilities/").data == {"pdf_available": False}
    monkeypatch.setattr(pdf, "pdf_available", lambda: True)
    assert admin_client.get("/api/documents/capabilities/").data == {"pdf_available": True}


def test_issued_has_no_patch_or_delete(admin_client, company):
    d = admin_client.post(
        I, {"kind": "contract", "client": make_client(company).pk}, format="json"
    ).data
    assert admin_client.patch(f"{I}{d['id']}/", {}, format="json").status_code == 405
    assert admin_client.delete(f"{I}{d['id']}/").status_code == 405
    assert admin_client.put(f"{I}{d['id']}/", {}, format="json").status_code == 405
    assert admin_client.get(f"{I}{d['id']}/").status_code == 200


# --- права ------------------------------------------------------------------------------------


def test_permissions_matrix(admin_client, company):
    s = sources(company)
    _, manager = client_with_role(company, "Менеджер")
    _, viewer = client_with_role(company, "Наблюдатель")
    _, mechanic = client_with_role(company, "Механик")
    _, dispatcher = client_with_role(company, "Диспетчер")
    pk = tid(company)
    data = docx_with_text("Акт {{ doc.number }}", "act")

    # Менеджер: читает и выдаёт, но не меняет шаблоны
    assert manager.get(T).status_code == 200
    assert manager.post(I, {"kind": "act", **s["act"]}, format="json").status_code == 201
    assert upload(manager, pk, data).status_code == 403
    assert manager.post(f"{T}{pk}/reset/").status_code == 403
    assert manager.patch(f"{T}{pk}/", {"name": "x"}, format="json").status_code == 403
    # Наблюдатель: только чтение
    assert viewer.get(T).status_code == 200 and viewer.get(I).status_code == 200
    assert viewer.get("/api/documents/capabilities/").status_code == 200
    assert viewer.get(f"{T}{pk}/download/").status_code == 200
    assert viewer.post(I, {"kind": "act", **s["act"]}, format="json").status_code == 403
    # Механик: 403 на всё
    for call in (
        lambda: mechanic.get(T),
        lambda: mechanic.get(I),
        lambda: mechanic.get(f"{T}placeholders/?kind=act"),
        lambda: mechanic.get(f"{T}{pk}/download/"),
        lambda: mechanic.get("/api/documents/capabilities/"),
        lambda: mechanic.post(I, {"kind": "contract", **s["contract"]}, format="json"),
        lambda: upload(mechanic, pk, data),
    ):
        assert call().status_code == 403
    # Диспетчер: нет finance.view - нельзя выдать акт и печатную форму счёта
    assert dispatcher.post(I, {"kind": "act", **s["act"]}, format="json").status_code == 403
    assert (
        dispatcher.post(I, {"kind": "invoice_print", **s["act"]}, format="json").status_code == 403
    )
    assert dispatcher.post(I, {"kind": "cmr", **s["cmr"]}, format="json").status_code == 201
    # отключение шаблона - documents.delete (есть только у администратора)
    assert manager.patch(f"{T}{pk}/", {"is_active": False}, format="json").status_code == 403
    assert admin_client.patch(f"{T}{pk}/", {"is_active": False}, format="json").status_code == 200


def test_unauthenticated_is_401(api_client):
    assert api_client.get(T).status_code == 401


# --- изоляция ---------------------------------------------------------------------------------


def test_foreign_company_ids_rejected(admin_client, company, make_company):
    other, _, _ = make_company("Чужая")
    s = sources(other)
    for kind in ("contract", "order_request", "carrier_order", "act", "invoice_print", "cmr"):
        r = admin_client.post(I, {"kind": kind, **s[kind]}, format="json")
        assert r.status_code in (400, 404), (kind, r.status_code)
    r = admin_client.post(I, {"kind": "letter", **s["letter"]}, format="json")
    assert r.status_code in (400, 404)
    with tenant_context(other.id):
        assert IssuedDocument.objects.count() == 0


def test_company_isolation_list_download_template(admin_client, company, make_company):
    other, _, other_api = make_company("Чужая")
    foreign_t = tid(other)
    assert admin_client.get(f"{T}{foreign_t}/download/").status_code == 404
    assert admin_client.post(f"{T}{foreign_t}/reset/").status_code == 404
    assert upload(admin_client, foreign_t, docx_with_text("x", "act")).status_code == 404
    assert admin_client.patch(f"{T}{foreign_t}/", {"name": "x"}, format="json").status_code == 404
    assert {t["id"] for t in admin_client.get(T).data}.isdisjoint(
        {t["id"] for t in other_api.get(T).data}
    )
    made = other_api.post(
        I, {"kind": "contract", "client": make_client(other).pk}, format="json"
    ).data
    assert admin_client.get(I).data["count"] == 0
    assert admin_client.get(f"{I}{made['id']}/").status_code == 404
    assert admin_client.get(f"{I}{made['id']}/download/").status_code == 404


def test_download_after_order_deleted(admin_client, company):
    order = make_order(company, consignments=[cargo()])
    d = admin_client.post(I, {"kind": "order_request", "order": order.pk}, format="json").data
    with tenant_context(company.id):
        order.delete()
    assert admin_client.get(f"{I}{d['id']}/download/").status_code == 200
    got = admin_client.get(f"{I}{d['id']}/")
    assert got.status_code == 200 and got.data["order"]["number"] == order.number


# --- список -----------------------------------------------------------------------------------


def test_filters_and_search(admin_client, company):
    s = sources(company)
    ids = {}
    for kind in ("contract", "act", "cmr"):
        ids[kind] = admin_client.post(I, {"kind": kind, **s[kind]}, format="json").data
    assert admin_client.get(I).data["count"] == 3
    assert admin_client.get(I + "?kind=act").data["count"] == 1
    assert admin_client.get(I + f"?client={s['contract']['client']}").data["count"] == 2
    assert admin_client.get(I + f"?invoice={s['act']['invoice']}").data["count"] == 1
    assert admin_client.get(I + f"?trip={s['cmr']['trip']}").data["count"] == 1
    assert admin_client.get(I + "?search=" + ids["act"]["number"][:6]).data["count"] == 1
    assert admin_client.get(I + "?date_from=2999-01-01").data["count"] == 0
    assert admin_client.get(I + "?date_to=2000-01-01").data["count"] == 0
    assert admin_client.get(I + "?date_from=2000-01-01&date_to=2999-01-01").data["count"] == 3
    assert admin_client.get(I + "?kind=zzz").status_code == 400
    assert admin_client.get(I + "?date_from=abc").status_code == 400
    assert admin_client.get(I + "?client=abc").status_code == 400
    assert admin_client.get(I + "?page_size=2").data["results"].__len__() == 2


def test_query_count_stable_for_list(admin_client, company, django_assert_max_num_queries):
    client = make_client(company)
    for _ in range(30):
        r = admin_client.post(I, {"kind": "contract", "client": client.pk}, format="json")
        assert r.status_code == 201
    with django_assert_max_num_queries(12):
        r = admin_client.get(I + "?page_size=50")
    assert r.status_code == 200 and len(r.data["results"]) == 30
    with django_assert_max_num_queries(12):
        assert len(admin_client.get(T).data) == 7


# --- аудит, RLS, лимиты -----------------------------------------------------------------------


def test_audit_written_for_issue_and_version(admin_client, company):
    pk = tid(company)
    upload(admin_client, pk, docx_with_text("x {{ doc.number }}", "act"))
    d = admin_client.post(
        I, {"kind": "contract", "client": make_client(company).pk}, format="json"
    ).data
    admin_client.patch(f"{T}{pk}/", {"name": "Другое"}, format="json")
    with tenant_context(company.id):
        rows = list(AuditLog.objects.all())
    assert any(r.action == "create" and r.object_id == str(d["id"]) for r in rows)
    assert any(r.action == "update" and r.object_id == str(pk) for r in rows)
    assert sum(1 for r in rows if r.action == "update" and r.object_id == str(pk)) >= 2


def test_rls_role_flow(admin_client, company):
    pk = tid(company)
    client = make_client(company)
    with app_role():
        r = upload(admin_client, pk, docx_with_text("x {{ doc.number }}", "act"))
        assert r.status_code == 201, r.content
        r = admin_client.post(I, {"kind": "contract", "client": client.pk}, format="json")
        assert r.status_code == 201, r.content
        assert admin_client.get(f"{I}{r.data['id']}/download/").status_code == 200
        assert admin_client.post(f"{T}{pk}/reset/").status_code == 200
        assert admin_client.get(I).data["count"] == 1


def test_upload_throttled_per_company(admin_client, company, make_company, monkeypatch):
    monkeypatch.setitem(TemplateUploadThrottle.THROTTLE_RATES, "document_upload", "2/hour")
    pk = tid(company)
    bad = b"not a docx"
    assert upload(admin_client, pk, bad).status_code == 400
    assert upload(admin_client, pk, bad).status_code == 400
    r = upload(admin_client, pk, bad)
    assert r.status_code == 429 and r.data["code"] == "throttled"
    other, _, other_api = make_company("Другая")
    assert upload(other_api, tid(other), bad).status_code == 400  # у другой компании свой счётчик


def test_pdf_download_throttled_per_company(admin_client, company, monkeypatch):
    monkeypatch.setitem(PdfDownloadThrottle.THROTTLE_RATES, "document_pdf", "2/min")
    monkeypatch.setattr(pdf, "convert_to_pdf", lambda d: b"%PDF")
    d = admin_client.post(
        I, {"kind": "contract", "client": make_client(company).pk}, format="json"
    ).data
    url = f"{I}{d['id']}/download/"
    assert admin_client.get(url + "?format=pdf").status_code == 200
    assert admin_client.get(url + "?format=pdf").status_code == 200
    assert admin_client.get(url + "?format=pdf").status_code == 429
    assert admin_client.get(url).status_code == 200  # docx не ограничивается
