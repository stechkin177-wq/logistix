import re

from rest_framework import serializers

from .models import Insurance, Vehicle, VehicleDocument

# госномер: латиница/кириллица/цифры без пробелов и дефисов в нормализованном виде
PLATE_CLEAN_RE = re.compile(r"[\s\-]+")


class _VehicleField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):  # менеджер компании вычисляется на запросе
        return Vehicle.objects.all()


class _DatedValidationMixin:
    def validate(self, attrs):
        start = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        end = attrs.get("expires_at", getattr(self.instance, "expires_at", None))
        if start and end and end < start:
            raise serializers.ValidationError({"expires_at": "Срок действия раньше даты начала"})
        return attrs


class VehicleDocumentSerializer(_DatedValidationMixin, serializers.ModelSerializer):
    vehicle = _VehicleField()

    class Meta:
        model = VehicleDocument
        fields = ["id", "vehicle", "kind", "number", "starts_at", "expires_at", "notes"]


class InsuranceSerializer(_DatedValidationMixin, serializers.ModelSerializer):
    vehicle = _VehicleField()

    class Meta:
        model = Insurance
        fields = [
            "id",
            "vehicle",
            "kind",
            "policy_number",
            "insurer",
            "starts_at",
            "expires_at",
            "notes",
        ]


class VehicleSerializer(serializers.ModelSerializer):
    documents = VehicleDocumentSerializer(many=True, read_only=True)
    insurances = InsuranceSerializer(many=True, read_only=True)

    class Meta:
        model = Vehicle
        fields = [
            "id",
            "kind",
            "plate",
            "vin",
            "make",
            "model",
            "year",
            "body_type",
            "capacity_kg",
            "volume_m3",
            "status",
            "notes",
            "documents",
            "insurances",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate_plate(self, value):
        value = PLATE_CLEAN_RE.sub("", value).upper()
        if not value:
            raise serializers.ValidationError("Укажите госномер")
        return value

    def validate_year(self, value):
        if value is not None and not 1950 <= value <= 2100:
            raise serializers.ValidationError("Некорректный год выпуска")
        return value

    def validate_volume_m3(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Объём не может быть отрицательным")
        return value
