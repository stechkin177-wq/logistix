from django.db import IntegrityError, transaction
from rest_framework import serializers

from ..models import Order, OrderService, Trip, TripConsignment

CARRIER_CATEGORY = "Перевозка"

BASE_LINE_MESSAGE = "Начальная ставка ведётся автоматически: измените ставку клиента в заказе"


class LineOrderField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return Order.objects.all()  # заказы компании без удалённых


class LineTripField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return Trip.objects.all()  # рейсы компании без удалённых


class OrderServiceSerializer(serializers.ModelSerializer):
    order = LineOrderField()
    order_number = serializers.CharField(source="order.number", read_only=True)
    # рейс, оплату перевозчику которого отражает строка (необязательно); защищает от двойного учёта
    trip = LineTripField(required=False, allow_null=True)
    trip_number = serializers.CharField(source="trip.number", read_only=True, default=None)

    class Meta:
        model = OrderService
        fields = [
            "id",
            "order",
            "order_number",
            "title",
            "category",
            "income",
            "expense",
            "date",
            "trip",
            "trip_number",
            "is_base",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_base", "created_at", "updated_at"]
        validators: list = []  # уникальность (заказ, рейс) проверяет БД; ответ - в create/update
        extra_kwargs = {
            "income": {"min_value": 0},
            "expense": {"min_value": 0},
            "category": {"required": False},
        }

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Название не может быть пустым")
        return value

    def validate(self, attrs):
        if self.instance is not None:
            if self.instance.is_base:
                raise serializers.ValidationError(BASE_LINE_MESSAGE)
            if "order" in attrs and attrs["order"].pk != self.instance.order_id:
                raise serializers.ValidationError(
                    {"order": "Строку нельзя перенести в другой заказ"}
                )
        trip = attrs.get("trip", getattr(self.instance, "trip", None))
        if trip is not None:
            order = attrs.get("order") or self.instance.order
            expense = attrs.get("expense", getattr(self.instance, "expense", 0))
            income = attrs.get("income", getattr(self.instance, "income", 0))
            if not TripConsignment.objects.filter(
                trip=trip, consignment__order=order
            ).exists():
                raise serializers.ValidationError({"trip": "Рейс не перевозит грузы этого заказа"})
            if income or not expense:
                raise serializers.ValidationError(
                    {"trip": "Строка рейса - это расход перевозчику: укажите расход, без дохода"}
                )
            attrs["category"] = CARRIER_CATEGORY
        return attrs

    def _guarded(self, action, *args):
        try:
            with transaction.atomic():  # точка сохранения: уникальность (заказ, рейс) в БД
                return action(*args)
        except IntegrityError:
            raise serializers.ValidationError(
                {"trip": "Расход по этому рейсу в заказе уже внесён"}, code="expense_exists"
            ) from None

    def create(self, validated_data):
        return self._guarded(super().create, validated_data)

    def update(self, instance, validated_data):
        return self._guarded(super().update, instance, validated_data)
