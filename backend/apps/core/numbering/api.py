from django.db import transaction
from rest_framework import mixins, serializers, viewsets
from rest_framework.response import Response

from apps.core.api_permissions import SectionPermissionMixin
from apps.core.audit.mixins import AuditedMixin

from .models import NumberingRule
from .services import KINDS, MAX_DIGITS, peek_number, sample_numbers, validate_template


class NumberingRuleSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    sample = serializers.SerializerMethodField()
    digits = serializers.IntegerField(min_value=0, max_value=MAX_DIGITS)
    next_value = serializers.IntegerField(min_value=1, max_value=2**31 - 1)

    class Meta:
        model = NumberingRule
        fields = ["kind", "name", "description", "template", "digits", "next_value", "sample"]
        read_only_fields = ["kind"]

    def get_name(self, obj):
        return KINDS[obj.kind]["name"]

    def get_description(self, obj):
        return KINDS[obj.kind]["description"]

    def get_sample(self, obj):
        samples = self.context.get("samples")
        if samples is not None:
            return samples[obj.kind]
        if obj.kind == "trip":
            order = peek_number("order")
            return peek_number("trip", order=order, n=1)
        return peek_number(obj.kind)

    def validate_template(self, value):
        value = value.strip()
        errors = validate_template(self.instance.kind, value)
        if errors:
            raise serializers.ValidationError(errors)
        return value


class NumberingRuleViewSet(
    AuditedMixin,
    SectionPermissionMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Правила нумерации: набор фиксирован (5 видов), создать и удалить нельзя."""

    permission_section = "numbering"
    serializer_class = NumberingRuleSerializer
    pagination_class = None
    lookup_field = "kind"
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        order = list(KINDS)
        return sorted(NumberingRule.objects.all(), key=lambda r: order.index(r.kind))

    def get_object(self):
        # строка блокируется до записи: правка не гонится с выдачей номера
        obj = NumberingRule.objects.select_for_update().filter(kind=self.kwargs["kind"]).first()
        if obj is None:
            from django.http import Http404

            raise Http404
        return obj

    def list(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            self.get_queryset(),
            many=True,
            context={**self.get_serializer_context(), "samples": sample_numbers()},
        )
        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        with transaction.atomic():
            return super().partial_update(request, *args, **kwargs)
