from datetime import datetime, time, timedelta

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import mixins, serializers, viewsets
from rest_framework.exceptions import ValidationError

from apps.core.api_permissions import permission_required
from apps.core.pagination import StandardPagination

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = [
            "id",
            "user",
            "action",
            "object_type",
            "object_id",
            "object_repr",
            "changes",
            "ip",
            "created_at",
        ]
        read_only_fields = fields


def _parse_bound(name: str, raw: str, *, end: bool):
    """Дата (границы суток включительно) или дата-время ISO; иначе 400."""
    day = parse_date(raw)  # сначала дата: parse_datetime принимает и "2026-05-01" (полночь)
    if day is not None:
        start = timezone.make_aware(datetime.combine(day, time.min))
        return (start + timedelta(days=1), True) if end else (start, False)
    dt = parse_datetime(raw)
    if dt is None:
        raise ValidationError({name: "Ожидается дата или дата-время ISO 8601"})
    return (timezone.make_aware(dt) if timezone.is_naive(dt) else dt), False


class AuditLogViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Журнал аудита: только чтение (право company.view); изменение записей API не даёт."""

    permission_classes = [permission_required("company.view")]
    serializer_class = AuditLogSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = AuditLog.objects.all()
        params = self.request.query_params
        for field in ("action", "object_type", "object_id"):
            if value := params.get(field):
                qs = qs.filter(**{field: value})
        if value := params.get("user"):
            if not value.isdigit():
                raise ValidationError({"user": "Ожидается числовой id"})
            qs = qs.filter(user_id=int(value))
        if value := params.get("created_from"):
            bound, _ = _parse_bound("created_from", value, end=False)
            qs = qs.filter(created_at__gte=bound)
        if value := params.get("created_to"):
            bound, exclusive = _parse_bound("created_to", value, end=True)
            qs = qs.filter(**{"created_at__lt" if exclusive else "created_at__lte": bound})
        return qs
