from collections.abc import Mapping

from django.db import transaction
from django.db.models import Prefetch
from rest_framework import serializers

from apps.core.audit.services import client_ip
from apps.core.handbooks.models import HandbookValue
from apps.core.models import LegalEntity

from ..consignments.models import Consignment, ConsignmentPoint
from ..consignments.serializers import NestedConsignmentSerializer
from ..consignments.services import first_load, last_unload
from ..fields import ActiveHandbookField, CompanyUserField, CurrentTolerantField
from ..finance_lines.services import attach_totals, forget_totals, sync_base_line
from ..models import Client, Contact, Order, OrderStatusHistory, TripConsignment
from .services import carried_with_carrier, change_status, create_order

FORBIDDEN_FIELDS = {
    "number": "Номер выдаётся автоматически",
    "status": "Статус меняется действием POST /api/orders/{id}/status/",
    "completed_at": "Дата завершения ставится при переводе в статус «Завершён»",
}


def consignments_prefetch() -> Prefetch:
    """Грузы заказа (без удалённых) по id, сразу с точками и справочниками: без N+1."""
    points = Prefetch(
        "points", queryset=ConsignmentPoint.objects.select_related("country", "method")
    )
    links = Prefetch(
        "trip_links",
        queryset=TripConsignment.objects.select_related("trip", "from_stop", "to_stop").order_by(
            "leg_seq", "id"
        ),
    )
    return Prefetch(
        "consignments",
        queryset=Consignment.objects.select_related("status", "packaging")
        .prefetch_related(points, links)
        .order_by("id"),
    )


def order_route(order) -> str:
    """«Город первой погрузки → Город последней выгрузки» первого (по id) груза, у которого
    есть обе остановки (промежуточные в строке не показываются).

    Грузы и точки должны быть предзагружены (prefetch_related), иначе по запросу на заказ."""
    for consignment in order.consignments.all():
        stops = sorted(consignment.points.all(), key=lambda p: (p.seq, p.pk))
        load, unload = first_load(stops), last_unload(stops)
        if load is not None and unload is not None:
            return f"{load.city} → {unload.city}"
    return ""


class ClientField(CurrentTolerantField):
    def get_queryset(self):
        return Client.objects.all()  # клиенты компании без удалённых


class ContactField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return Contact.objects.filter(client__isnull=False)


class LegalEntityField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return LegalEntity.objects.all()


class HistorySerializer(serializers.ModelSerializer):
    from_status_name = serializers.SerializerMethodField()
    to_status_name = serializers.CharField(source="to_status.name", read_only=True)

    class Meta:
        model = OrderStatusHistory
        fields = [
            "id",
            "from_status",
            "from_status_name",
            "to_status",
            "to_status_name",
            "user",
            "created_at",
        ]

    def get_from_status_name(self, obj):
        return obj.from_status.name if obj.from_status_id else None


class OrderSerializer(serializers.ModelSerializer):
    client = ClientField()
    contact = ContactField(allow_null=True, required=False)
    manager = CompanyUserField(required=False)
    forwarder = CompanyUserField(allow_null=True, required=False)
    extra_managers = CompanyUserField(many=True, required=False)
    legal_entity = LegalEntityField(required=False)
    currency = ActiveHandbookField("currency", required=False)
    transport_condition = ActiveHandbookField(
        "transport_condition", allow_null=True, required=False
    )
    payment_delay_condition = ActiveHandbookField(
        "payment_delay_condition", allow_null=True, required=False
    )
    consignments = NestedConsignmentSerializer(many=True, required=False)
    client_name = serializers.CharField(source="client.name", read_only=True)
    status_name = serializers.CharField(source="status.name", read_only=True)
    manager_name = serializers.SerializerMethodField()
    route = serializers.SerializerMethodField()
    has_carrier = serializers.SerializerMethodField()
    revenue = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True, allow_null=True
    )
    cost = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True, allow_null=True
    )
    profit = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True, allow_null=True
    )
    margin_pct = serializers.DecimalField(
        max_digits=20, decimal_places=2, read_only=True, allow_null=True
    )
    history = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "number",
            "client",
            "client_name",
            "client_ref",
            "contract_number",
            "contact",
            "manager",
            "manager_name",
            "forwarder",
            "extra_managers",
            "legal_entity",
            "client_rate",
            "currency",
            "transport_condition",
            "delivery_days",
            "payment_delay_days",
            "payment_delay_condition",
            "comment",
            "status",
            "status_name",
            "completed_at",
            "route",
            "has_carrier",
            "revenue",
            "cost",
            "profit",
            "margin_pct",
            "consignments",
            "history",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "number",
            "status",
            "completed_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {"client_rate": {"min_value": 0}}

    def get_manager_name(self, obj):
        return obj.manager.full_name or str(obj.manager)

    def get_route(self, obj):
        return order_route(obj)

    def get_has_carrier(self, obj):
        """Аннотация списка/деталей; у только что созданного заказа - запрос."""
        value = getattr(obj, "has_carrier", None)
        if value is None:
            value = carried_with_carrier(obj.pk).exists()
        return value

    def get_history(self, obj):
        return HistorySerializer(obj.history.all(), many=True).data

    def to_representation(self, instance):
        data_with_finance = self.context.get("with_finance", False)
        if data_with_finance:
            attach_totals(instance)  # аннотация списка/деталей; у только что созданного - запрос
        data = super().to_representation(instance)
        if not data_with_finance:  # ключи остаются, значения скрыты (как в сводке дашборда)
            for key in ("revenue", "cost", "profit", "margin_pct"):
                data[key] = None
        return data

    def get_fields(self):
        fields = super().get_fields()
        if not self.context.get("with_history"):  # история - только в карточке заказа
            fields.pop("history")
        return fields

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            errors = {name: [text] for name, text in FORBIDDEN_FIELDS.items() if name in data}
            if self.instance is not None and "consignments" in data:
                errors["consignments"] = [
                    "Грузы меняются через /api/consignments/, а не через заказ"
                ]
            if errors:
                raise serializers.ValidationError(errors)
        return super().to_internal_value(data)

    def validate(self, attrs):
        client = attrs.get("client") or (self.instance.client if self.instance else None)
        contact = (
            attrs["contact"] if "contact" in attrs else getattr(self.instance, "contact", None)
        )
        if contact is not None and client is not None and contact.client_id != client.pk:
            raise serializers.ValidationError({"contact": "Контакт принадлежит другому клиенту"})
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        return create_order(validated_data, request.user, ip=client_ip(request))

    def update(self, instance, validated_data):
        extra = validated_data.pop("extra_managers", None)
        instance._extra_managers_diff = None
        with transaction.atomic():
            instance = super().update(instance, validated_data)
            if "client_rate" in validated_data:
                sync_base_line(instance)
                forget_totals(instance)
                from apps.finance import hooks  # только engine=new

                hooks.after_order_saved(instance, self.context["request"].user)
        if extra is not None:
            old = sorted(instance.extra_managers.values_list("pk", flat=True))
            new = sorted(u.pk for u in extra)
            if old != new:
                instance.extra_managers.set(extra)
                instance._extra_managers_diff = [old, new]
        return instance


class OrderStatusField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return HandbookValue.objects.filter(handbook__code="order_status").select_related(
            "handbook"
        )


class StatusChangeSerializer(serializers.Serializer):
    status = OrderStatusField()

    def save(self, order, user, ip=None):
        return change_status(order, self.validated_data["status"], user, ip=ip)
