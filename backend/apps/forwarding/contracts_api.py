from datetime import date

from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import APIException, ValidationError

from apps.core.audit.mixins import AuditedMixin
from apps.core.pagination import StandardPagination

from .models import Carrier, Client, Contract
from .owner_permissions import OwnerSectionPermission


class ContractInUse(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Договор выбран в заказах или рейсах и не может быть удалён"
    default_code = "contract_in_use"


class _ClientField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return Client.objects.all()


class _CarrierField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return Carrier.objects.all()


class ContractSerializer(serializers.ModelSerializer):
    client = _ClientField(required=False, allow_null=True)
    carrier = _CarrierField(required=False, allow_null=True)
    party_name = serializers.SerializerMethodField()
    is_expired = serializers.SerializerMethodField()
    in_use = serializers.SerializerMethodField()

    class Meta:
        model = Contract
        fields = [
            "id", "client", "carrier", "party_name", "kind", "number", "date", "valid_until",
            "title", "comment", "source", "is_expired", "in_use", "created_at",
        ]  # fmt: skip
        read_only_fields = ["id", "source", "created_at"]
        validators: list = []  # уникальность номера проверяет validate() с понятным текстом

    def get_party_name(self, obj):
        return (obj.client or obj.carrier).name

    def get_is_expired(self, obj):
        return obj.valid_until is not None and obj.valid_until < date.today()

    def get_in_use(self, obj):
        return obj.orders.exists() or obj.trips.exists()

    def validate_number(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Номер договора не может быть пустым")
        return value

    def validate(self, attrs):
        parties = [f for f in ("client", "carrier") if attrs.get(f) is not None]
        if self.instance is None:
            if len(parties) != 1:
                raise serializers.ValidationError(
                    "Укажите ровно одну сторону: клиента или перевозчика"
                )
        elif any(
            f in attrs and attrs[f] != getattr(self.instance, f) for f in ("client", "carrier")
        ):
            raise serializers.ValidationError({"detail": "Сторону договора изменить нельзя"})
        start = attrs.get("date", getattr(self.instance, "date", None))
        end = attrs.get("valid_until", getattr(self.instance, "valid_until", None))
        if start and end and end < start:
            raise serializers.ValidationError({"valid_until": "Срок действия раньше даты договора"})
        party = attrs[parties[0]] if parties else (self.instance.client or self.instance.carrier)
        field = "client" if isinstance(party, Client) else "carrier"
        number = attrs.get("number", getattr(self.instance, "number", None))
        dup = Contract.objects.filter(**{field: party, "number": number})
        if self.instance is not None:
            dup = dup.exclude(pk=self.instance.pk)
        if dup.exists():
            raise serializers.ValidationError(
                {"number": "Договор с таким номером у стороны уже есть"}
            )
        return attrs

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class ContractViewSet(AuditedMixin, viewsets.ModelViewSet):
    """Договоры сторон: /api/contracts/?client=|carrier=<id>; active=1 - только действующие."""

    serializer_class = ContractSerializer
    permission_classes = [OwnerSectionPermission]
    owner_fields = ("client", "carrier")
    pagination_class = StandardPagination
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = Contract.objects.select_related("client", "carrier")
        if self.action != "list":
            return qs
        params = self.request.query_params
        for field in self.owner_fields:
            value = params.get(field)
            if value:
                if not value.isdigit():
                    raise ValidationError({field: "Ожидается числовой id"})
                qs = qs.filter(**{f"{field}_id": int(value)})
                break
        else:
            raise ValidationError({"detail": "Укажите client или carrier"})
        if params.get("active") == "1":
            today = date.today()
            qs = qs.filter(valid_until__isnull=True) | qs.filter(valid_until__gte=today)
        return qs

    def perform_destroy(self, instance):
        if instance.orders.exists() or instance.trips.exists():
            raise ContractInUse()
        super().perform_destroy(instance)
