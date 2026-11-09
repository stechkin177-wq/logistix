from django.db import transaction
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response

from apps.billing.permissions import ModuleDisabled, company_enabled_modules
from apps.core import document_types as service
from apps.core.audit import services as audit
from apps.core.audit.mixins import AuditedMixin
from apps.core.models import DocumentType

# вид объекта -> (модуль, раздел прав)
SUBJECT_ACCESS = {
    DocumentType.TRACTOR: ("fleet", "fleet"),
    DocumentType.TRAILER: ("fleet", "fleet"),
    DocumentType.DRIVER: ("drivers", "drivers"),
}


def _allowed(request, subject, write):
    module, section = SUBJECT_ACCESS[subject]
    if module not in company_enabled_modules(request):
        return False
    role = request.membership.role
    return bool(role) and f"{section}.{'update' if write else 'view'}" in role.permissions


class DocumentTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentType
        fields = [
            "id", "subject", "name", "fields", "required", "extra", "remind", "remind_days",
            "is_active", "archived_at", "sort_order",
        ]  # fmt: skip
        read_only_fields = ["archived_at"]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Укажите название")
        return value

    def validate(self, attrs):
        if self.instance is not None and "subject" in attrs and (
            attrs["subject"] != self.instance.subject
        ):
            raise serializers.ValidationError({"subject": "Вид объекта изменить нельзя"})
        keys = ("fields", "required", "extra", "remind", "remind_days")
        raw = {k: self.initial_data[k] for k in keys if k in self.initial_data}
        attrs.update(service.clean_config(raw, self.instance))
        if self.instance is None:
            attrs.setdefault("fields", service.ALL_FIELDS)
        return attrs


class DocumentTypeViewSet(AuditedMixin, viewsets.ModelViewSet):
    """Типы документов компании: список по виду объекта (?subject=tractor|trailer|driver),
    создание, правка (переименование, поля, напоминания, отключение), архив/возврат.
    Физического удаления нет: записи и история сохраняются."""

    serializer_class = DocumentTypeSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def _require(self, subject, write):
        if SUBJECT_ACCESS[subject][0] not in company_enabled_modules(self.request):
            raise ModuleDisabled()
        if not _allowed(self.request, subject, write):
            raise PermissionDenied()

    def get_queryset(self):
        qs = DocumentType.objects.all()
        if self.action == "list":
            subject = self.request.query_params.get("subject")
            if subject:
                if subject not in SUBJECT_ACCESS:
                    raise ValidationError({"subject": "Допустимо: tractor, trailer, driver"})
                self._require(subject, False)
                qs = qs.filter(subject=subject)
            else:
                qs = qs.filter(
                    subject__in=[s for s in SUBJECT_ACCESS if _allowed(self.request, s, False)]
                )
            if self.request.query_params.get("archived") != "1":
                qs = qs.filter(archived_at__isnull=True)
        return qs.order_by("sort_order", "id")

    def get_object(self):
        obj = super().get_object()
        self._require(obj.subject, self.request.method not in SAFE_METHODS)
        return obj

    def perform_create(self, serializer):
        subject = serializer.validated_data["subject"]
        self._require(subject, True)
        super().perform_create(serializer)

    def perform_update(self, serializer):
        if serializer.instance.archived_at:
            raise ValidationError("Тип в архиве: сначала верните его из архива")
        super().perform_update(serializer)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        obj = self.get_object()
        with transaction.atomic():
            before = audit.snapshot(obj)
            service.archive(obj)
            self.audit_updated(before, obj)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def unarchive(self, request, pk=None):
        obj = self.get_object()
        if not obj.archived_at:
            return Response(self.get_serializer(obj).data)
        clash = DocumentType.objects.filter(
            subject=obj.subject, name=obj.name, archived_at__isnull=True
        ).exists()
        if clash:
            raise ValidationError({"name": "Уже есть активный тип с таким названием"})
        with transaction.atomic():
            before = audit.snapshot(obj)
            obj.archived_at = None
            obj.save(update_fields=["archived_at"])
            self.audit_updated(before, obj)
        return Response(self.get_serializer(obj).data, status=status.HTTP_200_OK)
