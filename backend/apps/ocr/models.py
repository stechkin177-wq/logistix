"""Модуль ocr: настройки распознавания компании и распознанные документы.

Документ может быть привязан к рейсу и водителю (отчёт из приложения водителя); без этой
привязки он остаётся обычной загрузкой офиса. Ключи движков хранятся зашифрованными и наружу
не отдаются."""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TenantModel


class OcrSettings(TenantModel):
    GOOGLE_VISION = "google_vision"
    OCR_SPACE = "ocr_space"
    TESSERACT = "tesseract"
    GEMINI = "gemini"
    ENGINES = [
        (GEMINI, "Google Gemini"),
        (OCR_SPACE, "OCR.space"),
        (GOOGLE_VISION, "Google Cloud Vision"),
        (TESSERACT, "Tesseract (локальный)"),
    ]

    engine = models.CharField(max_length=16, choices=ENGINES, default=OCR_SPACE)
    google_vision_key_enc = models.TextField(blank=True)
    ocr_space_key_enc = models.TextField(blank=True)
    auto_fallback = models.BooleanField(default=True)
    # рукописный отчётный лист: Gemini читает фото, вторая модель пересверяет цифры
    gemini_key_enc = models.TextField(blank=True)
    handwriting_enabled = models.BooleanField(default=True)
    # одна простая рабочая модель по умолчанию; при сбое пробуются другие модели, доступные ключу
    handwriting_model = models.CharField(max_length=60, default="gemini-3.5-flash-lite")
    # вторая модель пересверки: пусто - подбирается автоматически из доступных ключу
    handwriting_check_model = models.CharField(max_length=60, blank=True, default="")
    handwriting_crosscheck = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company"], name="ocrsettings_company_uniq"),
            models.CheckConstraint(
                condition=Q(engine__in=["google_vision", "ocr_space", "tesseract", "gemini"]),
                name="ocrsettings_engine_valid",
            ),
        ]


class OcrDocType(TenantModel):
    """Тип документа распознавания: список настраивает компания (названия, показ водителю).

    handler - как читать: receipt (чек АЗС: дата, сумма, литры, топливо, госномер), sheet
    (рукописный отчётный лист через Gemini), generic (дата и сумма). Код технический и не
    меняется; название можно менять в любой момент."""

    RECEIPT = "receipt"
    SHEET = "sheet"
    GENERIC = "generic"
    HANDLERS = [(RECEIPT, "Чек АЗС"), (SHEET, "Рукописный лист"), (GENERIC, "Обычный документ")]

    code = models.SlugField(max_length=32)
    name = models.CharField(max_length=100)
    handler = models.CharField(max_length=10, choices=HANDLERS, default=GENERIC)
    driver_visible = models.BooleanField(default=True)  # доступен водителю в приложении
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"], name="ocrdoctype_company_code_uniq"
            ),
            models.CheckConstraint(
                condition=Q(handler__in=["receipt", "sheet", "generic"]),
                name="ocrdoctype_handler_valid",
            ),
        ]


DEFAULT_DOC_TYPES = [
    # код, название, обработчик, виден водителю
    ("fuel_receipt", "Чек АЗС", OcrDocType.RECEIPT, True),
    ("report_sheet", "Рукописный отчётный лист", OcrDocType.SHEET, True),
    ("waybill", "Путевой лист", OcrDocType.GENERIC, True),
    ("cmr", "CMR", OcrDocType.GENERIC, True),
    ("invoice", "Счёт или накладная", OcrDocType.GENERIC, False),
    ("other", "Другое", OcrDocType.GENERIC, True),
]


class ScannedDocument(TenantModel):
    FUEL_RECEIPT = "fuel_receipt"
    WAYBILL = "waybill"
    CMR = "cmr"
    INVOICE = "invoice"
    REPORT_SHEET = "report_sheet"
    OTHER = "other"
    OFFICE = "office"
    DRIVER_APP = "driver_app"
    SOURCES = [(OFFICE, "Офис"), (DRIVER_APP, "Приложение водителя")]
    TYPES = [
        (FUEL_RECEIPT, "Чек АЗС"),
        (WAYBILL, "Путевой лист"),
        (CMR, "CMR"),
        (INVOICE, "Счёт или акт"),
        (REPORT_SHEET, "Рукописный отчётный лист"),
        (OTHER, "Прочее"),
    ]
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    STATUSES = [(PROCESSING, "Распознаётся"), (DONE, "Распознан"), (FAILED, "Ошибка")]

    doc_type = models.CharField(max_length=32, default=OTHER)  # код типа компании (OcrDocType)
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
    # рукописный лист: прочитанное, сомнительные значения и расхождения чтений (по путям значений)
    sheet = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    source = models.CharField(max_length=12, choices=SOURCES, default=OFFICE)
    trip = models.ForeignKey(
        "forwarding.Trip", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    driver = models.ForeignKey(
        "drivers.Driver", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    vehicle = models.ForeignKey(
        "fleet.Vehicle", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )  # техника рейса на момент отправки (для группировки по машинам)
    route = models.CharField(max_length=255, blank=True)  # «откуда → куда» рейса на момент отправки
    archived_at = models.DateTimeField(null=True, blank=True)  # архив офиса
    driver_archived_at = models.DateTimeField(null=True, blank=True)  # архив водителя
    # результат сверки с фото: {"edits": {путь: значение}, "checked": [пути]}
    review = models.JSONField(default=dict, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)  # офис проверил документ
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
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
                condition=Q(source__in=["office", "driver_app"]), name="scandoc_source_valid"
            ),
            models.CheckConstraint(
                condition=Q(status__in=["processing", "done", "failed"]),
                name="scandoc_status_valid",
            ),
        ]


class OcrFile(TenantModel):
    """Фото документа (копия для просмотра и сверки). Хранится отдельно от записи, чтобы список
    документов не тянул байты; удаляется вместе с документом и через 180 дней после архива."""

    document = models.OneToOneField(ScannedDocument, on_delete=models.CASCADE, related_name="file")
    content_type = models.CharField(max_length=32)
    data = models.BinaryField()
