from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import SectionPermissionMixin, permission_required
from apps.core.audit.mixins import AuditedMixin
from apps.core.handbooks.models import Handbook, HandbookValue
from apps.core.handbooks.system_codes import system_code_assignment
from apps.core.pagination import StandardPagination
from apps.forwarding.orders.filters import date_param, int_param
from apps.forwarding.orders.services import BASE_CURRENCY_CODE

from ..models import ExchangeRate
from ..nbrk import NBRK_CODES, fetch_rates
from .serializers import HandbookField, money


class RateSerializer(serializers.ModelSerializer):
    currency = HandbookField("currency")
    rate = serializers.DecimalField(max_digits=18, decimal_places=6, min_value=Decimal("0.000001"))

    class Meta:
        model = ExchangeRate
        fields = ["id", "currency", "date", "rate", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_currency(self, value):
        if value.code == BASE_CURRENCY_CODE:
            raise serializers.ValidationError("Для тенге курс всегда 1: запись не нужна")
        return value

    def validate(self, attrs):
        currency = attrs.get("currency") or (self.instance.currency if self.instance else None)
        day = attrs.get("date") or (self.instance.date if self.instance else None)
        clash = ExchangeRate.objects.filter(
            currency=currency, quote_currency__isnull=True, date=day
        )
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError({"date": "Курс на эту дату уже задан"})
        return attrs

    def to_representation(self, instance):
        return {
            "id": instance.pk,
            "currency": {
                "id": instance.currency_id,
                "code": instance.currency.code,
                "name": instance.currency.name,
            },
            "date": instance.date,
            "rate": money(instance.rate),
            "created_at": instance.created_at,
        }


class RateViewSet(AuditedMixin, SectionPermissionMixin, viewsets.ModelViewSet):
    """Курсы валют к тенге (ввод вручную)."""

    permission_section = "finance"
    serializer_class = RateSerializer
    pagination_class = StandardPagination

    def get_permissions(self):
        if getattr(self, "action", None) == "nbrk":
            return [ModuleRequired("finance")(), permission_required("finance.create")()]
        return [ModuleRequired("finance")(), *super().get_permissions()]

    @action(detail=False, methods=["post"], url_path="nbrk")
    def nbrk(self, request):
        """Курсы USD, EUR, RUB, CNY на сегодня у Нацбанка: запрос и сохранение (запись на дату)."""
        today = timezone.localdate()
        fetched = fetch_rates(today)
        with transaction.atomic():
            handbook = Handbook.objects.get(code="currency")
            saved = []
            for code in NBRK_CODES:
                if code not in fetched:
                    continue
                currency = HandbookValue.objects.filter(handbook=handbook, code=code).first()
                if (
                    currency is None
                ):  # юань мог появиться в справочнике позже, чем была создана компания
                    with system_code_assignment():
                        currency = HandbookValue.objects.create(
                            company_id=handbook.company_id,
                            handbook=handbook,
                            name={"CNY": "Китайский юань"}.get(code, code),
                            code=code,
                            order=handbook.values.count() + 1,
                        )
                row, _ = ExchangeRate.objects.update_or_create(
                    currency=currency,
                    quote_currency=None,
                    date=today,
                    defaults={"rate": fetched[code], "company_id": handbook.company_id},
                )
                saved.append(row)
        return Response(
            {
                "date": today,
                "source": "nationalbank.kz",
                "results": [RateSerializer(r).data for r in saved],
            }
        )

    def get_queryset(self):
        qs = ExchangeRate.objects.select_related("currency").filter(quote_currency__isnull=True)
        if self.action == "list":
            p = self.request.query_params
            if (cid := int_param(p, "currency")) is not None:
                qs = qs.filter(currency_id=cid)
            if (day := date_param(p, "date_from")) is not None:
                qs = qs.filter(date__gte=day)
            if (day := date_param(p, "date_to")) is not None:
                qs = qs.filter(date__lte=day)
        return qs.order_by("-date", "currency__code")
