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
    "completed_at": "Время завершения выставляется автоматически при смене статуса",
}
MAX_CONSIGNMENTS = 500
PRICE_CONFLICT = "Поля price и carrier_price различаются: передайте одно значение"


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
    # price - временный алиас carrier_price (чтение и запись); удаляется отдельным решением
    price = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=0, required=False, source="carrier_price"
    )
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
            "carrier_price",
            "price",
            "currency",
            "status",
            "status_name",
            "is_consolidated",
            "completed_at",
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
            "completed_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {"carrier_price": {"min_value": 0}}

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
            self._check_price_alias(data)
        return super().to_internal_value(data)

    def _check_price_alias(self, data):
        """Оба поля в запросе с разными значениями (сравнение Decimal) -> 400 на `price`.

        Некорректные значения здесь пропускаются: их сообщит обычная валидация полей.
        """
        if "price" not in data or "carrier_price" not in data:
            return
        try:
            alias = self.fields["price"].run_validation(data["price"])
            main = self.fields["carrier_price"].run_validation(data["carrier_price"])
        except serializers.ValidationError:
            return
        if alias != main:
            raise serializers.ValidationError({"price": [PRICE_CONFLICT]})

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
    # обязательна только при выходе из статуса «Завершён» (проверяет сервис)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=1000, default="")

    def save(self, trip, user, ip=None, can_revert=False, perms=(), adjust_reason=None):
        return change_trip_status(
            trip,
            self.validated_data["status"],
            user,
            ip=ip,
            reason=self.validated_data.get("reason", ""),
            can_revert=can_revert,
            perms=perms,
            adjust_reason=adjust_reason,
        )
