from django.db import transaction
from rest_framework import serializers

from ..fields import ActiveHandbookField
from ..models import Consignment, ConsignmentPoint, Order
from . import services


class _AnyHandbookField(ActiveHandbookField):
    """Значение справочника компании без проверки активности: активность проверяет
    validate_points родительского сериализатора, который знает текущие точки груза."""

    def to_internal_value(self, data):
        return serializers.PrimaryKeyRelatedField.to_internal_value(self, data)


class PointSerializer(serializers.ModelSerializer):
    """Точка груза. Отключённые значения справочников (страна, способ) отвергаются в
    ConsignmentBaseSerializer.validate_points, кроме неизменённого значения той же точки."""

    country = _AnyHandbookField("country", allow_null=True, required=False)
    method = _AnyHandbookField("loading_method", allow_null=True, required=False)
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
        current = {}
        if isinstance(self.instance, Consignment):
            current = {p.kind: p for p in self.instance.points.all()}
        errors = {}
        for index, item in enumerate(items):
            old = current.get(item.get("kind"))
            for field, attr in (("country", "country_id"), ("method", "method_id")):
                value = item.get(field)
                if value is None or value.is_active:
                    continue
                if old is not None and getattr(old, attr) == value.pk:
                    continue  # неизменённое значение той же точки остаётся допустимым
                errors.setdefault(index, {})[field] = ["Значение справочника отключено"]
        if errors:
            raise serializers.ValidationError(errors)
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
    client = serializers.IntegerField(source="order.client_id", read_only=True)
    client_name = serializers.CharField(source="order.client.name", read_only=True)
    trips_count = serializers.SerializerMethodField()

    class Meta:
        model = Consignment
        fields = ["order", "order_number", "client", "client_name", *NESTED_FIELDS, "trips_count"]
        read_only_fields = ["id", "created_at"]
        extra_kwargs = {"weight_kg": {"min_value": 0}, "volume_m3": {"min_value": 0}}

    def get_trips_count(self, obj):
        """Не удалённые рейсы с грузом: аннотация списка/деталей, иначе (после создания) запрос."""
        count = getattr(obj, "trips_count", None)
        if count is None:
            count = obj.trip_links.filter(trip__deleted_at__isnull=True).count()
        return count

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
