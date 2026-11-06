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


class Trip(TenantModel, SoftDeleteModel):
    """Рейс: перевозка одного или нескольких грузов (сборный рейс - грузы разных заказов).

    Номер выдаёт сервис (create_trip) и после этого НЕ меняется, в том числе при перераспределении
    грузов (reassign); уникален в компании среди ВСЕХ строк, включая мягко удалённые.

    vehicle_plate и driver_name - ВРЕМЕННЫЕ свободные поля: на этапе 4 (собственный автопарк)
    их заменят ссылки на транспорт и водителя. Имя водителя - персональные данные, в аудит не
    пишется (audit_masked_fields); госномер - пишется.

    Один груз может ехать в нескольких рейсах (перегруз): уникальна только пара (рейс, груз).
    """

    audit_masked_fields = ("driver_name",)

    number = models.CharField(max_length=64)
    carrier = models.ForeignKey(
        "forwarding.Carrier",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="trips",
    )
    vehicle_plate = models.CharField(max_length=32, blank=True)
    driver_name = models.CharField(max_length=255, blank=True)
    price = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    currency = _handbook_fk("currency")
    status = _handbook_fk("trip_status")
    is_consolidated = models.BooleanField(default=False)
    consignments = models.ManyToManyField(
        "forwarding.Consignment", through="forwarding.TripConsignment", related_name="trips"
    )
    created_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["company", "-created_at"], name="trip_company_created_idx"),
            models.Index(fields=["company", "status"], name="trip_company_status_idx"),
            models.Index(fields=["company", "carrier"], name="trip_company_carrier_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["company", "number"], name="trip_company_number_uniq"),
            models.CheckConstraint(condition=Q(price__gte=0), name="trip_price_gte_0"),
        ]

    def __str__(self):
        return self.number

    def restore_blocker(self) -> str | None:
        """Рейс без единого действующего груза (груз и его заказ не удалены) не восстановить."""
        from .. import models as forwarding_models

        alive = forwarding_models.Consignment.objects.filter(
            trip_links__trip_id=self.pk, order__deleted_at__isnull=True
        )
        if not alive.exists():
            return "Нельзя восстановить рейс: все его грузы удалены. Сначала восстановите груз"
        return None


class TripConsignment(TenantModel):
    """Груз в рейсе. Явная таблица связи: у неё есть company_id и RLS, как у остальных."""

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="links")
    consignment = models.ForeignKey(
        "forwarding.Consignment", on_delete=models.PROTECT, related_name="trip_links"
    )

    class Meta:
        indexes = [models.Index(fields=["consignment"], name="tripcons_consignment_idx")]
        constraints = [
            models.UniqueConstraint(fields=["trip", "consignment"], name="tripcons_trip_cons_uniq")
        ]
