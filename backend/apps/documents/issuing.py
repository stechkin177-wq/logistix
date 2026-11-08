"""Выдача документа по универсальному субъекту через реестр поставщиков (A7).

Ядро не импортирует модели других модулей: субъект загружает и описывает поставщик
(documents/providers.py). Журнал, снимок, номер, аудит и скачивание - те же, что у прежних видов.
"""

from django.db import transaction

from apps.core.audit import services as audit
from apps.core.numbering.services import next_number

from . import access
from .context import _company as company_block
from .context import _date
from .errors import DocumentError
from .models import NUMBERED_KINDS, IssuedDocument
from .providers import find_provider
from .services import FALLBACK_LANGUAGE, _company, _pick_template, _today
from .words import date_long


@transaction.atomic
def issue_for_subject(
    kind: str, subject_type: str, subject_id: int, *, user, language: str | None = None
) -> IssuedDocument:
    """Выдать документ по субъекту поставщика: шаблон, номер, снимок и запись журнала."""
    provider = find_provider(kind, subject_type)
    if provider is None:
        raise DocumentError("kind_invalid", "Неизвестный вид документа или субъект.")
    access.require_module(provider.module_code)
    company = _company()
    template = _pick_template(kind, language or company.language or FALLBACK_LANGUAGE)
    subject = provider.load_subject(subject_type, subject_id)
    if subject is None:
        raise DocumentError("source_not_ready", "Субъект документа не найден или удалён.")
    number = next_number(kind) if kind in NUMBERED_KINDS else ""
    language_used = template.language
    issue_date = _today(company)
    snapshot = {
        "doc": {
            "number": number,
            "date": _date(issue_date),
            "date_long": date_long(issue_date, language_used),
        },
        "company": company_block(),
        **provider.build_context(kind, subject, language_used),
    }
    doc = IssuedDocument.objects.create(
        kind=kind,
        template_version=template.current_version,
        number=number,
        issue_date=issue_date,
        language=language_used,
        subject_type=subject_type,
        subject_id=subject_id,
        snapshot=snapshot,
        created_by=user if getattr(user, "pk", None) else None,
    )
    audit.log(
        "create",
        doc,
        user,
        {
            "kind": kind,
            "number": number,
            "template_version": doc.template_version_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
        },
    )
    return doc
