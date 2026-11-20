"""Распознавание документа: сохранить оригинал (если есть хранилище), распознать, разобрать поля."""

import logging

from django.conf import settings
from django.utils import timezone

from . import crypto, engines, fields, storage
from .models import OcrSettings, ScannedDocument

logger = logging.getLogger(__name__)

MAX_BYTES = 4_000_000  # Vercel не пропускает тела запросов больше 4,5 МБ
JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def sniff(data: bytes) -> str | None:
    """Тип по первым байтам (Content-Type верить нельзя): image/jpeg, image/png или None."""
    if data.startswith(JPEG_MAGIC):
        return "image/jpeg"
    if data.startswith(PNG_MAGIC):
        return "image/png"
    return None


def env_defaults() -> dict:
    return {
        "google_vision_key": getattr(settings, "OCR_GOOGLE_VISION_KEY", ""),
        "ocr_space_key": getattr(settings, "OCR_SPACE_KEY", ""),
    }


def config_for_company() -> engines.Config:
    """Выбор компании; ключи, которые она не вводила, берутся из окружения сервера (если заданы)."""
    row = OcrSettings.objects.first()
    env = env_defaults()
    if row is None:
        return engines.Config(
            engine=OcrSettings.OCR_SPACE, ocr_space_key=env["ocr_space_key"],
            google_vision_key=env["google_vision_key"],
        )  # fmt: skip
    return engines.Config(
        engine=row.engine,
        google_vision_key=crypto.decrypt(row.google_vision_key_enc) or env["google_vision_key"],
        ocr_space_key=crypto.decrypt(row.ocr_space_key_enc) or env["ocr_space_key"],
        fallback=row.auto_fallback,
    )


def scan(data: bytes, content_type: str, name: str, doc_type: str, user) -> ScannedDocument:
    """Создаёт запись и распознаёт синхронно. Лимит тарифа проверяется при создании записи
    (до обращения к движку), сбой распознавания сохраняется в записи и не роняет запрос."""
    doc = ScannedDocument(
        doc_type=doc_type, status=ScannedDocument.PROCESSING, original_name=name[:255],
        content_type=content_type, size=len(data), uploaded_by=user,
    )  # fmt: skip
    doc.save()
    if storage.configured():
        try:
            key = storage.new_key(doc.company_id, content_type)
            storage.put(key, data, content_type)
            doc.file_key = key
        except storage.StorageError as exc:
            logger.warning("Оригинал документа %s не сохранён: %s", doc.pk, exc)
    try:
        text, engine = engines.recognize(data, content_type, config_for_company())
    except engines.OcrError as exc:
        doc.status, doc.error = ScannedDocument.FAILED, str(exc)[:1000]
    else:
        doc.status, doc.engine, doc.text = ScannedDocument.DONE, engine, text
        doc.fields = fields.parse_fields(text, doc_type)
    doc.processed_at = timezone.now()
    doc.save()
    return doc
