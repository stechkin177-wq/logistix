"""Сквозной сценарий документов под ролью приложения (RLS): заказ и счёт -> выдача ->
скачивание -> свои версии шаблонов -> неизменность выданного после правок."""

import io
import zipfile

import pytest

from apps.core.tenancy import tenant_context
from apps.core.tests.test_rls import app_role
from apps.documents import pdf
from apps.documents.models import DocumentTemplate
from apps.documents.tests.test_services import cargo, docx_with_text, make_order
from apps.finance.tests.helpers import issue_invoice, make_client

pytestmark = pytest.mark.django_db

T = "/api/documents/templates/"
I = "/api/documents/issued/"  # noqa: E741


def _tid(company, kind):
    with tenant_context(company.id):
        return DocumentTemplate.objects.get(kind=kind, language="ru", is_active=True).pk


def _upload(api, pk, text):
    f = io.BytesIO(docx_with_text(text))
    f.name = "t.docx"
    r = api.post(f"{T}{pk}/versions/", {"file": f}, format="multipart")
    assert r.status_code == 201, r.content


def _xml(content):
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        return z.read("word/document.xml").decode().replace("\xa0", " ")


def _issue(api, body):
    r = api.post(I, body, format="json")
    assert r.status_code == 201, r.content
    return r.data["id"]


def _docx(api, pk):
    r = api.get(f"{I}{pk}/download/")
    assert r.status_code == 200, r.content
    return r.content


def test_full_flow(admin_client, company):
    client = make_client(company, "ТОО Сквозной")
    order = make_order(
        company, client, client_rate="1500.00", consignments=[cargo(), cargo("Соль")]
    )
    invoice = issue_invoice(company, order=order)

    with app_role():
        _upload(
            admin_client,
            _tid(company, "order_request"),
            "Заявка {{ doc.number }} {{ client.name }}",
        )
        request_id = _issue(admin_client, {"kind": "order_request", "order": order.pk})
        old_act = _issue(admin_client, {"kind": "act", "invoice": invoice.pk})
        print_id = _issue(admin_client, {"kind": "invoice_print", "invoice": invoice.pk})

        request_before = _docx(admin_client, request_id)
        old_act_before = _docx(admin_client, old_act)
        assert f"Заявка {order.number} ТОО Сквозной" in _xml(request_before)
        assert _docx(admin_client, print_id)[:2] == b"PK"

        # своя версия акта: новый акт - по ней, выданный раньше - по старой
        _upload(admin_client, _tid(company, "act"), "НОВЫЙ АКТ {{ doc.number }}")
        new_act = _issue(admin_client, {"kind": "act", "invoice": invoice.pk})
        assert "НОВЫЙ АКТ АКТ-" in _xml(_docx(admin_client, new_act))
        assert _xml(_docx(admin_client, old_act)) == _xml(old_act_before)
        assert "НОВЫЙ АКТ" not in _xml(old_act_before)

        # правка ставки и клиента не меняет выданный документ
        with tenant_context(company.id):
            type(order).objects.filter(pk=order.pk).update(client_rate="1.00")
            client.name = "Другое имя"
            client.save()
        assert _xml(_docx(admin_client, request_id)) == _xml(request_before)
        assert admin_client.get(I).data["count"] == 4

        if pdf.pdf_available():
            r = admin_client.get(f"{I}{request_id}/download/?format=pdf")
            assert r.status_code == 200
            assert r.content[:5] == b"%PDF-"
