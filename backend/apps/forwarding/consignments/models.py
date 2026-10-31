from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import SoftDeleteModel, TenantModel


class Consignment(TenantModel, SoftDeleteModel):
    """Груз заказа. Скрыт, пока удалён его заказ; восстановить груз удалённого заказа нельзя."""

    order = models.ForeignKey(
        "forwarding.Order", on_delete=models.PROTECT, related_name="consignments"
    )
    name = models.CharField(max_length=255)
    weight_kg = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)]
    )
    volume_m3 = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)]
    )
    pallets = models.PositiveIntegerField(default=0)
    packaging = models.ForeignKey(
        "core.HandbookValue",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Значение справочника packaging",
    )
    status = models.ForeignKey(
        "core.HandbookValue",
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Значение справочника consignment_status",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["company", "order"], name="consignment_company_order_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(weight_kg__gte=0), name="consignment_weight_gte_0"),
            models.CheckConstraint(condition=Q(volume_m3__gte=0), name="consignment_volume_gte_0"),
        ]

    def __str__(self):
        return self.name

    def restore_blocker(self) -> str | None:
        """Причина, по которой груз нельзя восстановить из корзины (None - можно)."""
        from .. import models as forwarding_models

        if forwarding_models.Order.trash.filter(pk=self.order_id).exists():
            return "Нельзя восстановить груз: его заказ удалён. Сначала восстановите заказ"
        return None


class ConsignmentPoint(TenantModel):
    """Точка погрузки или выгрузки груза: не более одной каждого вида."""

    LOAD = "load"
    UNLOAD = "unload"
    KINDS = [(LOAD, "Погрузка"), (UNLOAD, "Выгрузка")]

    consignment = models.ForeignKey(Consignment, on_delete=models.CASCADE, related_name="points")
    kind = models.CharField(max_length=8, choices=KINDS)
    window_from = models.DateTimeField()
    window_to = models.DateTimeField(null=True, blank=True)
    country = models.ForeignKey(
        "core.HandbookValue",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Значение справочника country",
    )
    city = models.CharField(max_length=255, blank=True)
    street = models.CharField(max_length=255, blank=True)
    method = models.ForeignKey(
        "core.HandbookValue",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Значение справочника loading_method",
    )
    contact = models.CharField(max_length=255, blank=True)
    postal_code = models.CharField(max_length=16, blank=True)
    lat = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    lng = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["kind"]  # load, затем unload
        constraints = [
            models.UniqueConstraint(
                fields=["consignment", "kind"], name="point_consignment_kind_uniq"
            ),
            models.CheckConstraint(
                condition=Q(kind__in=["load", "unload"]), name="point_kind_valid"
            ),
            models.CheckConstraint(
                condition=Q(window_to__isnull=True) | Q(window_to__gte=models.F("window_from")),
                name="point_window_order",
            ),
            models.CheckConstraint(
                condition=Q(lat__isnull=True) | (Q(lat__gte=-90) & Q(lat__lte=90)),
                name="point_lat_range",
            ),
            models.CheckConstraint(
                condition=Q(lng__isnull=True) | (Q(lng__gte=-180) & Q(lng__lte=180)),
                name="point_lng_range",
            ),
        ]
