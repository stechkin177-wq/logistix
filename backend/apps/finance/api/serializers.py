from decimal import Decimal

from rest_framework import serializers

from apps.core.handbooks.models import HandbookValue
from apps.forwarding.finance_lines.models import OrderService
from apps.forwarding.models import Carrier, Client, Trip
from apps.forwarding.orders.models import Order

from .. import invoices as svc
from ..models import Invoice, Payment
from ..payments import payment_fx_difference


def _empty(model):
    """Пустой queryset без контекста компании: настоящий строится лениво в get_queryset."""
    return model._base_manager.none()


class HandbookField(serializers.PrimaryKeyRelatedField):
    """Значение справочника компании заданного кода (активное)."""

    def __init__(self, code, **kwargs):
        self.code = code
        super().__init__(queryset=_empty(HandbookValue), **kwargs)

    def get_queryset(self):
        return HandbookValue.objects.filter(handbook__code=self.code, is_active=True)


class TenantRefField(serializers.PrimaryKeyRelatedField):
    """Ссылка на запись компании: queryset строится лениво, внутри контекста компании."""

    def __init__(self, model, **kwargs):
        self.model = model
        super().__init__(queryset=_empty(model), **kwargs)

    def get_queryset(self):
        return self.model.objects.all()


class ItemSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    amount_net = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0)
    line = TenantRefField(OrderService)

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Название не может быть пустым")
        return value


class InvoiceWriteSerializer(serializers.Serializer):
    direction = serializers.ChoiceField(choices=["out", "in"], required=False)
    party = serializers.IntegerField(required=False)
    order = TenantRefField(Order, required=False, allow_null=True)
    trip = TenantRefField(Trip, required=False, allow_null=True)
    currency = HandbookField("currency", required=False)
    vat_rate = HandbookField("vat_rate", required=False)
    due_date = serializers.DateField(required=False, allow_null=True)
    external_number = serializers.CharField(max_length=128, required=False, allow_blank=True)
    comment = serializers.CharField(required=False, allow_blank=True)
    items = ItemSerializer(many=True, required=False)

    def validate(self, attrs):
        creating = self.instance is None
        if creating:
            missing = [f for f in ("direction", "party", "currency", "vat_rate") if f not in attrs]
            if missing:
                raise serializers.ValidationError({f: "Обязательное поле" for f in missing})
        direction = attrs.get("direction") or (self.instance.direction if self.instance else None)
        if (
            self.instance is not None
            and attrs.get("direction", direction) != self.instance.direction
        ):
            raise serializers.ValidationError({"direction": "Направление счёта изменить нельзя"})
        if "party" in attrs:
            model = Client if direction == "out" else Carrier
            party = model.objects.filter(pk=attrs["party"]).first()
            if party is None:
                raise serializers.ValidationError({"party": "Контрагент не найден"})
            attrs["party"] = party
        return attrs


class PaymentWriteSerializer(serializers.Serializer):
    date = serializers.DateField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    method = serializers.ChoiceField(choices=[m for m, _ in Payment.METHODS], default="bank")
    payment_ref = serializers.CharField(max_length=128, required=False, allow_blank=True)
    comment = serializers.CharField(required=False, allow_blank=True)


def _ref(obj, *attrs):
    return None if obj is None else {"id": obj.pk, **{a: getattr(obj, a) for a in attrs}}


def money(value):
    return format(value, "f")


def invoice_data(invoice: Invoice, today) -> dict:
    """Представление счёта; invoice должен быть выбран через view.get_queryset (paid, связи)."""
    paid = invoice.paid
    return {
        "id": invoice.pk,
        "direction": invoice.direction,
        "number": invoice.number,
        "external_number": invoice.external_number,
        "status": invoice.status,
        "display_status": svc.display_status(invoice, today, paid=paid),
        "client": _ref(invoice.client, "name"),
        "carrier": _ref(invoice.carrier, "name"),
        "order": _ref(invoice.order, "number"),
        "trip": _ref(invoice.trip, "number"),
        "currency": _ref(invoice.currency, "code", "name"),
        "vat_rate": _ref(invoice.vat_rate, "code", "name"),
        "issue_date": invoice.issue_date,
        "due_date": invoice.due_date,
        "rate_to_kzt": None if invoice.rate_to_kzt is None else money(invoice.rate_to_kzt),
        "totals": {
            "net": money(invoice.total_net),
            "vat": money(invoice.total_vat),
            "gross": money(invoice.total_gross),
        },
        "paid": money(paid),
        "balance": money(invoice.total_gross - paid),
        "comment": invoice.comment,
        "items": [
            {"id": i.pk, "title": i.title, "amount_net": money(i.amount_net), "line": i.line_id}
            for i in invoice.items.all()
        ],
        "created_at": invoice.created_at,
    }


def payment_data(payment: Payment) -> dict:
    invoice = payment.invoice
    return {
        "id": payment.pk,
        "invoice": {"id": invoice.pk, "number": invoice.number, "direction": invoice.direction},
        "date": payment.date,
        "amount": money(payment.amount),
        "rate_to_kzt": money(payment.rate_to_kzt),
        "method": payment.method,
        "payment_ref": payment.payment_ref,
        "comment": payment.comment,
        "fx_difference_kzt": money(payment_fx_difference(payment)),
        "created_at": payment.created_at,
    }
