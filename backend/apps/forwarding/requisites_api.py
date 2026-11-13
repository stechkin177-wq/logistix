import re
from copy import copy

from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError

from apps.core.audit.mixins import AuditedMixin
from apps.core.models import LegalEntity

from . import requisites
from .models import BankAccount, Carrier, Client
from .owner_permissions import OwnerSectionPermission

IBAN_RE = re.compile(r"[A-Z0-9]{1,34}")
CURRENCY_RE = re.compile(r"[A-Z]{3}")


class _OwnerField(serializers.PrimaryKeyRelatedField):
    model: type

    def get_queryset(self):  # менеджер компании вычисляется на запросе
        return self.model.objects.all()


class _ClientField(_OwnerField):
    model = Client


class _CarrierField(_OwnerField):
    model = Carrier


class _EntityField(_OwnerField):
    model = LegalEntity


class BankAccountSerializer(serializers.ModelSerializer):
    client = _ClientField(required=False, allow_null=True)
    carrier = _CarrierField(required=False, allow_null=True)
    legal_entity = _EntityField(required=False, allow_null=True)
    is_default = serializers.BooleanField(required=False)

    class Meta:
        model = BankAccount
        fields = [
            "id", "client", "carrier", "legal_entity", "bank", "bic", "iban", "kbe", "currency",
            "is_default", "note", "created_at",
        ]  # fmt: skip
        read_only_fields = ["id", "created_at"]
        # условные UniqueConstraint (один счёт по умолчанию) проверяет сервис, а не авто-валидаторы
        validators: list = []

    def validate_iban(self, value):
        value = value.replace(" ", "").upper()
        if value and not IBAN_RE.fullmatch(value):
            raise serializers.ValidationError("IBAN: только латинские буквы и цифры, до 34 знаков")
        return value

    def validate_currency(self, value):
        value = value.strip().upper()
        if value and not CURRENCY_RE.fullmatch(value):
            raise serializers.ValidationError("Код валюты из трёх латинских букв, например KZT")
        return value

    def validate(self, attrs):
        owners = [f for f in BankAccount.OWNER_FIELDS if attrs.get(f) is not None]
        if self.instance is None:
            if len(owners) != 1:
                raise serializers.ValidationError("Укажите ровно одного владельца счёта")
        else:
            changed = [f for f in owners if getattr(self.instance, f"{f}_id") != attrs[f].pk]
            if changed or any(f in attrs and attrs[f] is None for f in BankAccount.OWNER_FIELDS):
                raise serializers.ValidationError({"detail": "Владельца счёта изменить нельзя"})
        bank = attrs.get("bank", getattr(self.instance, "bank", ""))
        iban = attrs.get("iban", getattr(self.instance, "iban", ""))
        if not (bank or iban):
            raise serializers.ValidationError("Укажите банк или IBAN")
        owner = attrs[owners[0]] if owners else self.instance.owner
        field = requisites.owner_field(owner)
        if iban:
            dup = BankAccount.objects.filter(**{field: owner}, iban=iban)
            if self.instance is not None:
                dup = dup.exclude(pk=self.instance.pk)
            if dup.exists():
                raise serializers.ValidationError({"iban": "Такой счёт у владельца уже есть"})
        return attrs

    def create(self, validated_data):
        make_default = validated_data.pop("is_default", False)
        return requisites.save_account(BankAccount(**validated_data), make_default=make_default)

    def update(self, instance, validated_data):
        make_default = validated_data.pop("is_default", False)
        for key, value in validated_data.items():
            if key not in BankAccount.OWNER_FIELDS:
                setattr(instance, key, value)
        return requisites.save_account(instance, make_default=make_default)


class BankAccountViewSet(AuditedMixin, viewsets.ModelViewSet):
    """Банковские счета стороны: /api/bank-accounts/?client=|carrier=|legal_entity=<id>."""

    serializer_class = BankAccountSerializer
    permission_classes = [OwnerSectionPermission]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = BankAccount.objects.all()
        if self.action != "list":
            return qs
        params = self.request.query_params
        for field in BankAccount.OWNER_FIELDS:
            value = params.get(field)
            if value:
                if not value.isdigit():
                    raise ValidationError({field: "Ожидается числовой id"})
                return qs.filter(**{f"{field}_id": int(value)})
        raise ValidationError({"detail": "Укажите client, carrier или legal_entity"})

    def perform_destroy(self, instance):
        before = copy(instance)
        requisites.remove_account(instance)  # переназначает счёт по умолчанию и обновляет зеркало
        self.audit_deleted(before)
