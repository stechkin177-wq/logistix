"""Сервисы документов: версии, откат, выдача, сборка файла."""

import io
import threading
import zipfile
from datetime import datetime
from datetime import timezone as dt_tz

import pytest
import time_machine
from django.db import connection, transaction

from apps.core.numbering.models import NumberingRule
from apps.core.tenancy import tenant_context
from apps.documents import pdf, services
from apps.documents.errors import DocumentError
from apps.documents.models import DocumentTemplate, IssuedDocument
from apps.documents.starter import starter_bytes
from apps.finance.models import Invoice
from apps.finance.tests.helpers import (
    cur,
    first_user,
    issue_invoice,
    make_carrier,
    make_client,
)
from apps.forwarding.tests.test_orders import _svc_cargo
from apps.forwarding.tests.test_orders import make_order as _make_order
from apps.forwarding.tests.test_trips import svc_create

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 11, 1, 10, 0, tzinfo=dt_tz.utc)
WHEN = datetime(2026, 6, 2, 9, 0, tzinfo=dt_tz.utc)


@pytest.fixture(autouse=True)
def frozen():
    with time_machine.travel(NOW, tick=False):
        yield


def code(exc):
    return exc.value.detail.code


def make_order(company, client=None, **extra):
    client = client or make_client(company)
    return _make_order(company, client, currency=cur(company), **extra)


def cargo(name="Мука"):
    return _svc_cargo(
        name=name,
        weight_kg="100",
        volume_m3="1",
        pallets=1,
        points=[
            {"kind": "load", "window_from": WHEN, "city": "Шымкент"},
            {"kind": "unload", "window_from": WHEN, "city": "Алматы"},
        ],
    )


def tmpl(company, kind="act", language="ru"):
    with tenant_context(company.id):
        return DocumentTemplate.objects.get(kind=kind, language=language, is_active=True)


def counter(company, kind):
    with tenant_context(company.id):
        return NumberingRule.objects.get(kind=kind).next_value


def docx_with_text(text, kind="letter"):
    """Стартовый шаблон, где один абзац заменён заданным текстом."""
    from docx import Document

    doc = Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def text_of(docx_bytes):
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
        return z.read("word/document.xml").decode()


def issue(company, kind, **kw):
    with tenant_context(company.id):
        return services.issue_document(kind, user=first_user(company), **kw)


def render(company, doc, fmt="docx"):
    with tenant_context(company.id):
        doc = IssuedDocument.objects.get(pk=doc.pk)
        return services.render_issued(doc, fmt)


# --- версии -----------------------------------------------------------------------------------


def test_upload_version_increments_and_switches_current(company):
    t = tmpl(company)
    data = docx_with_text("Акт {{ doc.number }}")
    with tenant_context(company.id):
        v = services.upload_version(t, data, first_user(company))
        t.refresh_from_db()
        assert v.number == 2 and not v.is_starter and len(v.sha256) == 64
        assert t.current_version_id == v.pk
        assert bytes(v.content) == data


def test_upload_invalid_does_not_create_version(company):
    t = tmpl(company)
    with tenant_context(company.id):
        before = t.versions.count()
        with pytest.raises(DocumentError) as exc:
            services.upload_version(t, b"not a docx", first_user(company))
        assert code(exc) == "template_invalid"
        with pytest.raises(DocumentError):
            services.upload_version(t, docx_with_text("{{ unknown.label }}"), first_user(company))
        assert t.versions.count() == before


def test_reset_to_starter_creates_new_starter_version(company):
    t = tmpl(company)
    with tenant_context(company.id):
        services.upload_version(t, docx_with_text("свой {{ doc.number }}"), first_user(company))
        v = services.reset_to_starter(t, first_user(company))
        t.refresh_from_db()
        assert v.number == 3 and v.is_starter and t.current_version_id == v.pk
        assert bytes(v.content) == starter_bytes("act", "ru")


# --- выдача -----------------------------------------------------------------------------------


def test_issue_order_request_uses_order_number_no_counter_spent(company):
    order = make_order(company, consignments=[cargo()])
    before = {k: counter(company, k) for k in ("order", "contract", "act", "letter")}
    doc = issue(company, "order_request", order=order)
    assert doc.number == order.number and doc.order_id == order.pk
    assert {k: counter(company, k) for k in before} == before


def test_issue_act_numbers_sequentially(company):
    invoice = issue_invoice(company)
    first = issue(company, "act", invoice=invoice)
    second = issue(company, "act", invoice=invoice)
    assert first.number == "АКТ-2026-00001" and second.number == "АКТ-2026-00002"
    assert first.invoice_id == invoice.pk and first.issue_date.isoformat() == "2026-11-01"
    assert first.snapshot["doc"]["number"] == first.number


def test_issue_invoice_print_uses_invoice_number(company):
    invoice = issue_invoice(company)
    doc = issue(company, "invoice_print", invoice=invoice)
    assert doc.number == invoice.number


def test_issue_act_requires_issued_invoice(company):
    order = make_order(company)
    from apps.finance import invoices as svc
    from apps.finance.tests.helpers import add_line, vat

    with tenant_context(company.id):
        line = add_line(company, order, income=10)
        draft = svc.create_draft(
            direction="out",
            party=order.client,
            order=order,
            currency=cur(company),
            vat_rate=vat(company, "0"),
            due_date=None,
            items=[{"title": "x", "amount_net": 10, "line": line}],
            user=first_user(company),
        )
    with pytest.raises(DocumentError) as exc:
        issue(company, "act", invoice=draft)
    assert code(exc) == "source_not_ready"
    with tenant_context(company.id):
        issued = svc.issue(draft, user=first_user(company))
        svc.cancel(issued, user=first_user(company))
        issued.refresh_from_db()
    with pytest.raises(DocumentError) as exc:
        issue(company, "act", invoice=issued)
    assert code(exc) == "source_not_ready"
    assert counter(company, "act") == 1


def test_issue_incoming_invoice_not_ready(company):
    carrier = make_carrier(company)
    invoice = issue_invoice(company, direction="in", carrier=carrier)
    with pytest.raises(DocumentError) as exc:
        issue(company, "act", invoice=invoice)
    assert code(exc) == "source_not_ready"


def _trip(company, carrier):
    order = make_order(company, consignments=[cargo()])
    from apps.forwarding.models import Consignment

    with tenant_context(company.id):
        ids = list(Consignment.objects.filter(order=order).values_list("pk", flat=True))
    return order, svc_create(company, ids, carrier)


def test_issue_carrier_order_requires_carrier(company):
    _, trip = _trip(company, None)
    with pytest.raises(DocumentError) as exc:
        issue(company, "carrier_order", trip=trip)
    assert code(exc) == "source_not_ready"
    _, trip2 = _trip(company, make_carrier(company))
    doc = issue(company, "carrier_order", trip=trip2)
    assert doc.number == "ЗП-2026-00001" and doc.trip_id == trip2.pk


def test_issue_cmr_and_contract(company):
    _, trip = _trip(company, make_carrier(company))
    assert issue(company, "cmr", trip=trip).number == "CMR-2026-00001"
    client = make_client(company)
    assert issue(company, "contract", client=client).number == "Д-2026-00001"


def test_missing_or_deleted_source_is_not_ready(company):
    order = make_order(company)
    with tenant_context(company.id):
        order.delete()
    with pytest.raises(DocumentError) as exc:
        issue(company, "order_request", order=order)
    assert code(exc) == "source_not_ready"
    with pytest.raises(DocumentError) as exc:
        issue(company, "act")
    assert code(exc) == "source_not_ready"


def test_issue_requires_active_template(company):
    t = tmpl(company, "contract")
    with tenant_context(company.id):
        t.is_active = False
        t.save(update_fields=["is_active"])
    client = make_client(company)
    with pytest.raises(DocumentError) as exc:
        issue(company, "contract", client=client)
    assert code(exc) == "template_missing"
    assert counter(company, "contract") == 1


def test_language_fallback_to_ru(company):
    from apps.core.models import Company

    Company.objects.filter(pk=company.pk).update(language="kk")
    client = make_client(company)
    doc = issue(company, "contract", client=client)
    assert doc.language == "ru"
    assert issue(company, "contract", client=client, language="kk").language == "ru"


@pytest.mark.parametrize(
    "letter",
    [
        None,
        {},
        {"recipient": "ТОО", "subject": "", "body": "текст"},
        {"recipient": "ТОО", "subject": "Тема", "body": "  "},
        {"recipient": "", "subject": "Тема", "body": "текст"},
        {"recipient": "ТОО", "subject": "Тема", "body": "я" * 20001},
        {"recipient": "ТОО", "subject": "Т" * 256, "body": "текст"},
    ],
)
def test_letter_validation(company, letter):
    with pytest.raises(DocumentError) as exc:
        issue(company, "letter", letter=letter)
    assert code(exc) == "letter_invalid"
    assert counter(company, "letter") == 1


def test_letter_ok_at_limit(company):
    doc = issue(
        company, "letter", letter={"recipient": "ТОО", "subject": "Тема", "body": "я" * 20000}
    )
    assert doc.number == "ИСХ-2026-00001"
    assert doc.snapshot["letter"]["subject"] == "Тема"


# --- снимок и версии ---------------------------------------------------------------------------


def test_snapshot_unchanged_after_order_edit_and_delete(company):
    t = tmpl(company, "order_request")
    with tenant_context(company.id):
        services.upload_version(
            t,
            docx_with_text("Ставка {{ order.rate }} клиент {{ client.name }}"),
            first_user(company),
        )
    client = make_client(company, "ТОО Снимок")
    order = make_order(company, client, client_rate="1234567.89", consignments=[cargo()])
    doc = issue(company, "order_request", order=order)
    before = text_of(render(company, doc)[0])
    assert "1 234 567.89" in before.replace("\xa0", " ") or "1234567" in before.replace(" ", "")
    assert "ТОО Снимок" in before
    with tenant_context(company.id):
        type(order).objects.filter(pk=order.pk).update(client_rate="1.00")
        order.refresh_from_db()
        order.delete()
        client.name = "Другое имя"
        client.save()
    assert text_of(render(company, doc)[0]) == before


def test_old_document_keeps_old_template_version(company):
    t = tmpl(company, "letter")
    letter = {"recipient": "ТОО", "subject": "Тема", "body": "Текст"}
    with tenant_context(company.id):
        services.upload_version(
            t, docx_with_text("СТАРОЕ {{ letter.subject }}"), first_user(company)
        )
    old = issue(company, "letter", letter=letter)
    with tenant_context(company.id):
        services.upload_version(
            t, docx_with_text("НОВОЕ {{ letter.subject }}"), first_user(company)
        )
    new = issue(company, "letter", letter=letter)
    assert "СТАРОЕ Тема" in text_of(render(company, old)[0])
    assert "НОВОЕ Тема" in text_of(render(company, new)[0])
    assert old.template_version_id != new.template_version_id


def test_render_pdf_goes_through_converter(company, monkeypatch):
    doc = issue(company, "contract", client=make_client(company))
    monkeypatch.setattr(pdf, "convert_to_pdf", lambda data: b"%PDF-fake" + data[:2])
    content, ctype, name = render(company, doc, "pdf")
    assert content.startswith(b"%PDF-fake") and ctype == "application/pdf"
    assert name.endswith(".pdf")
    with pytest.raises(ValueError):
        render(company, doc, "xls")


def test_audit_written(company):
    from apps.core.audit.models import AuditLog

    doc = issue(company, "contract", client=make_client(company))
    with tenant_context(company.id):
        row = AuditLog.objects.get(action="create", object_type="documents.issueddocument")
        assert row.object_id == str(doc.pk)


# --- имя файла ---------------------------------------------------------------------------------


def test_filename_is_safe():
    name = services.safe_filename("act", "АКТ №1/2 ..\\x y", "docx")
    assert name.endswith(".docx")
    assert not any(c in name for c in "/\\ \"';:\r\n")
    assert ".." not in name
    assert services.safe_filename("act", "", "pdf") == "act.pdf"


# --- транзакции --------------------------------------------------------------------------------


class Boom(Exception):
    pass


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_rollback_does_not_burn_number(company):
    client = make_client(company)
    user = first_user(company)
    with pytest.raises(Boom), tenant_context(company.id), transaction.atomic():
        services.issue_document("contract", user=user, client=client)
        raise Boom
    with tenant_context(company.id):
        assert IssuedDocument.objects.count() == 0
    assert issue(company, "contract", client=client).number == "Д-2026-00001"


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_issue_unique_numbers(company):
    invoice = issue_invoice(company)
    user = first_user(company)
    numbers, errors = [], []
    barrier = threading.Barrier(2)

    def run():
        try:
            barrier.wait(timeout=10)
            with tenant_context(company.id):
                numbers.append(services.issue_document("act", user=user, invoice=invoice).number)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=run) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors, errors
    assert sorted(numbers) == ["АКТ-2026-00001", "АКТ-2026-00002"]
    with tenant_context(company.id):
        assert Invoice.objects.get(pk=invoice.pk).status == "issued"
