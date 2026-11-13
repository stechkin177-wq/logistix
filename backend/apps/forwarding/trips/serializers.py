from collections.abc import Mapping

from rest_framework import serializers

from apps.core.audit.services import client_ip
from apps.core.handbooks.models import HandbookValue
from apps.core.tenancy import get_current_company_id
from apps.drivers.models import Driver
from apps.fleet.models import Vehicle

from ..fields import ActiveHandbookField, CurrentTolerantField
from ..models import Carrier, Contract, Trip, TripConsignment
from . import odometer
from .resources import validate_assignment
from .services import change_trip_status, create_trip, reassign

SERVER_FIELDS = {
    "number": "Номер выдаётся автоматически",
    "status": "Статус меняется действием POST /api/trips/{id}/status/",
    "is_consolidated": "Признак сборного рейса вычисляется по грузам",
    "completed_at": "Время завершения выставляется автоматически при смене статуса",
}
MAX_CONSIGNMENTS = 500
MAX_LEGS = 500
PRICE_CONFLICT = "Поля price и carrier_price различаются: передайте одно значение"


class StopRefSerializer(serializers.Serializer):
    """Остановка участка (кратко): для ленты маршрута."""

    id = serializers.IntegerField()
    seq = serializers.IntegerField()
    kind = serializers.CharField()
    city = serializers.CharField()


class LegSerializer(serializers.ModelSerializer):
    """Участок перевозки (TripConsignment) в ответе рейса."""

    consignment_name = serializers.CharField(source="consignment.name", read_only=True)
    order = serializers.IntegerField(source="consignment.order_id", read_only=True)
    order_number = serializers.CharField(source="consignment.order.number", read_only=True)
    from_stop = StopRefSerializer(read_only=True)
    to_stop = StopRefSerializer(read_only=True)

    class Meta:
        model = TripConsignment
        fields = [
            "id",
            "consignment",
            "consignment_name",
            "order",
            "order_number",
            "from_stop",
            "to_stop",
            "leg_seq",
            "status",
            "weight_kg",
            "volume_m3",
            "pallets",
        ]
        read_only_fields = fields


class SharesSerializer(serializers.Serializer):
    """Доли груза на участке; пусто (или не указано) - весь груз по этому измерению."""

    weight_kg = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=0, required=False, allow_null=True
    )
    volume_m3 = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=0, required=False, allow_null=True
    )
    pallets = serializers.IntegerField(min_value=0, required=False, allow_null=True)


class LegInputSerializer(serializers.Serializer):
    """Участок в запросе: груз, остановки (обе или ни одной - весь маршрут), доли."""

    consignment = serializers.IntegerField(min_value=1)
    from_stop = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    to_stop = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    shares = SharesSerializer(required=False)

    def validate(self, attrs):
        if (attrs.get("from_stop") is None) != (attrs.get("to_stop") is None):
            raise serializers.ValidationError("Укажите обе остановки участка или ни одной")
        return attrs


class CarrierField(CurrentTolerantField):
    def get_queryset(self):  # перевозчики компании без удалённых, только активные
        return Carrier.objects.filter(status=Carrier.ACTIVE)


class VehicleField(CurrentTolerantField):
    def get_queryset(self):  # техника компании без удалённой
        return Vehicle.objects.all()


class TripContractField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):  # договоры компании без удалённых
        return Contract.objects.filter(carrier__isnull=False)


class DriverField(CurrentTolerantField):
    def get_queryset(self):  # водители компании без удалённых
        return Driver.objects.all()


class TripSerializer(serializers.ModelSerializer):
    """Рейс: чтение и PATCH (перевозчик, госномер, водитель, цена, валюта).

    Грузы меняются действием reassign, статус - действием status; в выводе consignments -
    список действующих грузов (без удалённых и грузов удалённых заказов).
    """

    carrier = CarrierField(allow_null=True, required=False)
    vehicle = VehicleField(allow_null=True, required=False)
    trailer = VehicleField(allow_null=True, required=False)
    driver = DriverField(allow_null=True, required=False)
    contract = TripContractField(allow_null=True, required=False)
    currency = ActiveHandbookField("currency", required=False)
    # price - временный алиас carrier_price (чтение и запись); удаляется отдельным решением
    price = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=0, required=False, source="carrier_price"
    )
    carrier_name = serializers.SerializerMethodField()
    status_name = serializers.CharField(source="status.name", read_only=True)
    orders = serializers.SerializerMethodField()
    consignments = serializers.SerializerMethodField()
    legs = serializers.SerializerMethodField()

    class Meta:
        model = Trip
        fields = [
            "id",
            "number",
            "carrier",
            "carrier_name",
            "vehicle",
            "trailer",
            "driver",
            "contract",
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
            "legs",
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
        "legs": "Участки меняются действием POST /api/trips/{id}/reassign/",
    }

    def get_carrier_name(self, obj):
        return obj.carrier.name if obj.carrier_id else None

    def _cargos(self, obj):
        # prefetch: только действующие грузы, по id; груз с несколькими участками в рейсе - один раз
        return list({c.pk: c for c in obj.consignments.all()}.values())

    def get_legs(self, obj):
        """Участки рейса (груз, откуда-куда, статус, доли); по грузам и порядку маршрута."""
        return LegSerializer(obj.links.all(), many=True, context=self.context).data

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

    def _check_contract(self, attrs):
        """Договор рейса - договор его перевозчика; смена перевозчика снимает чужой договор."""
        if "carrier" in attrs:
            carrier = attrs["carrier"]
        else:
            carrier = getattr(self.instance, "carrier", None)
        contract = attrs.get("contract")
        if contract is not None:
            if carrier is None or contract.carrier_id != carrier.pk:
                raise serializers.ValidationError(
                    {"contract": "Договор принадлежит другому перевозчику"}
                )
        elif (
            "contract" not in attrs
            and "carrier" in attrs
            and self.instance is not None
            and self.instance.contract_id is not None
            and (carrier is None or self.instance.contract.carrier_id != carrier.pk)
        ):
            attrs["contract"] = None

    def validate(self, attrs):
        attrs = super().validate(attrs)
        self._check_contract(attrs)
        if any(k in attrs for k in ("vehicle", "trailer", "driver")):
            attrs.update(validate_assignment(attrs, self.instance, get_current_company_id()))
        return attrs

    def validate_driver_name(self, value):
        return value.strip()

    def validate_vehicle_plate(self, value):
        return value.strip()


class TripCreateSerializer(TripSerializer):
    """Создание: consignments - список id грузов (не менее одного)."""

    forbidden = {**SERVER_FIELDS, "contract": "Договор выбирается после создания рейса"}

    # грузы на весь маршрут; вместе с ним (или вместо) можно передать явные участки legs
    consignments = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=True,
        required=False,
        max_length=MAX_CONSIGNMENTS,
        write_only=True,
    )
    legs = LegInputSerializer(many=True, required=False, write_only=True, max_length=MAX_LEGS)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if not attrs.get("consignments") and not attrs.get("legs"):
            raise serializers.ValidationError(
                {"consignments": "В рейсе должен быть хотя бы один груз"}
            )
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        ids = validated_data.pop("consignments", [])
        legs = validated_data.pop("legs", [])
        carrier = validated_data.pop("carrier", None)
        return create_trip(
            ids,
            carrier.pk if carrier else None,
            validated_data,
            request.user,
            legs=legs,
            ip=client_ip(request),
        )


class ReassignSerializer(serializers.Serializer):
    consignment_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=True,
        required=False,
        max_length=MAX_CONSIGNMENTS,
    )
    legs = LegInputSerializer(many=True, required=False, max_length=MAX_LEGS)

    def validate(self, attrs):
        if not attrs.get("consignment_ids") and not attrs.get("legs"):
            raise serializers.ValidationError(
                {"consignment_ids": "В рейсе должен быть хотя бы один груз"}
            )
        return attrs

    def save(self, trip, user, ip=None):
        return reassign(
            trip,
            self.validated_data.get("consignment_ids", []),
            user,
            legs=self.validated_data.get("legs", []),
            ip=ip,
        )


class TripStatusField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return HandbookValue.objects.filter(handbook__code="trip_status").select_related("handbook")


class TripStatusSerializer(serializers.Serializer):
    status = TripStatusField()
    # обязательна только при выходе из статуса «Завершён» (проверяет сервис)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=1000, default="")
    # официальный пробег по отчёту водителя (необязательно): при выезде и при завершении
    vehicle_km = serializers.IntegerField(required=False, min_value=0, max_value=10_000_000)
    trailer_km = serializers.IntegerField(required=False, min_value=0, max_value=10_000_000)

    def validate(self, attrs):
        if ("vehicle_km" in attrs or "trailer_km" in attrs) and odometer.phase_for_transition(
            "", attrs["status"].code
        ) is None:
            raise serializers.ValidationError(
                {"vehicle_km": "Пробег фиксируется только при выезде в рейс и при его завершении"}
            )
        return attrs

    def save(self, trip, user, ip=None, can_revert=False, perms=(), adjust_reason=None):
        phase = odometer.phase_for_transition(trip.status.code, self.validated_data["status"].code)
        given = "vehicle_km" in self.validated_data or "trailer_km" in self.validated_data
        if given and phase is None:  # до смены статуса: ничего не меняем
            raise serializers.ValidationError(
                {"vehicle_km": "Пробег фиксируется только при выезде в рейс и при его завершении"}
            )
        saved = self._save(trip, user, ip, can_revert, perms, adjust_reason)
        if phase:
            odometer.record(
                saved,
                phase,
                vehicle_km=self.validated_data.get("vehicle_km"),
                trailer_km=self.validated_data.get("trailer_km"),
            )
        return saved

    def _save(self, trip, user, ip, can_revert, perms, adjust_reason):
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


class TripOdometerSerializer(serializers.Serializer):
    """Позднее внесение или исправление официального пробега рейса."""

    phase = serializers.ChoiceField(choices=[odometer.START, odometer.END])
    vehicle_km = serializers.IntegerField(required=False, min_value=0, max_value=10_000_000)
    trailer_km = serializers.IntegerField(required=False, min_value=0, max_value=10_000_000)

    def validate(self, attrs):
        if "vehicle_km" not in attrs and "trailer_km" not in attrs:
            raise serializers.ValidationError({"vehicle_km": "Укажите пробег тягача или прицепа"})
        return attrs
