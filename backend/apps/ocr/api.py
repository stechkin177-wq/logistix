import hmac
import re
import uuid
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.db.models import Count, Exists, OuterRef, Q
from django.http import HttpResponse
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

from . import crypto, engines, handwriting, services, storage
from .models import OcrDocType, OcrFile, OcrSettings, ScannedDocument

FIELD_KEYS = ("date", "amount", "liters", "price_per_liter", "fuel_type", "plate", "note")
MAX_FIELD_LEN = 200
MODEL_RE = re.compile(r"^[A-Za-z0-9._-]{1,60}$")
MAX_REVIEW_ITEMS = 600


class UploadThrottle(UserRateThrottle):
    scope = "ocr_upload"


class DocumentSerializer(serializers.ModelSerializer):
    has_file = serializers.SerializerMethodField()
    uploaded_by_name = serializers.SerializerMethodField()
    doc_type_name = serializers.SerializerMethodField()
    trip_number = serializers.CharField(source="trip.number", read_only=True, default="")
    driver_name = serializers.CharField(source="driver.full_name", read_only=True, default="")
    vehicle_plate = serializers.CharField(source="vehicle.plate", read_only=True, default="")

    class Meta:
        model = ScannedDocument
        fields = [
            "id", "doc_type", "doc_type_name", "status", "engine", "original_name", "size",
            "has_file", "text", "fields", "sheet", "review", "error", "uploaded_by_name",
            "created_at", "processed_at", "source", "trip", "trip_number", "route", "driver",
            "driver_name", "vehicle", "vehicle_plate", "reviewed_at", "archived_at",
            "driver_archived_at",
        ]  # fmt: skip
        read_only_fields = [f for f in fields if f not in ("doc_type", "fields")]

    def get_has_file(self, obj):
        flag = getattr(obj, "has_db_file", None)
        if flag is None:
            flag = OcrFile.objects.filter(document_id=obj.pk).exists()
        return bool(flag or obj.file_key)

    def get_doc_type_name(self, obj):
        names = self.context.get("type_names")
        if names is None:
            names = services.doc_type_names()
        return names.get(obj.doc_type, obj.doc_type)

    def get_uploaded_by_name(self, obj):
        user = obj.uploaded_by
        return (user.full_name or user.email or user.phone or "") if user else ""

    def validate_doc_type(self, value):
        if services.doc_type_or_none(value) is None:
            raise serializers.ValidationError("Неизвестный тип документа")
        return value

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


def documents_queryset():
    """Документы компании без байтов фото; has_db_file - есть ли копия для просмотра."""
    return ScannedDocument.objects.select_related(
        "uploaded_by", "trip", "driver", "vehicle"
    ).annotate(has_db_file=Exists(OcrFile.objects.filter(document=OuterRef("pk"))))


def image_response(doc: ScannedDocument) -> HttpResponse:
    """Фото документа (копия в базе); без копии - 404. Только вложение «как есть»: тип по первым
    байтам, nosniff, не кэшируется общими кэшами."""
    stored = OcrFile.objects.filter(document=doc).first()
    if stored is None:
        raise NotFound("Фото не сохранено или уже удалено по сроку архива")
    response = HttpResponse(bytes(stored.data), content_type=stored.content_type)
    response["Cache-Control"] = "private, max-age=300"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def clean_review(data) -> dict:
    """Результат сверки: {"edits": {путь: строка}, "checked": [путь]}, размеры ограничены."""
    if not isinstance(data, dict):
        raise ValidationError({"review": "Ожидается объект"})
    edits, checked = data.get("edits") or {}, data.get("checked") or []
    if not isinstance(edits, dict) or not isinstance(checked, list):
        raise ValidationError({"review": "edits - объект, checked - список"})
    if len(edits) > MAX_REVIEW_ITEMS or len(checked) > MAX_REVIEW_ITEMS:
        raise ValidationError({"review": "Слишком много значений"})
    clean_edits = {}
    for path, value in edits.items():
        if not isinstance(path, str) or len(path) > 120 or not isinstance(value, str | int | float):
            raise ValidationError({"review": "Некорректная правка"})
        clean_edits[path] = str(value).strip()[:MAX_FIELD_LEN]
    clean_checked = sorted({str(p)[:120] for p in checked})
    return {"edits": clean_edits, "checked": clean_checked}


class DocumentViewSet(SectionPermissionMixin, viewsets.ModelViewSet):
    """Распознанные документы: список по группам, загрузка (POST multipart), правка полей,
    сверка с фото, проверка и архив офиса, удаление."""

    permission_section = "ocr"
    serializer_class = DocumentSerializer
    pagination_class = StandardPagination
    parser_classes = [MultiPartParser, FormParser, *viewsets.ModelViewSet.parser_classes]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    _action_map = {
        **SectionPermissionMixin._action_map,
        "review": "update",
        "archive": "update",
        "save_review": "update",
        "image": "view",
        "groups": "view",
    }

    def get_throttles(self):
        return [UploadThrottle()] if self.action == "create" else super().get_throttles()

    def get_permissions(self):
        return [ModuleRequired("ocr")(), *super().get_permissions()]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["type_names"] = services.doc_type_names()
        return context

    @staticmethod
    def _filter_id(qs, field, raw):
        """0 - «без значения» (документ не привязан), число - конкретная запись, иное - пусто."""
        if raw == "0":
            return qs.filter(**{f"{field}__isnull": True})
        return qs.filter(**{field: raw}) if raw.isdigit() else qs.none()

    def _filtered(self, *, archived_filter=True):
        qs = documents_queryset()
        p = self.request.query_params
        if status_ := p.get("status"):
            if status_ not in dict(ScannedDocument.STATUSES):
                raise ValidationError({"status": "Допустимо: processing, done, failed"})
            qs = qs.filter(status=status_)
        if doc_type := p.get("doc_type"):
            qs = qs.filter(doc_type=doc_type)
        if source := p.get("source"):
            if source not in dict(ScannedDocument.SOURCES):
                raise ValidationError({"source": "Допустимо: office, driver_app"})
            qs = qs.filter(source=source)
        if trip := p.get("trip"):
            qs = self._filter_id(qs, "trip_id", trip)
        if driver := p.get("driver"):
            qs = self._filter_id(qs, "driver_id", driver)
        if vehicle := p.get("vehicle"):
            qs = self._filter_id(qs, "vehicle_id", vehicle)
        if (reviewed := p.get("reviewed")) in ("true", "false"):
            qs = qs.filter(reviewed_at__isnull=(reviewed == "false"))
        if q := (p.get("q") or "").strip():
            qs = qs.filter(Q(original_name__icontains=q) | Q(text__icontains=q))
        if archived_filter:
            qs = qs.filter(archived_at__isnull=(p.get("archived") != "true"))
        return qs

    def get_queryset(self):
        # архив и обычные документы различаются только в списке; карточки и действия
        # доступны для любого документа
        return self._filtered(archived_filter=self.action == "list")

    @action(detail=False, methods=["get"], url_path="groups")
    def groups(self, request):
        """Разграничение документов: ?by=driver|vehicle, ?archived=true. Группа id=0 - документы без
        водителя (машины). Для каждой: всего и ожидающих проверки офисом (только водительские)."""
        by = request.query_params.get("by", "driver")
        if by not in ("driver", "vehicle"):
            raise ValidationError({"by": "Допустимо: driver, vehicle"})
        key, label = (
            ("driver_id", "driver__full_name")
            if by == "driver"
            else ("vehicle_id", "vehicle__plate")
        )
        base = ScannedDocument.objects.filter(
            archived_at__isnull=(request.query_params.get("archived") != "true")
        )
        rows = (
            base.values(key, label)
            .annotate(
                total=Count("id"),
                pending=Count("id", filter=Q(source="driver_app", reviewed_at__isnull=True)),
            )
            .order_by(label)
        )
        out = [
            {
                "id": r[key] or 0,
                "name": r[label] or "",
                "total": r["total"],
                "pending": r["pending"],
            }
            for r in rows
        ]
        return Response({"results": out})

    @action(detail=True, methods=["get"], url_path="image")
    def image(self, request, pk=None):
        return image_response(self.get_object())

    @action(detail=True, methods=["post"], url_path="review")
    def review(self, request, pk=None):
        """Отметка «проверено офисом» ({"reviewed": true|false}; по умолчанию true)."""
        doc = self.get_object()
        reviewed = request.data.get("reviewed", True) not in (False, "false", "0", 0)
        doc.reviewed_at = timezone.now() if reviewed else None
        doc.reviewed_by = request.user if reviewed else None
        doc.save(update_fields=["reviewed_at", "reviewed_by"])
        return Response(self.get_serializer(doc).data)

    @action(detail=True, methods=["post"], url_path="save-review")
    def save_review(self, request, pk=None):
        """Сохранение сверки с фото: правки и подтверждённые значения; done=true - ещё и отметить
        документ проверенным."""
        doc = self.get_object()
        doc.review = clean_review(request.data)
        fields_ = ["review"]
        if request.data.get("done") in (True, "true", 1, "1"):
            doc.reviewed_at, doc.reviewed_by = timezone.now(), request.user
            fields_ += ["reviewed_at", "reviewed_by"]
        doc.save(update_fields=fields_)
        return Response(self.get_serializer(doc).data)

    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request, pk=None):
        """В архив офиса и обратно ({"archived": true|false}); файлы из архива чистятся по сроку."""
        doc = self.get_object()
        archived = request.data.get("archived", True) not in (False, "false", "0", 0)
        doc.archived_at = timezone.now() if archived else None
        doc.save(update_fields=["archived_at"])
        return Response(self.get_serializer(doc).data)

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
        if services.doc_type_or_none(doc_type) is None:
            raise ValidationError({"doc_type": "Неизвестный тип документа"})
        doc = services.scan(data, content_type, upload.name or "", doc_type, request.user)
        return Response(self.get_serializer(doc).data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance):
        key = instance.file_key
        instance.delete()
        if key and storage.configured():
            storage.delete(key)


class DocTypeSerializer(serializers.ModelSerializer):
    used = serializers.SerializerMethodField()

    class Meta:
        model = OcrDocType
        fields = [
            "id",
            "code",
            "name",
            "handler",
            "driver_visible",
            "is_active",
            "sort_order",
            "used",
        ]
        read_only_fields = ["id", "code", "used"]

    def get_used(self, obj):
        counts = self.context.get("counts") or {}
        return counts.get(obj.code, 0)

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Укажите название")
        return value


class DocTypeViewSet(viewsets.ModelViewSet):
    """Типы документов компании: чтение по ocr.view, изменение по ocr.manage. Тип, по которому уже
    есть документы, при «удалении» отключается (документы сохраняют его название)."""

    serializer_class = DocTypeSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self):
        code = "ocr.view" if self.request.method in ("GET", "HEAD", "OPTIONS") else "ocr.manage"
        return [ModuleRequired("ocr")(), permission_required(code)()]

    def get_queryset(self):
        services.ensure_doc_types()
        return OcrDocType.objects.all()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["counts"] = dict(
            ScannedDocument.objects.values_list("doc_type").annotate(n=Count("id"))
        )
        return context

    def perform_create(self, serializer):
        last = OcrDocType.objects.order_by("-sort_order").first()
        order = (last.sort_order if last else 0) + 10
        serializer.save(code=f"t{uuid.uuid4().hex[:10]}", sort_order=order)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if ScannedDocument.objects.filter(doc_type=instance.code).exists():
            instance.is_active = False
            instance.save(update_fields=["is_active"])
            return Response({"deactivated": True})
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


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
        "handwriting_crosscheck": row.handwriting_crosscheck if row else False,
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
    """Проверка движков с ключом: каждый отвечает на пробную картинку (ключи наружу не уходят)."""

    def get_permissions(self):
        return [ModuleRequired("ocr")(), permission_required("ocr.manage")()]

    def post(self, request):
        config = services.config_for_company()
        names = [n for n in engines.ENGINES if engines.make(n, config).available()]

        def check(name):
            error = engines.check_engine(name, config)
            return name, {"ok": error == "", "error": error}

        with ThreadPoolExecutor(max_workers=max(1, len(names))) as pool:
            results = dict(pool.map(check, names)) if names else {}
        return Response({"results": results})


class CronPurgeView(APIView):
    """Ежедневная очистка: удаляет фото документов старше срока архива (180 дней). Вызывается
    планировщиком Vercel с заголовком Authorization: Bearer <CRON_SECRET>; без секрета закрыт."""

    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request):
        from apps.core.models import Company
        from apps.core.tenancy import tenant_context

        secret = getattr(settings, "CRON_SECRET", "")
        given = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not secret or not hmac.compare_digest(given.encode(), secret.encode()):
            return Response({"detail": "Нет доступа"}, status=status.HTTP_403_FORBIDDEN)
        total = 0
        for company_id in Company.objects.values_list("id", flat=True):
            with tenant_context(company_id):
                total += services.purge_old_files()
        return Response({"purged": total})
