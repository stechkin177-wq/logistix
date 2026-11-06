import re

from django.db import IntegrityError, transaction
from django.db.models import Count, ProtectedError, Q
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import APIException

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import SectionPermissionMixin
from apps.core.audit.mixins import AuditedMixin
from apps.core.handbooks.models import HandbookValue
from apps.core.pagination import StandardPagination

from .filters import filter_parties
from .models import Carrier, Client, Contact, Order

BIN_RE = re.compile(r"[0-9]{10,12}")  # только ASCII: \d принимает и арабо-индийские цифры
DUPLICATE_BIN_MESSAGE = "Контрагент с таким БИН/ИИН уже есть"
CONTACT_FIELDS = ("name", "position", "phone", "email")


class ContactInUse(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Контакт используется в заказах и не может быть удалён"
    default_code = "contact_in_use"


class ContactSerializer(serializers.ModelSerializer):
    # id нужен только для сопоставления при замене списка; чужие/несуществующие id - 400
    id = serializers.IntegerField(required=False)

    class Meta:
        model = Contact
        fields = ["id", "name", "position", "phone", "email"]
        extra_kwargs = {"phone": {"required": False}, "email": {"required": False}}


class HandbookTypeField(serializers.PrimaryKeyRelatedField):
    """Значение справочника компании; код справочника задаёт type_handbook."""

    def __init__(self, handbook_code, **kwargs):
        self.handbook_code = handbook_code
        super().__init__(**kwargs)

    def get_queryset(self):  # менеджер компании вычисляется на запросе
        return HandbookValue.objects.filter(handbook__code=self.handbook_code)


class PartySerializer(serializers.ModelSerializer):
    """Общее для клиента и перевозчика. Подклассы задают Meta.model/fields, type и parent_field."""

    parent_field: str
    type_name = serializers.SerializerMethodField()
    contacts = ContactSerializer(many=True, required=False)

    def get_type_name(self, obj):
        return obj.type.name if obj.type_id else None

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Название не может быть пустым")
        return value

    def validate_bin_iin(self, value):
        value = value.strip()
        if not value:
            return ""
        if not BIN_RE.fullmatch(value):
            raise serializers.ValidationError("БИН/ИИН должен состоять из 10-12 цифр")
        dup = self.Meta.model.objects.filter(bin_iin=value)
        if self.instance is not None:
            dup = dup.exclude(pk=self.instance.pk)
        if dup.exists():
            raise serializers.ValidationError(DUPLICATE_BIN_MESSAGE)
        return value

    def validate_type(self, value):
        unchanged = self.instance is not None and value is not None
        unchanged = unchanged and self.instance.type_id == value.pk
        if value is not None and not value.is_active and not unchanged:
            raise serializers.ValidationError("Значение справочника отключено")
        return value

    def validate_contacts(self, items):
        ids = [item["id"] for item in items if "id" in item]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("Контакт указан дважды")
        if ids:
            existing = set()
            if self.instance is not None:
                existing = set(
                    Contact.objects.filter(**{self.parent_field: self.instance}).values_list(
                        "id", flat=True
                    )
                )
            if not set(ids) <= existing:
                raise serializers.ValidationError("Контакт не найден у этого контрагента")
        for item in items:
            if "id" not in item and not item.get("name", "").strip():
                raise serializers.ValidationError("Укажите имя контакта")
        return items

    def create(self, validated_data):
        contacts = validated_data.pop("contacts", [])
        with transaction.atomic():
            instance = self.Meta.model(**validated_data)
            instance.save()
            for item in contacts:
                Contact(**{self.parent_field: instance}, **item).save()
        instance._contacts_changed = bool(contacts)
        return instance

    def update(self, instance, validated_data):
        contacts = validated_data.pop("contacts", None)
        with transaction.atomic():
            instance = super().update(instance, validated_data)
            instance._contacts_changed = (
                self._replace_contacts(instance, contacts) if contacts is not None else False
            )
        return instance

    def _replace_contacts(self, instance, items) -> bool:
        """Список заменяет набор: по id обновляет, без id создаёт, отсутствующие удаляет."""
        current = {c.pk: c for c in Contact.objects.filter(**{self.parent_field: instance})}
        changed = False
        for item in items:
            contact = current.pop(item.get("id"), None)
            if contact is None:
                Contact(**{self.parent_field: instance}, **{k: v for k, v in item.items()}).save()
                changed = True
                continue
            before = [getattr(contact, f) for f in CONTACT_FIELDS]
            for field in CONTACT_FIELDS:
                if field in item:
                    setattr(contact, field, item[field])
            contact.normalize()
            if [getattr(contact, f) for f in CONTACT_FIELDS] != before:
                contact.save()
                changed = True
        if current:
            try:
                Contact.objects.filter(pk__in=list(current)).delete()
            except ProtectedError:  # контакт указан в заказе (в т.ч. удалённом): PATCH откатывается
                raise ContactInUse() from None
            changed = True
        return changed


class ClientSerializer(PartySerializer):
    parent_field = "client"
    type = HandbookTypeField("client_type", allow_null=True, required=False)
    orders_count = serializers.SerializerMethodField()

    def get_orders_count(self, obj):
        """Не удалённые заказы клиента: аннотация списка/деталей, иначе (после создания) запрос."""
        count = getattr(obj, "orders_count", None)
        return Order.objects.filter(client=obj).count() if count is None else count

    class Meta:
        model = Client
        fields = [
            "id",
            "name",
            "bin_iin",
            "type",
            "type_name",
            "status",
            "credit_limit",
            "orders_count",
            "notes",
            "address",
            "bank",
            "iban",
            "contacts",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
        extra_kwargs = {"credit_limit": {"min_value": 0}}


class CarrierSerializer(PartySerializer):
    parent_field = "carrier"
    type = HandbookTypeField("carrier_type", allow_null=True, required=False)

    class Meta:
        model = Carrier
        fields = [
            "id",
            "name",
            "bin_iin",
            "type",
            "type_name",
            "status",
            "rating",
            "notes",
            "address",
            "bank",
            "iban",
            "contacts",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
        extra_kwargs = {"rating": {"min_value": 0, "max_value": 5}}


class PartyViewSet(AuditedMixin, SectionPermissionMixin, viewsets.ModelViewSet):
    model: type
    ordering_fields: tuple
    pagination_class = StandardPagination

    def get_permissions(self):
        return [ModuleRequired("forwarding")(), *super().get_permissions()]

    def get_queryset(self):
        qs = self.model.objects.select_related("type").prefetch_related("contacts")
        if self.action == "list":
            qs = filter_parties(qs, self.request.query_params, self.ordering_fields)
        return qs

    def audit_extra_changes(self, instance):
        # состав контактов (телефоны, почты) в аудит не пишем - только факт изменения
        return {"contacts": "changed"} if getattr(instance, "_contacts_changed", False) else {}

    def _guarded(self, method, request, *args, **kwargs):
        """Гонка по уникальному БИН/ИИН: ответ БД превращается в 400, а не 500."""
        try:
            with transaction.atomic():
                return method(request, *args, **kwargs)
        except IntegrityError as exc:
            constraint = getattr(getattr(exc.__cause__, "diag", None), "constraint_name", "") or ""
            if not constraint.endswith("_bin_uniq"):
                raise
            raise serializers.ValidationError({"bin_iin": [DUPLICATE_BIN_MESSAGE]}) from None

    def create(self, request, *args, **kwargs):
        return self._guarded(super().create, request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        return self._guarded(super().update, request, *args, **kwargs)


class ClientViewSet(PartyViewSet):
    permission_section = "clients"
    serializer_class = ClientSerializer
    model = Client
    ordering_fields = ("name", "created_at")

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .annotate(orders_count=Count("orders", filter=Q(orders__deleted_at__isnull=True)))
        )


class CarrierViewSet(PartyViewSet):
    permission_section = "carriers"
    serializer_class = CarrierSerializer
    model = Carrier
    ordering_fields = ("name", "created_at", "rating")
