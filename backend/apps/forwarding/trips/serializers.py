from collections.abc import Mapping

from rest_framework import serializers

from apps.core.audit.services import client_ip
from apps.core.handbooks.models import HandbookValue

from ..fields import ActiveHandbookField, CurrentTolerantField
from ..models import Carrier, Trip
from .services import change_trip_status, create_trip, reassign

SERVER_FIELDS = {
    "number": "Номер выдаётся автоматически",
    "status": "Статус меняется действием POST /api/trips/{id}/status/",
    "is_consolidated": "Признак сборного рейса вычисляется по грузам",
}
MAX_CONSIGNMENTS = 500


class CarrierField(CurrentTolerantField):
    def get_queryset(self):  # перевозчики компании без удалённых, только активные
        return Carrier.objects.filter(status=Carrier.ACTIVE)


class TripSerializer(serializers.ModelSerializer):
    """Рейс: чтение и PATCH (перевозчик, госномер, водитель, цена, валюта).

    Грузы меняются действием reassign, статус - действием status; в выводе consignments -
    список действующих грузов (без удалённых и грузов удалённых заказов).
    """

    carrier = CarrierField(allow_null=True, required=False)
    currency = ActiveHandbookField("currency", required=False)
    carrier_name = serializers.SerializerMethodField()
    status_name = serializers.CharField(source="status.name", read_only=True)
    orders = serializers.SerializerMethodField()
    consignments = serializers.SerializerMethodField()

    class Meta:
        model = Trip
        fields = [
            "id",
            "number",
            "carrier",
            "carrier_name",
            "vehicle_plate",
            "driver_name",
            "price",
            "currency",
            "status",
            "status_name",
            "is_consolidated",
            "orders",
            "consignments",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "number",
            "status",
            "is_consolidated",
            "created_by",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {"price": {"min_value": 0}}

    forbidden = {
        **SERVER_FIELDS,
        "consignments": "Грузы меняются действием POST /api/trips/{id}/reassign/",
    }

    def get_carrier_name(self, obj):
        return obj.carrier.name if obj.carrier_id else None

    def _cargos(self, obj):
        return list(obj.consignments.all())  # prefetch: только действующие грузы, по id

    def get_orders(self, obj):
        seen = {}
        for c in self._cargos(obj):
            seen.setdefault(c.order_id, {"id": c.order_id, "number": c.order.number})
        return sorted(seen.values(), key=lambda o: o["id"])

    def get_consignments(self, obj):
        return [
            {"id": c.pk, "name": c.name, "order": c.order_id, "order_number": c.order.number}
            for c in self._cargos(obj)
        ]

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            errors = {name: [text] for name, text in self.forbidden.items() if name in data}
            if errors:
                raise serializers.ValidationError(errors)
        return super().to_internal_value(data)

    def validate_driver_name(self, value):
        return value.strip()

    def validate_vehicle_plate(self, value):
        return value.strip()


class TripCreateSerializer(TripSerializer):
    """Создание: consignments - список id грузов (не менее одного)."""

    forbidden = SERVER_FIELDS

    consignments = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        max_length=MAX_CONSIGNMENTS,
        write_only=True,
    )

    def create(self, validated_data):
        request = self.context["request"]
        ids = validated_data.pop("consignments")
        carrier = validated_data.pop("carrier", None)
        return create_trip(
            ids,
            carrier.pk if carrier else None,
            validated_data,
            request.user,
            ip=client_ip(request),
        )


class ReassignSerializer(serializers.Serializer):
    consignment_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=False, max_length=MAX_CONSIGNMENTS
    )

    def save(self, trip, user, ip=None):
        return reassign(trip, self.validated_data["consignment_ids"], user, ip=ip)


class TripStatusField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return HandbookValue.objects.filter(handbook__code="trip_status").select_related("handbook")


class TripStatusSerializer(serializers.Serializer):
    status = TripStatusField()

    def save(self, trip, user, ip=None):
        return change_trip_status(trip, self.validated_data["status"], user, ip=ip)
