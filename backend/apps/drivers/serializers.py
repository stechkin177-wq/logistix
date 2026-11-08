import re

from rest_framework import serializers

from apps.core.models import Membership
from apps.core.phone import normalize_phone
from apps.core.tenancy import get_current_company_id

from .models import Driver, DriverDocument

IIN_RE = re.compile(r"[0-9]{12}")  # только ASCII-цифры


class _DriverField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):  # менеджер компании вычисляется на запросе
        return Driver.objects.all()


class DriverDocumentSerializer(serializers.ModelSerializer):
    driver = _DriverField()

    class Meta:
        model = DriverDocument
        fields = ["id", "driver", "kind", "number", "issued_at", "expires_at", "notes"]

    def validate(self, attrs):
        issued = attrs.get("issued_at", getattr(self.instance, "issued_at", None))
        expires = attrs.get("expires_at", getattr(self.instance, "expires_at", None))
        if issued and expires and expires < issued:
            raise serializers.ValidationError({"expires_at": "Срок действия раньше даты выдачи"})
        return attrs


class DriverSerializer(serializers.ModelSerializer):
    documents = DriverDocumentSerializer(many=True, read_only=True)

    class Meta:
        model = Driver
        fields = [
            "id",
            "full_name",
            "phone",
            "iin",
            "birth_date",
            "license_number",
            "license_categories",
            "license_expires",
            "status",
            "user",
            "notes",
            "documents",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate_full_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Укажите ФИО")
        return value

    def validate_phone(self, value):
        value = value.strip()
        if not value:
            return ""
        try:
            return normalize_phone(value)
        except ValueError:
            raise serializers.ValidationError("Некорректный номер телефона") from None

    def validate_iin(self, value):
        value = value.strip()
        if value and not IIN_RE.fullmatch(value):
            raise serializers.ValidationError("ИИН состоит из 12 цифр")
        return value

    def validate_user(self, value):
        if value is None:
            return value
        company_id = get_current_company_id()
        if not Membership.objects.filter(
            user=value, company_id=company_id, is_active=True
        ).exists():
            raise serializers.ValidationError("Пользователь не состоит в компании")
        return value
