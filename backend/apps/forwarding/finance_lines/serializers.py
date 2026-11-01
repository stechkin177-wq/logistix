from rest_framework import serializers

from ..models import Order, OrderService

BASE_LINE_MESSAGE = "Начальная ставка ведётся автоматически: измените ставку клиента в заказе"


class LineOrderField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return Order.objects.all()  # заказы компании без удалённых


class OrderServiceSerializer(serializers.ModelSerializer):
    order = LineOrderField()
    order_number = serializers.CharField(source="order.number", read_only=True)

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
            "is_base",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_base", "created_at", "updated_at"]
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
        return attrs
