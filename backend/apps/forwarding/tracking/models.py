"""Передачи груза и журнал событий (этап 1.5-D).

``CargoTransfer`` - запись о передаче груза на остановке вида ``transfer``; после подтверждения
неизменяема (исправление - новая запись-сторно с ``reverses``), удаление запрещено.
``ConsignmentEvent`` - журнал событий груза, только добавление. Обе таблицы - tenant с RLS.
"""

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import TenantModel

MANUAL = "manual"
DRIVER_APP = "driver_app"
SOURCES = [(MANUAL, "Вручную"), (DRIVER_APP, "Приложение водителя")]


class ImmutableRecordError(ValidationError):
    pass


class CargoTransfer(TenantModel):
    TO_CARRIER = "to_carrier"
    BETWEEN_VEHICLES = "between_vehicles"
    TO_STORAGE = "to_storage"
    FROM_STORAGE = "from_storage"
    KINDS = [
        (TO_CARRIER, "Другому перевозчику"),
        (BETWEEN_VEHICLES, "Перегрузка между ТС"),
        (TO_STORAGE, "На склад"),
        (FROM_STORAGE, "Со склада"),
    ]
    INITIATED = "initiated"
    CONFIRMED = "confirmed"
    REVERSED = "reversed"  # запись-сторно (исправляет другую запись), не статус исходной
    STATUSES = [
        (INITIATED, "Инициирована"),
        (CONFIRMED, "Подтверждена"),
        (REVERSED, "Сторно"),
    ]

    consignment = models.ForeignKey(
        "forwarding.Consignment", on_delete=models.PROTECT, related_name="transfers"
    )
    from_trip = models.ForeignKey(
        "forwarding.Trip", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    to_trip = models.ForeignKey(
        "forwarding.Trip", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    from_stop = models.ForeignKey(
        "forwarding.ConsignmentPoint",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="transfers_from",
    )
    to_stop = models.ForeignKey(
        "forwarding.ConsignmentPoint", on_delete=models.PROTECT, related_name="transfers_to"
    )
    transfer_kind = models.CharField(max_length=16, choices=KINDS)
    from_carrier = models.ForeignKey(
        "forwarding.Carrier", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    to_carrier = models.ForeignKey(
        "forwarding.Carrier", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    carrier_changed = models.BooleanField(default=False)
    transferred_at = models.DateTimeField()
    weight_kg = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    volume_m3 = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    pallets = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=STATUSES, default=INITIATED)
    initiated_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    source = models.CharField(max_length=12, choices=SOURCES, default=MANUAL)
    confirmed_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    reverses = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversals"
    )
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-transferred_at", "-id"]
        indexes = [
            models.Index(fields=["company", "consignment"], name="transfer_company_cons_idx"),
            models.Index(fields=["company", "status"], name="transfer_company_status_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    transfer_kind__in=[
                        "to_carrier",
                        "between_vehicles",
                        "to_storage",
                        "from_storage",
                    ]
                ),
                name="transfer_kind_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["initiated", "confirmed", "reversed"]),
                name="transfer_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(source__in=["manual", "driver_app"]), name="transfer_source_valid"
            ),
            models.CheckConstraint(
                condition=(Q(weight_kg__isnull=True) | Q(weight_kg__gte=0))
                & (Q(volume_m3__isnull=True) | Q(volume_m3__gte=0)),
                name="transfer_share_gte_0",
            ),
            # к одной записи - не больше одного сторно
            models.UniqueConstraint(
                fields=["reverses"],
                condition=Q(reverses__isnull=False),
                name="transfer_one_reversal",
            ),
        ]

    def __str__(self):
        return f"transfer {self.pk} {self.transfer_kind}"

    def save(self, *args, **kwargs):
        """Неизменяема после подтверждения; правится только инициированная запись."""
        if not self._state.adding:
            stored = type(self).all_objects.filter(pk=self.pk).values("status").first()
            if stored is None or stored["status"] != self.INITIATED:
                raise ImmutableRecordError("Подтверждённая передача неизменяема: создайте сторно")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("Передачи груза не удаляются: используйте сторно")


class ConsignmentEvent(TenantModel):
    ARRIVED = "arrived"
    LOADED = "loaded"
    DEPARTED = "departed"
    TRANSFERRED = "transferred"
    UNLOADED = "unloaded"
    DELIVERED = "delivered"
    SKIPPED = "skipped"
    STORED = "stored"
    TYPES = [
        (ARRIVED, "Прибыл на остановку"),
        (LOADED, "Погружен"),
        (DEPARTED, "Отправлен с остановки"),
        (TRANSFERRED, "Передан"),
        (UNLOADED, "Выгружен"),
        (DELIVERED, "Доставлен"),
        (SKIPPED, "Остановка пропущена"),
        (STORED, "Помещён на хранение"),
    ]
    TYPE_CODES = [code for code, _ in TYPES]

    consignment = models.ForeignKey(
        "forwarding.Consignment", on_delete=models.PROTECT, related_name="events"
    )
    stop = models.ForeignKey(
        "forwarding.ConsignmentPoint",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="events",
    )
    leg = models.ForeignKey(
        "forwarding.TripConsignment",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
    )
    trip = models.ForeignKey(
        "forwarding.Trip", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    event_type = models.CharField(max_length=12, choices=TYPES)
    occurred_at = models.DateTimeField()
    recorded_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    source = models.CharField(max_length=12, choices=SOURCES, default=MANUAL)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["occurred_at", "id"]
        indexes = [
            models.Index(
                fields=["company", "consignment", "occurred_at"], name="event_company_cons_idx"
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    event_type__in=[
                        "arrived",
                        "loaded",
                        "departed",
                        "transferred",
                        "unloaded",
                        "delivered",
                        "skipped",
                        "stored",
                    ]
                ),
                name="event_type_valid",
            ),
            models.CheckConstraint(
                condition=Q(source__in=["manual", "driver_app"]), name="event_source_valid"
            ),
            # повтор того же события не дублируется (для событий с остановкой)
            models.UniqueConstraint(
                fields=["consignment", "stop", "event_type", "occurred_at"],
                name="event_idempotent_uniq",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError("Журнал событий только для добавления")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("События груза не удаляются")
