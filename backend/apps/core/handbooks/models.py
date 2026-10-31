from django.db import models
from django.db.models import Q

from apps.core.models import TenantModel

# Справочники статусов: у каждого ровно одно активное начальное значение
STATUS_HANDBOOK_CODES = frozenset({"order_status", "consignment_status", "trip_status"})


class Handbook(TenantModel):
    """Справочник компании. Набор фиксирован (создаётся сидингом), через API не создаётся."""

    code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    group = models.CharField(max_length=128, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="handbook_company_code_uniq"),
        ]

    def __str__(self):
        return self.name


class HandbookValue(TenantModel):
    """Значение справочника. code - краткий код (валюта KZT, страна KZ), уникален в справочнике."""

    handbook = models.ForeignKey(Handbook, on_delete=models.PROTECT, related_name="values")
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=32, blank=True)
    order = models.PositiveIntegerField(default=0)
    is_initial = models.BooleanField(default=False)
    is_final = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["handbook", "code"],
                condition=~Q(code=""),
                name="handbookvalue_handbook_code_uniq",
            ),
            models.UniqueConstraint(
                fields=["handbook"],
                condition=Q(is_initial=True),
                name="handbookvalue_one_initial_uniq",
            ),
        ]

    def __str__(self):
        return self.name
