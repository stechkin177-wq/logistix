from copy import copy

from django.db import IntegrityError, transaction
from django.db.models import Count, ProtectedError
from django.shortcuts import get_object_or_404
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core.api_permissions import SectionPermissionMixin, permission_required
from apps.core.audit import snapshot
from apps.core.audit.mixins import AuditedMixin
from apps.core.tenancy import get_current_company_id

from .models import Handbook, HandbookValue
from .services import is_status_handbook, make_initial, validate_value_change

CONFLICT_MESSAGE = "Конфликт данных: значение с таким кодом или начальный статус уже есть"
IN_USE_MESSAGE = "Значение используется в записях и не может быть удалено; деактивируйте его"


class HandbookValueSerializer(serializers.ModelSerializer):
    # справочник адресуется кодом; queryset - менеджер компании, вычисляется на запросе
    handbook = serializers.SlugRelatedField(slug_field="code", queryset=Handbook.objects)
    order = serializers.IntegerField(required=False, min_value=0)

    class Meta:
        model = HandbookValue
        fields = ["id", "handbook", "name", "code", "order", "is_initial", "is_final", "is_active"]
        read_only_fields = ["id"]
        extra_kwargs = {"code": {"trim_whitespace": False}}

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Название не может быть пустым")
        return value

    def validate_code(self, value):
        if value and not value.strip():
            raise serializers.ValidationError("Код не может состоять из пробелов")
        return value.strip()

    def validate(self, attrs):
        instance = self.instance
        handbook = attrs.get("handbook") or instance.handbook
        if instance is not None and handbook.pk != instance.handbook_id:
            raise serializers.ValidationError(
                {"handbook": "Нельзя перенести значение в другой справочник"}
            )
        code = attrs.get("code", instance.code if instance else "")
        if code:
            dup = HandbookValue.objects.filter(handbook=handbook, code=code)
            if instance is not None:
                dup = dup.exclude(pk=instance.pk)
            if dup.exists():
                raise serializers.ValidationError({"code": "Значение с таким кодом уже есть"})
        validate_value_change(handbook, instance, attrs)
        return attrs


class HandbookValueFilterMixin:
    @staticmethod
    def filter_values(qs, params):
        if code := params.get("handbook"):
            qs = qs.filter(handbook__code=code)
        if (active := params.get("is_active")) is not None:
            qs = qs.filter(is_active=active.lower() in ("1", "true", "yes"))
        return qs


class HandbookValueViewSet(
    AuditedMixin, HandbookValueFilterMixin, SectionPermissionMixin, viewsets.ModelViewSet
):
    permission_section = "handbooks"
    serializer_class = HandbookValueSerializer
    pagination_class = None

    def get_permissions(self):
        if getattr(self, "action", None) == "make_initial":
            return [permission_required("handbooks.update")()]
        return super().get_permissions()

    def get_queryset(self):
        qs = HandbookValue.objects.select_related("handbook").order_by("handbook_id", "order", "id")
        return self.filter_values(qs, self.request.query_params)

    def _conflict(self):
        return Response({"detail": CONFLICT_MESSAGE}, status=status.HTTP_409_CONFLICT)

    def create(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                return super().create(request, *args, **kwargs)
        except IntegrityError:
            return self._conflict()

    def update(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                return super().update(request, *args, **kwargs)
        except IntegrityError:
            return self._conflict()

    def get_create_kwargs(self, serializer):
        data = serializer.validated_data
        extra = {"company_id": get_current_company_id()}
        if "order" not in data:
            last = (
                HandbookValue.objects.filter(handbook=data["handbook"])
                .order_by("-order")
                .values_list("order", flat=True)
                .first()
            )
            extra["order"] = (last or 0) + 1
        return extra

    @action(detail=True, methods=["post"], url_path="make-initial")
    def make_initial(self, request, pk=None):
        value = self.get_object()
        if not is_status_handbook(value.handbook):
            raise ValidationError(
                {"detail": "Начальное значение есть только у справочников статусов"}
            )
        before = snapshot(value)
        try:
            with transaction.atomic():
                value = make_initial(value)
                self.audit_updated(before, value)
        except IntegrityError:
            return self._conflict()
        return Response(self.get_serializer(value).data)

    def destroy(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                value = self.get_object()
                if value.is_initial and is_status_handbook(value.handbook):
                    raise ValidationError({"detail": "Начальный статус нельзя удалить"})
                removed = copy(value)
                value.delete()
                self.audit_deleted(removed)
        except ProtectedError:
            return Response({"detail": IN_USE_MESSAGE}, status=status.HTTP_409_CONFLICT)
        return Response(status=status.HTTP_204_NO_CONTENT)


class HandbookSerializer(serializers.ModelSerializer):
    values_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Handbook
        fields = ["code", "name", "group", "values_count"]


class HandbookDetailSerializer(HandbookSerializer):
    values = serializers.SerializerMethodField()

    class Meta(HandbookSerializer.Meta):
        fields = [*HandbookSerializer.Meta.fields, "values"]

    def get_values(self, obj):
        values = HandbookValue.objects.filter(handbook=obj).order_by("order", "id")
        return HandbookValueSerializer(values, many=True).data


class HandbookViewSet(
    SectionPermissionMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Только чтение: набор справочников фиксирован. ?code=X возвращает один справочник
    со значениями (как /handbooks/X/)."""

    permission_section = "handbooks"
    serializer_class = HandbookSerializer
    pagination_class = None
    lookup_field = "code"

    def get_queryset(self):
        return Handbook.objects.annotate(values_count=Count("values")).order_by("group", "id")

    def get_serializer_class(self):
        return HandbookDetailSerializer if self.action == "retrieve" else HandbookSerializer

    def list(self, request, *args, **kwargs):
        if code := request.query_params.get("code"):
            obj = get_object_or_404(self.get_queryset(), code=code)
            return Response(HandbookDetailSerializer(obj).data)
        return super().list(request, *args, **kwargs)
