import re

from rest_framework import serializers

from apps.core.document_types import validate_with_type, vehicle_subject
from apps.core.models import DocumentType

from .models import FuelFill, Insurance, MileageReading, ServiceRecord, Vehicle, VehicleDocument

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


class _DocTypeField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):  # менеджер компании вычисляется на запросе
        return DocumentType.objects.all()


class VehicleDocumentSerializer(_DatedValidationMixin, serializers.ModelSerializer):
    vehicle = _VehicleField()
    doc_type = _DocTypeField(required=False, allow_null=True)
    doc_type_name = serializers.CharField(source="doc_type.name", read_only=True, default="")

    class Meta:
        model = VehicleDocument
        fields = [
            "id", "vehicle", "doc_type", "doc_type_name", "kind", "number", "issued_by",
            "starts_at", "expires_at", "notes", "extra",
        ]  # fmt: skip

    def validate(self, attrs):
        attrs = super().validate(attrs)
        vehicle = attrs.get("vehicle") or getattr(self.instance, "vehicle", None)
        return validate_with_type(attrs, self.instance, vehicle_subject(vehicle), "starts_at")


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
            "gps_check",
            "initial_odometer_km",
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

    def validate_initial_odometer_km(self, value):
        """Начальный пробег не больше первого показания по рейсу (иначе пробег «убывал» бы)."""
        if value is not None and self.instance is not None:
            first = self.instance.mileage.order_by("recorded_at", "id").first()
            if first is not None and value > first.odometer_km:
                raise serializers.ValidationError(
                    f"Начальный пробег больше первого показания по рейсу ({first.odometer_km} км)"
                )
        return value

    def validate_volume_m3(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Объём не может быть отрицательным")
        return value


# --- эксплуатационный учёт (2.4) -------------------------------------------------------------


class _ExpenseField(serializers.PrimaryKeyRelatedField):
    """Расход Finance G1 компании (только активный). Fleet сам денег не хранит."""

    def get_queryset(self):
        from apps.finance.models import Expense

        return Expense.objects.all()

    def to_internal_value(self, data):
        expense = super().to_internal_value(data)
        if expense.status != "active":
            raise serializers.ValidationError("Расход аннулирован")
        return expense


def _require_finance(attrs):
    """Связь с расходом возможна, только если модуль finance включён и есть в тарифе."""
    from apps.core.tenancy import get_current_company_id
    from apps.forwarding.trips.resources import effective_modules

    if attrs.get("expense") is not None and "finance" not in effective_modules(
        get_current_company_id()
    ):
        raise serializers.ValidationError({"expense": "Модуль финансов не подключён"})


class MileageSerializer(serializers.ModelSerializer):
    """Официальный пробег: только чтение (создаётся при выезде в рейс и по его завершении)."""

    vehicle = _VehicleField(read_only=True)
    trip = serializers.IntegerField(source="trip_id", read_only=True)

    class Meta:
        model = MileageReading
        fields = ["id", "vehicle", "trip", "recorded_at", "odometer_km", "source", "note"]
        read_only_fields = fields


class ServiceRecordSerializer(serializers.ModelSerializer):
    vehicle = _VehicleField()
    expense = _ExpenseField(allow_null=True, required=False)

    class Meta:
        model = ServiceRecord
        fields = [
            "id",
            "vehicle",
            "kind",
            "status",
            "title",
            "planned_date",
            "done_date",
            "odometer_km",
            "description",
            "next_due_date",
            "next_due_km",
            "expense",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Укажите название работ")
        return value

    def validate(self, attrs):
        status = attrs.get("status", getattr(self.instance, "status", "planned"))
        done = attrs.get("done_date", getattr(self.instance, "done_date", None))
        if status == "done" and done is None:
            raise serializers.ValidationError({"done_date": "Укажите дату выполнения"})
        _require_finance(attrs)
        return attrs


class FuelFillSerializer(serializers.ModelSerializer):
    vehicle = _VehicleField()
    expense = _ExpenseField(allow_null=True, required=False)
    l_per_100km = serializers.SerializerMethodField()

    class Meta:
        model = FuelFill
        fields = [
            "id",
            "vehicle",
            "filled_at",
            "liters",
            "odometer_km",
            "full_tank",
            "fuel_type",
            "station",
            "note",
            "expense",
            "l_per_100km",
        ]

    def get_l_per_100km(self, obj):
        """Расход сегмента, закрытого этой заправкой (считается списком для всей выборки)."""
        value = self.context.get("consumption", {}).get(obj.pk)
        return None if value is None else str(value)

    def validate_liters(self, value):
        if value <= 0:
            raise serializers.ValidationError("Количество литров должно быть больше нуля")
        return value

    def validate(self, attrs):
        _require_finance(attrs)
        return attrs
