from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import TenantModel
from apps.core.tenancy import get_current_company_id

DEFAULT_TIMEZONE = "Asia/Almaty"


def company_zone(company_id) -> ZoneInfo:
    """Часовой пояс компании (при сбое поля - Asia/Almaty)."""
    from apps.core.models import Company

    name = (
        Company.objects.filter(pk=company_id).values_list("timezone", flat=True).first()
        if company_id is not None
        else None
    )
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def company_today(company_id=None) -> date:
    """Сегодняшняя дата в часовом поясе компании (по умолчанию - текущей компании)."""
    if company_id is None:
        company_id = get_current_company_id()
    return timezone.now().astimezone(company_zone(company_id)).date()


class OrderService(TenantModel):
    """Строка заказа с доходом и расходом (услуга, расход перевозчика, начальная ставка).

    Прибыль заказа - сумма доходов минус сумма расходов по его строкам. Удаляется жёстко;
    строки мягко удалённого заказа остаются в БД (и возвращаются вместе с заказом). Категория -
    свободный текст до появления финансовых справочников (этап 3). Строка is_base - системная
    «Начальная ставка» (income = Order.client_rate): не более одной на заказ, ведётся сервисом.
    """

    order = models.ForeignKey("forwarding.Order", on_delete=models.PROTECT, related_name="lines")
    title = models.CharField(max_length=255)
    category = models.CharField(max_length=255, blank=True)
    income = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    expense = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    date = models.DateField(default=company_today)
    is_base = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "id"]
        indexes = [
            models.Index(fields=["order", "date"], name="orderservice_order_date_idx"),
            models.Index(fields=["company", "date"], name="orderservice_company_date_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(income__gte=0), name="orderservice_income_gte_0"),
            models.CheckConstraint(condition=Q(expense__gte=0), name="orderservice_expense_gte_0"),
            models.UniqueConstraint(
                fields=["order"], condition=Q(is_base=True), name="orderservice_one_base_uniq"
            ),
        ]

    def __str__(self):
        return self.title
