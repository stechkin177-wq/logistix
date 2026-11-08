from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import SoftDeleteModel, TenantModel


def _handbook_fk(code, **kwargs):
    return models.ForeignKey(
        "core.HandbookValue",
        on_delete=models.PROTECT,
        related_name="+",
        help_text=f"Значение справочника {code}",
        **kwargs,
    )


class Order(TenantModel, SoftDeleteModel):
    """Заказ клиента. Номер выдаёт сервис (next_number) и клиентом не задаётся; уникален в
    компании среди ВСЕХ строк, включая мягко удалённые (номера не переиспользуются)."""

    number = models.CharField(max_length=64)
    client = models.ForeignKey("forwarding.Client", on_delete=models.PROTECT, related_name="orders")
    client_ref = models.CharField(max_length=255, blank=True)
    contract_number = models.CharField(max_length=255, blank=True)
    contact = models.ForeignKey(
        "forwarding.Contact",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Контакт именно этого клиента",
    )
    manager = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    forwarder = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    extra_managers = models.ManyToManyField("core.User", blank=True, related_name="+")
    legal_entity = models.ForeignKey("core.LegalEntity", on_delete=models.PROTECT, related_name="+")
    client_rate = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    currency = _handbook_fk("currency")
    transport_condition = _handbook_fk("transport_condition", null=True, blank=True)
    delivery_days = models.PositiveIntegerField(null=True, blank=True)
    payment_delay_days = models.PositiveIntegerField(null=True, blank=True)
    payment_delay_condition = _handbook_fk("payment_delay_condition", null=True, blank=True)
    comment = models.TextField(blank=True)
    status = _handbook_fk("order_status")
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["company", "-created_at"], name="order_company_created_idx"),
            models.Index(fields=["company", "client"], name="order_company_client_idx"),
            models.Index(fields=["company", "status"], name="order_company_status_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["company", "number"], name="order_company_number_uniq"),
            models.CheckConstraint(condition=Q(client_rate__gte=0), name="order_rate_gte_0"),
        ]

    def restore(self):
        super().restore()
        from apps.finance import hooks  # engine=new: плановый доход перевозки создаётся заново

        hooks.after_order_restored(self)

    def __str__(self):
        return self.number


class OrderStatusHistory(TenantModel):
    """Смены статуса заказа; первая строка - начальный статус (from_status пуст)."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="history")
    from_status = _handbook_fk("order_status", null=True, blank=True)
    to_status = _handbook_fk("order_status")
    user = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["order", "id"], name="orderhistory_order_idx")]
