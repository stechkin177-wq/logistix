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

    Один груз может ехать в нескольких рейсах (перегруз) и на нескольких участках одного рейса
    (см. TripConsignment).
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
    # назначение собственных техники и водителя (модули fleet и drivers); необязательно, свободные
    # поля vehicle_plate и driver_name ниже сохраняются для совместимости. Участки рейса
    # наследуют технику и водителя из рейса (индивидуальной подмены на участке нет).
    vehicle = models.ForeignKey(
        "fleet.Vehicle", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    trailer = models.ForeignKey(
        "fleet.Vehicle", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    driver = models.ForeignKey(
        "drivers.Driver", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    vehicle_plate = models.CharField(max_length=32, blank=True)
    driver_name = models.CharField(max_length=255, blank=True)
    # Стоимость перевозчика. Столбец БД остаётся `price` (переименование только в коде);
    # в API `price` - временный алиас этого поля.
    carrier_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        db_column="price",
    )
    currency = _handbook_fk("currency")
    status = _handbook_fk("trip_status")
    is_consolidated = models.BooleanField(default=False)
    # Время перехода в статус с системным кодом COMPLETED; ставит и обнуляет только сервис
    # change_trip_status (в API только чтение).
    completed_at = models.DateTimeField(null=True, blank=True, editable=False)
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
            models.Index(fields=["company", "completed_at"], name="trip_company_completed_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["company", "number"], name="trip_company_number_uniq"),
            models.CheckConstraint(condition=Q(carrier_price__gte=0), name="trip_price_gte_0"),
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
        from . import resources

        if self.status.code in resources.BUSY_CODES:  # рейс был в работе: ресурсы не заняты ли?
            try:
                resources.assert_free(self)
            except resources.ResourceBusy as exc:
                return str(exc.detail["detail"])
        from apps.finance import hooks  # engine=new: участки не должны конфликтовать с другими

        return hooks.trip_restore_blocker(self)

    def restore(self):
        super().restore()
        from apps.finance import hooks  # engine=new: пересчёт признания дохода заказов рейса

        from .services import refresh_tracking

        refresh_tracking(self.links.values_list("consignment_id", flat=True))
        hooks.after_trip_restored(self)


class TripConsignment(TenantModel):
    """Груз в рейсе = участок перевозки. Явная таблица связи: у неё есть company_id и RLS.

    Участок - часть маршрута груза от остановки ``from_stop`` до ``to_stop`` (``from_stop.seq <
    to_stop.seq``), которую выполняет рейс; перевозчик, водитель и техника берутся из рейса.
    Пустая пара (NULL, NULL) - прежняя запись «весь груз в рейсе» без привязки к остановкам.
    Доли ``weight_kg``/``volume_m3``/``pallets`` - сколько груза едет на участке (NULL - весь груз
    по этому измерению). Один груз может ехать в нескольких рейсах (передача между рейсами на
    разных участках) и в одном рейсе на нескольких участках; ``leg_seq`` - номер участка в паре
    (рейс, груз) по порядку маршрута. Статус участка следует за статусом рейса (сервис).
    """

    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"
    STATUSES = [
        (PLANNED, "Запланирован"),
        (IN_PROGRESS, "В пути"),
        (DONE, "Выполнен"),
        (CANCELLED, "Отменён"),
    ]

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="links")
    consignment = models.ForeignKey(
        "forwarding.Consignment", on_delete=models.PROTECT, related_name="trip_links"
    )
    from_stop = models.ForeignKey(
        "forwarding.ConsignmentPoint",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="legs_from",
    )
    to_stop = models.ForeignKey(
        "forwarding.ConsignmentPoint",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="legs_to",
    )
    leg_seq = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=12, choices=STATUSES, default=PLANNED)
    weight_kg = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    volume_m3 = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    pallets = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["consignment"], name="tripcons_consignment_idx")]
        constraints = [
            # NULL в PostgreSQL различны: для заполненных пар - обычная уникальность, для
            # прежних записей без остановок - частичная уникальность (рейс, груз)
            models.UniqueConstraint(
                fields=["trip", "consignment", "from_stop", "to_stop"],
                name="tripcons_trip_cons_leg_uniq",
            ),
            models.UniqueConstraint(
                fields=["trip", "consignment"],
                condition=Q(from_stop__isnull=True, to_stop__isnull=True),
                name="tripcons_trip_cons_whole_uniq",
            ),
            models.CheckConstraint(
                condition=(Q(from_stop__isnull=True) & Q(to_stop__isnull=True))
                | (Q(from_stop__isnull=False) & Q(to_stop__isnull=False)),
                name="tripcons_stops_both_or_none",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["planned", "in_progress", "done", "cancelled"]),
                name="tripcons_status_valid",
            ),
            models.CheckConstraint(
                condition=(Q(weight_kg__isnull=True) | Q(weight_kg__gte=0))
                & (Q(volume_m3__isnull=True) | Q(volume_m3__gte=0)),
                name="tripcons_share_gte_0",
            ),
        ]
