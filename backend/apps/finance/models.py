from django.db import models, transaction
from django.db.models import Q

from apps.core.models import SoftDeleteModel, TenantModel

from .errors import FinanceError


class ExchangeRate(TenantModel):
    """Курс валюты к тенге на дату (вводится вручную). Для KZT записи не создаются: курс 1."""

    currency = models.ForeignKey(
        "core.HandbookValue",
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Значение справочника currency",
    )
    date = models.DateField()
    rate = models.DecimalField(max_digits=18, decimal_places=6)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "currency", "date"], name="exchangerate_company_cur_date_uniq"
            ),
            models.CheckConstraint(condition=Q(rate__gt=0), name="exchangerate_rate_gt_0"),
        ]

    def __str__(self):
        return f"{self.currency_id} {self.date}: {self.rate}"


def _handbook_fk(code, **kwargs):
    return models.ForeignKey(
        "core.HandbookValue",
        on_delete=models.PROTECT,
        related_name="+",
        help_text=f"Значение справочника {code}",
        **kwargs,
    )


class Invoice(TenantModel, SoftDeleteModel):
    """Счёт: клиенту (out) или полученный от перевозчика (in).

    Суммы (total_*) и курс фиксируются при выставлении; пока счёт черновик, они нулевые.
    Просроченность и оплаченность - производные (см. invoices.display_status).
    """

    DIRECTIONS = [("out", "Клиенту"), ("in", "От перевозчика")]
    STATUSES = [("draft", "Черновик"), ("issued", "Выставлен"), ("cancelled", "Отменён")]

    direction = models.CharField(max_length=3, choices=DIRECTIONS)
    number = models.CharField(max_length=64, blank=True)
    external_number = models.CharField(max_length=128, blank=True)
    client = models.ForeignKey(
        "forwarding.Client", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    carrier = models.ForeignKey(
        "forwarding.Carrier", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    order = models.ForeignKey(
        "forwarding.Order", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    trip = models.ForeignKey(
        "forwarding.Trip", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    currency = _handbook_fk("currency")
    vat_rate = _handbook_fk("vat_rate")
    issue_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    rate_to_kzt = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="draft")
    total_net = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_vat = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_gross = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    comment = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["company", "direction", "status"], name="invoice_cmp_dir_st_idx"),
            models.Index(fields=["company", "due_date"], name="invoice_cmp_due_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "direction", "number"],
                condition=~Q(number=""),
                name="invoice_company_dir_number_uniq",
            ),
            models.CheckConstraint(
                condition=(Q(direction="out") & Q(client__isnull=False) & Q(carrier__isnull=True))
                | (Q(direction="in") & Q(carrier__isnull=False) & Q(client__isnull=True)),
                name="invoice_direction_party",
            ),
            models.CheckConstraint(
                condition=Q(total_net__gte=0) & Q(total_vat__gte=0) & Q(total_gross__gte=0),
                name="invoice_totals_gte_0",
            ),
        ]

    def __str__(self):
        return self.number or f"черновик #{self.pk}"


class InvoiceItem(TenantModel):
    """Позиция счёта: сумма без НДС и ссылка на строку заказа (доход для out, расход для in)."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="items")
    title = models.CharField(max_length=255)
    amount_net = models.DecimalField(max_digits=14, decimal_places=2)
    # null у отменённого счёта: строка освобождается (её можно удалить и выставить заново), а
    # название и сумма позиции остаются снимком для истории
    line = models.ForeignKey(
        "forwarding.OrderService",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="invoice_items",
    )
    trip = models.ForeignKey(
        "forwarding.Trip", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=Q(amount_net__gte=0), name="invoiceitem_amount_gte_0"),
        ]


class Payment(TenantModel, SoftDeleteModel):
    """Оплата по счёту (в валюте счёта); курс к тенге фиксируется на дату платежа."""

    METHODS = [("bank", "Банк"), ("cash", "Наличные"), ("other", "Прочее")]

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    rate_to_kzt = models.DecimalField(max_digits=18, decimal_places=6)
    method = models.CharField(max_length=10, choices=METHODS, default="bank")
    payment_ref = models.CharField(max_length=128, blank=True)
    comment = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "id"]
        indexes = [models.Index(fields=["invoice", "date"], name="payment_invoice_date_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_gt_0"),
        ]

    def restore_blocker(self) -> str | None:
        """Восстановить оплату нельзя, если счёт не выставлен или не хватает остатка."""
        invoice = Invoice.all_objects.filter(pk=self.invoice_id).first()
        if invoice is None or invoice.deleted_at is not None or invoice.status != "issued":
            return "Счёт оплаты отменён или удалён: восстановить оплату нельзя"
        paid = Payment.objects.filter(invoice=invoice).aggregate(t=models.Sum("amount"))["t"] or 0
        if self.amount > invoice.total_gross - paid:
            return "Сумма оплаты больше остатка по счёту: восстановить оплату нельзя"
        return None

    def restore(self):
        # счёт блокируется: восстановление не должно разойтись с параллельной оплатой
        with transaction.atomic():
            Invoice.all_objects.select_for_update().filter(pk=self.invoice_id).first()
            if (reason := self.restore_blocker()) is not None:
                raise FinanceError("payment_not_restorable", reason, status_code=409)
            super().restore()
