"""Распознавание документа: сохранить оригинал (если есть хранилище), распознать, разобрать поля."""

import logging

from django.conf import settings
from django.utils import timezone

from . import crypto, engines, fields, gemini, handwriting, storage
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


def google_used_this_month() -> int:
    """Сколько распознаваний Google Vision компания уже сделала в этом календарном месяце."""
    from apps.billing.limits import _month_start
    from apps.core.tenancy import get_current_company_id

    start = _month_start(get_current_company_id())
    return ScannedDocument.objects.filter(
        engine=engines.GOOGLE_VISION, created_at__gte=start
    ).count()


def google_limit() -> int:
    """Порог перехода на другой движок: бесплатные 1000 страниц Google минус запас."""
    return int(getattr(settings, "OCR_GOOGLE_MONTHLY_LIMIT", 950))


def effective_config() -> engines.Config:
    """Конфигурация с учётом бесплатного лимита Google Vision: при исчерпании месячного порога
    Google исключается (ключ обнуляется), основным становится OCR.space, чтобы не получить
    платные запросы. С нового месяца Google включается сам."""
    config = config_for_company()
    if config.google_vision_key and google_used_this_month() >= google_limit():
        engine = config.engine
        if engine == engines.GOOGLE_VISION:
            engine = OcrSettings.OCR_SPACE
        return engines.Config(
            engine=engine,
            google_vision_key="",
            ocr_space_key=config.ocr_space_key,
            fallback=config.fallback,
        )
    return config


_MODELS_CACHE: dict[str, tuple[float, list[str]]] = {}
MODELS_TTL = 600
STATIC_FALLBACK = ("gemini-flash-latest", "gemini-3.5-flash-lite")


def available_models(api_key: str) -> list[str]:
    """Модели, доступные ключу (кэш на 10 минут, чтобы не спрашивать Google при каждом чтении)."""
    import hashlib
    import time

    key = hashlib.sha256(api_key.encode()).hexdigest()
    cached = _MODELS_CACHE.get(key)
    if cached and time.monotonic() - cached[0] < MODELS_TTL:
        return cached[1]
    try:
        found = gemini.list_models(api_key, timeout=8)
    except gemini.GeminiError:
        return []
    _MODELS_CACHE[key] = (time.monotonic(), found)
    return found


def fallback_models(api_key: str = "") -> tuple[str, ...]:
    """Запасные модели Gemini. OCR_GEMINI_FALLBACK_MODELS = «auto» (по умолчанию): все модели,
    доступные ключу, сначала линейка flash, новые первыми (названия и состав у Google меняются,
    поэтому список берётся у самого Google); иначе список через запятую."""
    raw = str(getattr(settings, "OCR_GEMINI_FALLBACK_MODELS", "auto")).strip()
    if raw.lower() != "auto":
        return tuple(m.strip() for m in raw.split(",") if m.strip())
    found = available_models(api_key) if api_key else []
    if not found:
        return STATIC_FALLBACK
    return tuple([m for m in found if "flash" in m] + [m for m in found if "flash" not in m])


def handwriting_config() -> handwriting.HandwritingConfig:
    """Настройки Gemini компании; ключ, которого она не вводила, берётся из окружения сервера."""
    server_key = getattr(settings, "OCR_GEMINI_KEY", "")
    row = OcrSettings.objects.first()
    if row is None:
        return handwriting.HandwritingConfig(
            api_key=server_key, fallback_models=fallback_models(server_key)
        )
    api_key = crypto.decrypt(row.gemini_key_enc) or server_key
    return handwriting.HandwritingConfig(
        api_key=api_key,
        model=row.handwriting_model or handwriting.DEFAULT_MODEL,
        check_model=row.handwriting_check_model or handwriting.DEFAULT_CHECK_MODEL,
        crosscheck=row.handwriting_crosscheck,
        enabled=row.handwriting_enabled,
        fallback_models=fallback_models(api_key),
    )


def _read_sheet(doc: ScannedDocument, data: bytes, content_type: str) -> None:
    config = handwriting_config()
    if not config.ready:
        doc.status = ScannedDocument.FAILED
        doc.error = "Чтение рукописных листов не настроено: введите ключ Gemini в настройках."
        return
    try:
        page = handwriting.read_sheet(data, content_type, config)
    except handwriting.HandwritingError as exc:
        doc.status, doc.error = ScannedDocument.FAILED, str(exc)[:1000]
        return
    doc.status, doc.engine = ScannedDocument.DONE, "gemini"
    doc.sheet = page


def scan(
    data: bytes, content_type: str, name: str, doc_type: str, user, **extra
) -> ScannedDocument:
    """Создаёт запись и распознаёт синхронно. Лимит тарифа проверяется при создании записи
    (до обращения к движку), сбой распознавания сохраняется в записи и не роняет запрос.
    extra - дополнительные поля записи (рейс, водитель, источник)."""
    doc = ScannedDocument(
        doc_type=doc_type, status=ScannedDocument.PROCESSING, original_name=name[:255],
        content_type=content_type, size=len(data), uploaded_by=user, **extra,
    )  # fmt: skip
    doc.save()
    if storage.configured():
        try:
            key = storage.new_key(doc.company_id, content_type)
            storage.put(key, data, content_type)
            doc.file_key = key
        except storage.StorageError as exc:
            logger.warning("Оригинал документа %s не сохранён: %s", doc.pk, exc)
    if doc_type == ScannedDocument.REPORT_SHEET:
        _read_sheet(doc, data, content_type)
    else:
        try:
            text, engine = engines.recognize(data, content_type, effective_config())
        except engines.OcrError as exc:
            doc.status, doc.error = ScannedDocument.FAILED, str(exc)[:1000]
        else:
            doc.status, doc.engine, doc.text = ScannedDocument.DONE, engine, text
            doc.fields = fields.parse_fields(text, doc_type)
    doc.processed_at = timezone.now()
    doc.save()
    return doc
