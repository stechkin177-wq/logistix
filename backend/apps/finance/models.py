from django.db import models
from django.db.models import Q

from apps.core.models import TenantModel


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
