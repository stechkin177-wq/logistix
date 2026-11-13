from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import labels as label_service
from apps.core.api_permissions import permission_required
from apps.core.audit.mixins import AuditedMixin
from apps.core.audit.services import client_ip
from apps.core.models import LABEL_COLORS, Label

READ_SECTIONS = ("orders", "trips", "clients", "carriers")


def _has(request, view, code: str) -> bool:
    return permission_required(code)().has_permission(request, view)


class LabelPermission(BasePermission):
    """Чтение - тем, кто видит хотя бы один размечаемый раздел; изменение - labels.manage."""

    def has_permission(self, request, view):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return any(_has(request, view, f"{s}.view") for s in READ_SECTIONS)
        return _has(request, view, "labels.manage")


class LabelSerializer(serializers.ModelSerializer):
    usage_count = serializers.SerializerMethodField()

    class Meta:
        model = Label
        fields = ["id", "name", "color", "usage_count", "created_at"]
        read_only_fields = ["id", "created_at"]
        validators: list = []

    def get_usage_count(self, obj):
        return obj.assignments.count()

    def validate_name(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Название метки не может быть пустым")
        dup = Label.objects.filter(name__iexact=value)
        if self.instance is not None:
            dup = dup.exclude(pk=self.instance.pk)
        if dup.exists():
            raise serializers.ValidationError("Метка с таким названием уже есть")
        return value

    def validate_color(self, value):
        if value not in LABEL_COLORS:
            raise serializers.ValidationError(f"Допустимые цвета: {', '.join(LABEL_COLORS)}")
        return value


class LabelViewSet(AuditedMixin, viewsets.ModelViewSet):
    """Метки компании: /api/labels/ (создание, правка, удаление - право labels.manage)."""

    serializer_class = LabelSerializer
    permission_classes = [LabelPermission]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return Label.objects.all()

    def get_create_kwargs(self, serializer):
        return {"created_by": self.request.user}


class SubjectLabelsView(APIView):
    """Метки объекта: GET - текущие, PUT {labels: [id]} - заменить набор.

    Чтение - право <раздел>.view объекта, замена - <раздел>.update: метить может тот, кто
    правит объект."""

    def _subject(self, request, kind, pk, need):
        found = label_service.subject_for(kind, pk)
        if found is None:
            raise NotFound("Неизвестный тип объекта")
        model_label, section, obj = found
        if not _has(request, self, f"{section}.{need}"):
            raise PermissionDenied()
        if obj is None:
            raise NotFound("Объект не найден")
        return model_label, obj

    def get(self, request, kind, pk):
        model_label, obj = self._subject(request, kind, pk, "view")
        return Response(label_service.labels_map(model_label, [obj.pk]).get(obj.pk, []))

    def put(self, request, kind, pk):
        model_label, obj = self._subject(request, kind, pk, "update")
        ids = request.data.get("labels") if hasattr(request.data, "get") else None
        if not isinstance(ids, list) or not all(
            isinstance(i, int) and not isinstance(i, bool) for i in ids
        ):
            raise ValidationError({"labels": "Ожидается список id меток"})
        result = label_service.set_labels(
            model_label, obj, ids, request.user, ip=client_ip(request)
        )
        return Response(result)
