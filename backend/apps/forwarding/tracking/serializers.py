from django.utils import timezone
from rest_framework import serializers

from ..models import Carrier, ConsignmentPoint, Trip, TripConsignment
from .models import CargoTransfer, ConsignmentEvent


class _Ref(serializers.PrimaryKeyRelatedField):
    """Объект текущей компании (менеджер фильтрует по контексту)."""

    def __init__(self, model, **kwargs):
        self._model = model
        kwargs.setdefault("required", False)
        kwargs.setdefault("allow_null", True)
        super().__init__(**kwargs)

    def get_queryset(self):
        return self._model.objects.all()


class EventSerializer(serializers.ModelSerializer):
    event_type_name = serializers.CharField(source="get_event_type_display", read_only=True)
    stop_city = serializers.CharField(source="stop.city", read_only=True, default=None)
    stop_seq = serializers.IntegerField(source="stop.seq", read_only=True, default=None)
    trip_number = serializers.CharField(source="trip.number", read_only=True, default=None)

    class Meta:
        model = ConsignmentEvent
        fields = [
            "id",
            "consignment",
            "stop",
            "stop_seq",
            "stop_city",
            "leg",
            "trip",
            "trip_number",
            "event_type",
            "event_type_name",
            "occurred_at",
            "recorded_by",
            "source",
            "note",
            "created_at",
        ]
        read_only_fields = fields


class EventCreateSerializer(serializers.Serializer):
    event_type = serializers.ChoiceField(choices=ConsignmentEvent.TYPES)
    stop = _Ref(ConsignmentPoint)
    leg = _Ref(TripConsignment)
    trip = _Ref(Trip)
    occurred_at = serializers.DateTimeField(required=False)
    source = serializers.ChoiceField(choices=["manual", "driver_app"], default="manual")
    note = serializers.CharField(required=False, allow_blank=True, default="")


class TransferSerializer(serializers.ModelSerializer):
    transfer_kind_name = serializers.CharField(source="get_transfer_kind_display", read_only=True)
    consignment_name = serializers.CharField(source="consignment.name", read_only=True)
    order = serializers.IntegerField(source="consignment.order_id", read_only=True)
    order_number = serializers.CharField(source="consignment.order.number", read_only=True)
    to_stop_city = serializers.CharField(source="to_stop.city", read_only=True)
    from_trip_number = serializers.CharField(
        source="from_trip.number", read_only=True, default=None
    )
    to_trip_number = serializers.CharField(source="to_trip.number", read_only=True, default=None)
    from_carrier_name = serializers.CharField(
        source="from_carrier.name", read_only=True, default=None
    )
    to_carrier_name = serializers.CharField(source="to_carrier.name", read_only=True, default=None)
    reversed_by = serializers.SerializerMethodField()

    class Meta:
        model = CargoTransfer
        fields = [
            "id",
            "consignment",
            "consignment_name",
            "order",
            "order_number",
            "transfer_kind",
            "transfer_kind_name",
            "from_trip",
            "from_trip_number",
            "to_trip",
            "to_trip_number",
            "from_stop",
            "to_stop",
            "to_stop_city",
            "from_carrier",
            "from_carrier_name",
            "to_carrier",
            "to_carrier_name",
            "carrier_changed",
            "transferred_at",
            "weight_kg",
            "volume_m3",
            "pallets",
            "status",
            "initiated_by",
            "source",
            "confirmed_by",
            "confirmed_at",
            "reverses",
            "reversed_by",
            "note",
            "created_at",
        ]
        read_only_fields = fields

    def get_reversed_by(self, obj):
        reversals = list(obj.reversals.all())  # prefetch
        return reversals[0].pk if reversals else None


class TransferCreateSerializer(serializers.Serializer):
    transfer_kind = serializers.ChoiceField(choices=CargoTransfer.KINDS)
    to_stop = _Ref(ConsignmentPoint, required=True, allow_null=False)
    from_stop = _Ref(ConsignmentPoint)
    from_trip = _Ref(Trip)
    to_trip = _Ref(Trip)
    from_carrier = _Ref(Carrier)
    to_carrier = _Ref(Carrier)
    transferred_at = serializers.DateTimeField(required=False)
    weight_kg = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True, min_value=0
    )
    volume_m3 = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True, min_value=0
    )
    pallets = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    source = serializers.ChoiceField(choices=["manual", "driver_app"], default="manual")
    note = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        attrs.setdefault("transferred_at", timezone.now())
        return attrs
