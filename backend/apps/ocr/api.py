import re
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import SectionPermissionMixin, permission_required
from apps.core.pagination import StandardPagination

from . import crypto, engines, gemini, handwriting, services, storage
from .models import OcrSettings, ScannedDocument

FIELD_KEYS = ("date", "amount", "liters", "price_per_liter", "fuel_type", "plate", "note")
MAX_FIELD_LEN = 200
MODEL_RE = re.compile(r"^[A-Za-z0-9._-]{1,60}$")


class UploadThrottle(UserRateThrottle):
    scope = "ocr_upload"


class DocumentSerializer(serializers.ModelSerializer):
    has_file = serializers.SerializerMethodField()
    uploaded_by_name = serializers.SerializerMethodField()
    trip_number = serializers.CharField(source="trip.number", read_only=True, default="")
    driver_name = serializers.CharField(source="driver.full_name", read_only=True, default="")

    class Meta:
        model = ScannedDocument
        fields = [
            "id", "doc_type", "status", "engine", "original_name", "size", "has_file", "text",
            "fields", "sheet", "error", "uploaded_by_name", "created_at", "processed_at",
            "source", "trip", "trip_number", "driver", "driver_name", "reviewed_at",
        ]  # fmt: skip
        read_only_fields = [f for f in fields if f not in ("doc_type", "fields")]

    def get_has_file(self, obj):
        return bool(obj.file_key)

    def get_uploaded_by_name(self, obj):
        user = obj.uploaded_by
        return (user.full_name or user.email or user.phone or "") if user else ""

    def validate_fields(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Ожидается объект")
        clean = {}
        for key, raw in value.items():
            if key not in FIELD_KEYS:
                raise serializers.ValidationError(f"Неизвестное поле: {key}")
            if not isinstance(raw, str) or len(raw) > MAX_FIELD_LEN:
                raise serializers.ValidationError(f"{key}: текст до {MAX_FIELD_LEN} символов")
            if raw.strip():
                clean[key] = raw.strip()
        return clean


class DocumentViewSet(SectionPermissionMixin, viewsets.ModelViewSet):
    """Распознанные документы: список, загрузка (POST multipart), правка полей, удаление."""

    permission_section = "ocr"
    serializer_class = DocumentSerializer
    pagination_class = StandardPagination
    parser_classes = [MultiPartParser, FormParser, *viewsets.ModelViewSet.parser_classes]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    _action_map = {**SectionPermissionMixin._action_map, "review": "update"}

    def get_throttles(self):
        return [UploadThrottle()] if self.action == "create" else super().get_throttles()

    def get_permissions(self):
        return [ModuleRequired("ocr")(), *super().get_permissions()]

    def get_queryset(self):
        qs = ScannedDocument.objects.select_related("uploaded_by", "trip", "driver")
        p = self.request.query_params
        if status_ := p.get("status"):
            if status_ not in dict(ScannedDocument.STATUSES):
                raise ValidationError({"status": "Допустимо: processing, done, failed"})
            qs = qs.filter(status=status_)
        if doc_type := p.get("doc_type"):
            if doc_type not in dict(ScannedDocument.TYPES):
                raise ValidationError({"doc_type": "Неизвестный тип документа"})
            qs = qs.filter(doc_type=doc_type)
        if source := p.get("source"):
            if source not in dict(ScannedDocument.SOURCES):
                raise ValidationError({"source": "Допустимо: office, driver_app"})
            qs = qs.filter(source=source)
        if trip := p.get("trip"):
            qs = qs.filter(trip_id=trip) if trip.isdigit() else qs.none()
        if driver := p.get("driver"):
            qs = qs.filter(driver_id=driver) if driver.isdigit() else qs.none()
        if (reviewed := p.get("reviewed")) in ("true", "false"):
            qs = qs.filter(reviewed_at__isnull=(reviewed == "false"))
        if q := (p.get("q") or "").strip():
            qs = qs.filter(original_name__icontains=q) | qs.filter(text__icontains=q)
        return qs

    @action(detail=True, methods=["post"], url_path="review")
    def review(self, request, pk=None):
        """Отметка «проверено офисом» ({"reviewed": true|false}; по умолчанию true)."""
        doc = self.get_object()
        reviewed = request.data.get("reviewed", True) not in (False, "false", "0", 0)
        doc.reviewed_at = timezone.now() if reviewed else None
        doc.reviewed_by = request.user if reviewed else None
        doc.save(update_fields=["reviewed_at", "reviewed_by"])
        return Response(DocumentSerializer(doc).data)

    def create(self, request, *args, **kwargs):
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": "Выберите файл"})
        if upload.size > services.MAX_BYTES:
            raise ValidationError({"file": "Файл больше 4 МБ: сожмите фото"})
        data = upload.read()
        content_type = services.sniff(data)
        if content_type is None:
            raise ValidationError({"file": "Нужна картинка JPEG или PNG"})
        doc_type = request.data.get("doc_type") or ScannedDocument.OTHER
        if doc_type not in dict(ScannedDocument.TYPES):
            raise ValidationError({"doc_type": "Неизвестный тип документа"})
        doc = services.scan(data, content_type, upload.name or "", doc_type, request.user)
        return Response(DocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance):
        key = instance.file_key
        instance.delete()
        if key and storage.configured():
            storage.delete(key)

    def file(self, request, pk=None):
        doc = self.get_object()
        if not doc.file_key or not storage.configured():
            raise NotFound("Оригинал не сохранён")
        try:
            return Response({"url": storage.signed_url(doc.file_key)})
        except storage.StorageError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)


class SettingsSerializer(serializers.Serializer):
    engine = serializers.ChoiceField(choices=[c for c, _ in OcrSettings.ENGINES], required=False)
    auto_fallback = serializers.BooleanField(required=False)
    google_vision_key = serializers.CharField(
        required=False, allow_blank=True, write_only=True, trim_whitespace=True
    )
    ocr_space_key = serializers.CharField(
        required=False, allow_blank=True, write_only=True, trim_whitespace=True
    )
    gemini_key = serializers.CharField(
        required=False, allow_blank=True, write_only=True, trim_whitespace=True
    )
    handwriting_enabled = serializers.BooleanField(required=False)
    handwriting_crosscheck = serializers.BooleanField(required=False)
    handwriting_model = serializers.RegexField(r"^[A-Za-z0-9._-]{1,60}$", required=False)
    handwriting_check_model = serializers.RegexField(r"^[A-Za-z0-9._-]{1,60}$", required=False)


def settings_payload(row: OcrSettings | None) -> dict:
    env = services.env_defaults()
    return {
        "engine": row.engine if row else OcrSettings.OCR_SPACE,
        "auto_fallback": row.auto_fallback if row else True,
        "has_google_vision_key": bool(row and row.google_vision_key_enc)
        or bool(env["google_vision_key"]),
        "has_ocr_space_key": bool(row and row.ocr_space_key_enc) or bool(env["ocr_space_key"]),
        "has_gemini_key": bool(row and row.gemini_key_enc)
        or bool(getattr(settings, "OCR_GEMINI_KEY", "")),
        "handwriting_enabled": row.handwriting_enabled if row else True,
        "handwriting_crosscheck": row.handwriting_crosscheck if row else True,
        "handwriting_model": row.handwriting_model if row else handwriting.DEFAULT_MODEL,
        "handwriting_check_model": (
            row.handwriting_check_model if row else handwriting.DEFAULT_CHECK_MODEL
        ),
        "google_used": services.google_used_this_month(),
        "google_limit": services.google_limit(),
        "tesseract_available": engines.Tesseract().available(),
        "storage_configured": storage.configured(),
        "engines": [{"code": c, "label": label} for c, label in OcrSettings.ENGINES],
    }


class SettingsView(APIView):
    """Настройки распознавания: GET (без ключей), PUT (пустой ключ - без изменения)."""

    def get_permissions(self):
        code = "ocr.view" if self.request.method == "GET" else "ocr.manage"
        return [ModuleRequired("ocr")(), permission_required(code)()]

    def get(self, request):
        return Response(settings_payload(OcrSettings.objects.first()))

    def put(self, request):
        ser = SettingsSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        row = OcrSettings.objects.first() or OcrSettings()
        if "engine" in data:
            row.engine = data["engine"]
        if "auto_fallback" in data:
            row.auto_fallback = data["auto_fallback"]
        if key := data.get("google_vision_key"):
            row.google_vision_key_enc = crypto.encrypt(key)
        if key := data.get("ocr_space_key"):
            row.ocr_space_key_enc = crypto.encrypt(key)
        if key := data.get("gemini_key"):
            row.gemini_key_enc = crypto.encrypt(key)
        for name in (
            "handwriting_enabled", "handwriting_crosscheck",
            "handwriting_model", "handwriting_check_model",
        ):  # fmt: skip
            if name in data:
                setattr(row, name, data[name])
        row.save()
        return Response(settings_payload(row))


class SettingsTestView(APIView):
    """Проверка движков: каждый с ключом отвечает на пробную картинку (ключи наружу не уходят)."""

    def get_permissions(self):
        return [ModuleRequired("ocr")(), permission_required("ocr.manage")()]

    def post(self, request):
        config = services.config_for_company()
        results = {}
        for name in engines.ENGINES:
            engine = engines.ENGINES[name](config.key_for(name))
            if not engine.available():
                continue
            error = engines.check_engine(name, config.key_for(name))
            results[name] = {"ok": error == "", "error": error}
        return Response({"results": results})


class GeminiModelsView(APIView):
    """Список моделей Gemini, доступных ключу компании (названия меняются: брать только отсюда)."""

    def get_permissions(self):
        return [ModuleRequired("ocr")(), permission_required("ocr.manage")()]

    def get(self, request):
        config = services.handwriting_config()
        if not config.api_key:
            return Response({"models": [], "error": "Не задан ключ Gemini."})
        try:
            return Response({"models": gemini.list_models(config.api_key), "error": ""})
        except gemini.GeminiError as exc:
            return Response({"models": [], "error": str(exc)})


class GeminiTestView(APIView):
    """Проверка Gemini: читает тестовую картинку - ключ, выбранные модели и приём фото работают."""

    def get_permissions(self):
        return [ModuleRequired("ocr")(), permission_required("ocr.manage")()]

    def post(self, request):
        """Тело (необязательно): model и check_model - проверяются введённые в форме модели, ещё
        не сохранённые; иначе проверяются сохранённые настройки компании."""
        config = services.handwriting_config()
        if not config.api_key:
            return Response({"ok": False, "error": "Не задан ключ Gemini."})
        names = []
        for key in ("model", "check_model"):
            value = str(request.data.get(key) or "").strip()
            if value and not MODEL_RE.match(value):
                raise ValidationError({key: "Недопустимое название модели"})
            names.append(value)
        main = names[0] or config.model
        check = names[1] or config.check_model
        models = [main] + ([check] if config.crosscheck and check != main else [])

        def check(model):
            try:
                gemini.check_key(model, config.api_key, engines.PROBE_PNG, "image/png")
            except gemini.GeminiError as exc:
                return model, {"ok": False, "error": str(exc)}
            return model, {"ok": True, "error": ""}

        # параллельно: последовательные проверки с таймаутами не укладывались в лимит функции
        with ThreadPoolExecutor(max_workers=len(models)) as pool:
            results = dict(pool.map(check, models))
        return Response({"ok": all(r["ok"] for r in results.values()), "models": results})
