from django.db import models

from apps.core.models import TenantModel

KIND_CHOICES = [
    ("order", "Заявка"),
    ("trip", "Рейс"),
    ("consolidated_trip", "Сборный рейс"),
    ("invoice_out", "Счёт клиенту"),
    ("invoice_in", "Счёт от перевозчика"),
    ("contract", "Договор"),
    ("act", "Акт"),
    ("carrier_order", "Заявка перевозчику"),
    ("cmr", "CMR"),
    ("letter", "Исходящее письмо"),
]


class NumberingRule(TenantModel):
    """Правило нумерации документов компании: по одному на вид (создаётся сидингом)."""

    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    template = models.CharField(max_length=100)
    digits = models.PositiveSmallIntegerField(default=5)
    next_value = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "kind"], name="numberingrule_company_kind_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(digits__lte=10), name="numberingrule_digits_lte_10"
            ),
            models.CheckConstraint(
                condition=models.Q(next_value__gte=1), name="numberingrule_next_value_gte_1"
            ),
        ]

    def __str__(self):
        return f"{self.kind}: {self.template}"
