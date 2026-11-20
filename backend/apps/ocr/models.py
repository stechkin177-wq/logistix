"""Модуль ocr: настройки распознавания компании и распознанные документы.

Связей с техникой, рейсами и отчётами здесь нет (модуль зависит только от documents): привязка
к ним появится в отчёте водителя. Ключи движков хранятся зашифрованными и наружу не отдаются."""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TenantModel


class OcrSettings(TenantModel):
    GOOGLE_VISION = "google_vision"
    OCR_SPACE = "ocr_space"
    TESSERACT = "tesseract"
    ENGINES = [
        (GOOGLE_VISION, "Google Cloud Vision"),
        (OCR_SPACE, "OCR.space"),
        (TESSERACT, "Tesseract (локальный)"),
    ]

    engine = models.CharField(max_length=16, choices=ENGINES, default=OCR_SPACE)
    google_vision_key_enc = models.TextField(blank=True)
    ocr_space_key_enc = models.TextField(blank=True)
    auto_fallback = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company"], name="ocrsettings_company_uniq"),
            models.CheckConstraint(
                condition=Q(engine__in=["google_vision", "ocr_space", "tesseract"]),
                name="ocrsettings_engine_valid",
            ),
        ]


class ScannedDocument(TenantModel):
    FUEL_RECEIPT = "fuel_receipt"
    WAYBILL = "waybill"
    CMR = "cmr"
    INVOICE = "invoice"
    OTHER = "other"
    TYPES = [
        (FUEL_RECEIPT, "Чек АЗС"),
        (WAYBILL, "Путевой лист"),
        (CMR, "CMR"),
        (INVOICE, "Счёт или акт"),
        (OTHER, "Прочее"),
    ]
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    STATUSES = [(PROCESSING, "Распознаётся"), (DONE, "Распознан"), (FAILED, "Ошибка")]

    doc_type = models.CharField(max_length=16, choices=TYPES, default=OTHER)
    status = models.CharField(max_length=12, choices=STATUSES, default=PROCESSING)
    engine = models.CharField(max_length=16, blank=True)  # сработавший движок
    original_name = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=32, blank=True)
    size = models.PositiveIntegerField(default=0)
    file_key = models.CharField(
        max_length=300, blank=True
    )  # путь в хранилище; пусто - оригинал не сохранён
    text = models.TextField(blank=True)
    fields = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["company", "-created_at"], name="scandoc_company_time_idx")]
        constraints = [
            models.CheckConstraint(
                condition=Q(doc_type__in=["fuel_receipt", "waybill", "cmr", "invoice", "other"]),
                name="scandoc_type_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["processing", "done", "failed"]),
                name="scandoc_status_valid",
            ),
        ]
