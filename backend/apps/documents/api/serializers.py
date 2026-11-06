from rest_framework import serializers

from apps.finance.models import Invoice
from apps.forwarding.models import Client, Trip
from apps.forwarding.orders.models import Order

from ..models import KINDS


def _user(user):
    return {"id": user.pk, "full_name": user.full_name} if user else None


def version_data(version):
    return {
        "id": version.pk,
        "number": version.number,
        "sha256": version.sha256,
        "is_starter": version.is_starter,
        "uploaded_by": _user(version.uploaded_by),
        "created_at": version.created_at,
    }


def template_data(template):
    version = template.current_version
    return {
        "id": template.pk,
        "kind": template.kind,
        "name": template.name,
        "language": template.language,
        "is_active": template.is_active,
        "current_version": version_data(version) if version else None,
        "versions_count": template.versions_count,
    }


def _ref(obj, field):
    return {"id": obj.pk, field: getattr(obj, field)} if obj else None


def issued_data(doc):
    version = doc.template_version
    return {
        "id": doc.pk,
        "kind": doc.kind,
        "number": doc.number,
        "issue_date": doc.issue_date,
        "language": doc.language,
        "client": _ref(doc.client, "name"),
        "order": _ref(doc.order, "number"),
        "trip": _ref(doc.trip, "number"),
        "invoice": _ref(doc.invoice, "number"),
        "template_version": {
            "id": version.pk,
            "number": version.number,
            "template": version.template_id,
        },
        "created_by": _user(doc.created_by),
        "created_at": doc.created_at,
    }


class TemplatePatchSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False)
    is_active = serializers.BooleanField(required=False)

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Название не может быть пустым")
        return value


class TenantRefField(serializers.PrimaryKeyRelatedField):
    """Ссылка на запись компании: queryset строится лениво, внутри контекста компании."""

    def __init__(self, model, **kwargs):
        self.model = model
        super().__init__(queryset=model._base_manager.none(), **kwargs)

    def get_queryset(self):
        return self.model.objects.all()


class IssueSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=KINDS)
    client = TenantRefField(Client, required=False, allow_null=True)
    order = TenantRefField(Order, required=False, allow_null=True)
    trip = TenantRefField(Trip, required=False, allow_null=True)
    invoice = TenantRefField(Invoice, required=False, allow_null=True)
    letter = serializers.DictField(required=False, allow_null=True)
    language = serializers.CharField(max_length=8, required=False, allow_null=True)

    def validate(self, attrs):
        from ..services import SOURCES

        kind = attrs["kind"]
        needed = SOURCES[kind][0]
        given = {k for k in ("client", "order", "trip", "invoice") if attrs.get(k) is not None}
        allowed = {needed} if needed else set()
        if kind == "letter":
            allowed = {"order"}  # письмо можно привязать к заказу, источник не обязателен
        if (needed and needed not in given) or (given - allowed):
            raise serializers.ValidationError(
                {"detail": "Укажите ровно один источник, подходящий виду документа."}
                if needed
                else {"detail": "Для этого вида источник указывается только заказом."}
            )
        if kind != "letter" and attrs.get("letter"):
            raise serializers.ValidationError({"letter": "Поле только для вида «письмо»."})
        return attrs
