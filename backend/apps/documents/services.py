"""Сервисы документов: версии шаблонов, откат к стартовому, выдача и сборка файла.

Вызываются в контексте компании (RLS). Права на исходный объект проверяет API.
"""

import hashlib
import re
from datetime import date
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.core.audit import services as audit
from apps.core.models import Company
from apps.core.numbering.services import next_number
from apps.core.tenancy import get_current_company_id
from apps.finance.models import Invoice
from apps.forwarding.models import Client, Order, Trip

from . import engine, pdf
from .context import build_context
from .errors import DocumentError
from .models import (
    KINDS,
    NUMBERED_KINDS,
    DocumentTemplate,
    DocumentTemplateVersion,
    IssuedDocument,
)
from .starter import starter_bytes

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_TYPE = "application/pdf"
FALLBACK_LANGUAGE = "ru"
LETTER_LIMITS = {"recipient": 255, "subject": 255, "body": 20000}
LETTER_LABELS = {"recipient": "адресат", "subject": "тема", "body": "текст"}

# --- условия источников: единая таблица (спека, раздел 4) -------------------------------------
# вид -> (аргумент-источник, модель, проверка состояния под блокировкой -> текст ошибки | None)


def _check_none(obj) -> str | None:
    return None


def _check_issued_out_invoice(invoice) -> str | None:
    if invoice.direction != "out" or invoice.status != "issued":
        return "Документ можно выдать только по выставленному счёту клиенту."
    return None


def _check_trip_carrier(trip) -> str | None:
    return None if trip.carrier_id else "У рейса не указан перевозчик."


def _check_trip_cargo(trip) -> str | None:
    if not trip.consignments.filter(order__deleted_at__isnull=True).exists():
        return "В рейсе нет грузов."
    return None


SOURCES = {
    "contract": ("client", Client, _check_none),
    "order_request": ("order", Order, _check_none),
    "carrier_order": ("trip", Trip, _check_trip_carrier),
    "act": ("invoice", Invoice, _check_issued_out_invoice),
    "invoice_print": ("invoice", Invoice, _check_issued_out_invoice),
    "cmr": ("trip", Trip, _check_trip_cargo),
    "letter": (None, None, _check_none),
}
_NOT_FOUND = {
    "client": "Клиент не найден.",
    "order": "Заказ не найден или удалён.",
    "trip": "Рейс не найден или удалён.",
    "invoice": "Счёт не найден или удалён.",
}


def _not_ready(detail: str) -> DocumentError:
    return DocumentError("source_not_ready", detail)


# --- версии шаблонов --------------------------------------------------------------------------


def _new_version(
    template: DocumentTemplate, data: bytes, user, *, is_starter: bool
) -> DocumentTemplateVersion:
    locked = DocumentTemplate.objects.select_for_update().get(pk=template.pk)
    last = locked.versions.aggregate(m=Max("number"))["m"] or 0
    version = DocumentTemplateVersion.objects.create(
        template=locked,
        number=last + 1,
        content=data,
        sha256=hashlib.sha256(data).hexdigest(),
        is_starter=is_starter,
        uploaded_by=user if getattr(user, "pk", None) else None,
    )
    locked.current_version = version
    locked.save(update_fields=["current_version"])
    template.current_version = version
    template.current_version_id = version.pk
    audit.log(
        "update",
        locked,
        user,
        {"current_version": [None, version.number], "sha256": version.sha256},
    )
    return version


@transaction.atomic
def upload_version(template: DocumentTemplate, data: bytes, user) -> DocumentTemplateVersion:
    """Проверить и сохранить новую версию шаблона, сделать её текущей."""
    engine.validate_upload(data, template.kind)
    return _new_version(template, data, user, is_starter=False)


@transaction.atomic
def reset_to_starter(template: DocumentTemplate, user) -> DocumentTemplateVersion:
    """Вернуть стартовый файл как новую версию (история сохраняется)."""
    data = starter_bytes(template.kind, template.language)
    return _new_version(template, data, user, is_starter=True)


# --- выдача -----------------------------------------------------------------------------------


def _company() -> Company:
    return Company.objects.get(pk=get_current_company_id())


def _today(company: Company) -> date:
    try:
        tz = ZoneInfo(company.timezone)
    except Exception:  # noqa: BLE001 - неизвестная зона не должна ронять выдачу
        tz = ZoneInfo("Asia/Almaty")
    return timezone.now().astimezone(tz).date()


def _pick_template(kind: str, language: str) -> DocumentTemplate:
    base = DocumentTemplate.objects.filter(kind=kind, is_active=True, current_version__isnull=False)
    template = base.filter(language=language).first()
    if template is None and language != FALLBACK_LANGUAGE:
        template = base.filter(language=FALLBACK_LANGUAGE).first()
    if template is None:
        raise DocumentError("template_missing", "Нет активного шаблона для этого вида документа.")
    return template


def _clean_letter(letter: dict | None) -> dict:
    letter = letter or {}
    out = {}
    for key, limit in LETTER_LIMITS.items():
        value = letter.get(key)
        value = value.strip() if isinstance(value, str) else ""
        if not value:
            raise DocumentError("letter_invalid", f"Письмо: заполните поле «{LETTER_LABELS[key]}».")
        if len(value) > limit:
            raise DocumentError(
                "letter_invalid", f"Письмо: поле «{LETTER_LABELS[key]}» длиннее {limit} символов."
            )
        out[key] = value
    return out


def _lock_source(kind: str, given: dict):
    arg, model, check = SOURCES[kind]
    if arg is None:
        return None
    obj = given.get(arg)
    if obj is None:
        raise _not_ready(_NOT_FOUND[arg])
    try:
        locked = model.objects.select_for_update(of=("self",)).get(pk=obj.pk)
    except model.DoesNotExist:
        raise _not_ready(_NOT_FOUND[arg]) from None
    problem = check(locked)
    if problem:
        raise _not_ready(problem)
    return locked


@transaction.atomic
def issue_document(
    kind: str,
    *,
    user,
    client=None,
    order=None,
    trip=None,
    invoice=None,
    letter: dict | None = None,
    language: str | None = None,
) -> IssuedDocument:
    """Выдать документ: шаблон, номер, снимок данных и запись журнала в одной транзакции."""
    if kind not in KINDS:
        raise ValueError(f"Неизвестный вид документа: {kind}")
    company = _company()
    template = _pick_template(kind, language or company.language or FALLBACK_LANGUAGE)
    cleaned = _clean_letter(letter) if kind == "letter" else None

    given = {"client": client, "order": order, "trip": trip, "invoice": invoice}
    source = _lock_source(kind, given)
    links = {"client": None, "order": None, "trip": None, "invoice": None}
    if kind == "letter" and order is not None:
        try:
            links["order"] = Order.objects.select_for_update(of=("self",)).get(pk=order.pk)
        except Order.DoesNotExist:
            raise _not_ready(_NOT_FOUND["order"]) from None
    elif source is not None:
        arg = SOURCES[kind][0]
        links[arg] = source
        if arg == "invoice":
            links["order"] = source.order
            links["client"] = source.client

    if kind in NUMBERED_KINDS:
        number = next_number(kind)
    elif kind == "order_request":
        number = links["order"].number
    else:  # invoice_print
        number = links["invoice"].number

    language_used = template.language
    issue_date = _today(company)
    snapshot = build_context(
        kind,
        client=links["client"],
        order=links["order"],
        trip=links["trip"],
        invoice=links["invoice"],
        letter=cleaned,
        number=number,
        issue_date=issue_date,
        language=language_used,
    )
    doc = IssuedDocument.objects.create(
        kind=kind,
        template_version=template.current_version,
        number=number,
        issue_date=issue_date,
        language=language_used,
        client=links["client"],
        order=links["order"],
        trip=links["trip"],
        invoice=links["invoice"],
        snapshot=snapshot,
        created_by=user if getattr(user, "pk", None) else None,
    )
    audit.log(
        "create",
        doc,
        user,
        {"kind": kind, "number": number, "template_version": doc.template_version_id},
    )
    return doc


# --- сборка файла -----------------------------------------------------------------------------

_UNSAFE = re.compile(r"[^\w.\-]+")


def safe_filename(kind: str, number: str, ext: str) -> str:
    base = re.sub(r"\.{2,}", ".", _UNSAFE.sub("_", f"{kind}-{number}")).strip("._-") or kind
    return f"{base[:120]}.{ext}"


def render_issued(doc: IssuedDocument, fmt: str) -> tuple[bytes, str, str]:
    """Собрать файл выданного документа из снимка и версии шаблона: (байты, тип, имя)."""
    if fmt not in ("docx", "pdf"):
        raise ValueError(f"Неизвестный формат: {fmt}")
    content = engine.render_docx(bytes(doc.template_version.content), doc.snapshot)
    if fmt == "pdf":
        content = pdf.convert_to_pdf(content)
        return content, PDF_TYPE, safe_filename(doc.kind, doc.number, "pdf")
    return content, DOCX_TYPE, safe_filename(doc.kind, doc.number, "docx")
