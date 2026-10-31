from django.db import transaction
from rest_framework import serializers

from ..fields import ActiveHandbookField
from ..models import Consignment, ConsignmentPoint, Order
from . import services


class PointSerializer(serializers.ModelSerializer):
    country = ActiveHandbookField("country", allow_null=True, required=False)
    method = ActiveHandbookField("loading_method", allow_null=True, required=False)
    country_name = serializers.SerializerMethodField()
    method_name = serializers.SerializerMethodField()

    class Meta:
        model = ConsignmentPoint
        fields = [
            "id",
            "kind",
            "window_from",
            "window_to",
            "country",
            "country_name",
            "city",
            "street",
            "method",
            "method_name",
            "contact",
            "postal_code",
            "lat",
            "lng",
            "note",
        ]
        read_only_fields = ["id"]
        extra_kwargs = {
            "city": {"required": True, "allow_blank": False},
            "lat": {"min_value": -90, "max_value": 90},
            "lng": {"min_value": -180, "max_value": 180},
        }

    def get_country_name(self, obj):
        return obj.country.name if obj.country_id else None

    def get_method_name(self, obj):
        return obj.method.name if obj.method_id else None

    def validate_city(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Укажите город")
        return value

    def validate(self, attrs):
        start, end = attrs.get("window_from"), attrs.get("window_to")
        if start is not None and end is not None and end < start:
            raise serializers.ValidationError({"window_to": "Не может быть раньше начала окна"})
        return attrs


class ConsignmentBaseSerializer(serializers.ModelSerializer):
    """Груз с точками; наследники задают состав полей (с заказом и без)."""

    packaging = ActiveHandbookField("packaging", allow_null=True, required=False)
    status = ActiveHandbookField("consignment_status", required=False)
    packaging_name = serializers.SerializerMethodField()
    status_name = serializers.SerializerMethodField()
    points = PointSerializer(many=True)

    def get_packaging_name(self, obj):
        return obj.packaging.name if obj.packaging_id else None

    def get_status_name(self, obj):
        return obj.status.name

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Название не может быть пустым")
        return value

    def validate_points(self, items):
        kinds = [item.get("kind") for item in items]
        if sorted(map(str, kinds)) != sorted(services.KINDS):
            raise serializers.ValidationError("Нужны ровно две точки: погрузка и выгрузка")
        return items


NESTED_FIELDS = [
    "id",
    "name",
    "weight_kg",
    "volume_m3",
    "pallets",
    "packaging",
    "packaging_name",
    "status",
    "status_name",
    "points",
    "created_at",
]


class NestedConsignmentSerializer(ConsignmentBaseSerializer):
    """Груз внутри заказа (без поля order)."""

    class Meta:
        model = Consignment
        fields = NESTED_FIELDS
        read_only_fields = ["id", "created_at"]
        extra_kwargs = {"weight_kg": {"min_value": 0}, "volume_m3": {"min_value": 0}}


class OrderRefField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return Order.objects.all()  # заказы компании без удалённых


class ConsignmentSerializer(ConsignmentBaseSerializer):
    order = OrderRefField()
    order_number = serializers.CharField(source="order.number", read_only=True)

    class Meta:
        model = Consignment
        fields = ["order", "order_number", *NESTED_FIELDS]
        read_only_fields = ["id", "created_at"]
        extra_kwargs = {"weight_kg": {"min_value": 0}, "volume_m3": {"min_value": 0}}

    def validate_order(self, value):
        if self.instance is not None and value.pk != self.instance.order_id:
            raise serializers.ValidationError("Груз нельзя перенести в другой заказ")
        return value

    def create(self, validated_data):
        order = validated_data.pop("order")
        consignment = services.create_consignment(order, validated_data)
        consignment._points_changed = True
        return consignment

    def update(self, instance, validated_data):
        points = validated_data.pop("points", None)
        validated_data.pop("order", None)
        with transaction.atomic():
            instance = super().update(instance, validated_data)
            instance._points_changed = (
                services.update_points(instance, points) if points is not None else False
            )
        return instance
