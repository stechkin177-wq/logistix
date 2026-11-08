"""Автопарк (модуль fleet): техника, её документы и страховки.

Модуль независим от forwarding и drivers. Назначение техники на рейс - необязательная ссылка
``Trip.vehicle`` (подзадача 2.3); прежнее текстовое поле ``Trip.vehicle_plate`` сохраняется.
Деньги (стоимость обслуживания, страховые премии) в этой подзадаче не хранятся: затраты по
технике позже идут через Expense/ExpenseAllocation (G1), параллельной финансовой системы нет.
"""

from django.db import models
from django.db.models import Q

from apps.core.models import SoftDeleteModel, TenantModel


class Vehicle(TenantModel, SoftDeleteModel):
    TRACTOR = "tractor"
    TRAILER = "trailer"
    TRUCK = "truck"
    OTHER = "other"
    KINDS = [
        (TRACTOR, "Тягач"),
        (TRAILER, "Полуприцеп/прицеп"),
        (TRUCK, "Грузовик"),
        (OTHER, "Другое"),
    ]
    ACTIVE = "active"
    REPAIR = "repair"
    INACTIVE = "inactive"
    STATUSES = [(ACTIVE, "В работе"), (REPAIR, "В ремонте"), (INACTIVE, "Выведен")]

    audit_masked_fields = ("vin", "notes")

    kind = models.CharField(max_length=16, choices=KINDS, default=TRUCK)
    plate = models.CharField(max_length=32)
    vin = models.CharField(max_length=32, blank=True)
    make = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    body_type = models.CharField(max_length=64, blank=True)
    capacity_kg = models.PositiveIntegerField(null=True, blank=True)
    volume_m3 = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUSES, default=ACTIVE)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["company", "plate"], name="vehicle_company_plate_idx")]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "plate"],
                condition=Q(deleted_at__isnull=True),
                name="vehicle_company_plate_uniq",
            ),
            models.CheckConstraint(
                condition=Q(kind__in=["tractor", "trailer", "truck", "other"]),
                name="vehicle_kind_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["active", "repair", "inactive"]),
                name="vehicle_status_valid",
            ),
        ]

    def __str__(self):
        return self.plate


class _Dated(TenantModel):
    """Общее для документов и страховок техники: срок действия не раньше даты выдачи."""

    class Meta:
        abstract = True

    @staticmethod
    def dates_constraint(name):
        return models.CheckConstraint(
            condition=Q(starts_at__isnull=True)
            | Q(expires_at__isnull=True)
            | Q(expires_at__gte=models.F("starts_at")),
            name=name,
        )


class VehicleDocument(_Dated):
    REGISTRATION = "registration"
    INSPECTION = "inspection"
    PERMIT = "permit"
    OTHER = "other"
    KINDS = [
        (REGISTRATION, "Техпаспорт"),
        (INSPECTION, "Техосмотр"),
        (PERMIT, "Разрешение"),
        (OTHER, "Другое"),
    ]

    audit_masked_fields = ("number", "notes")

    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="documents")
    kind = models.CharField(max_length=16, choices=KINDS, default=OTHER)
    number = models.CharField(max_length=64, blank=True)
    starts_at = models.DateField(null=True, blank=True)
    expires_at = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["company", "vehicle"], name="vehdoc_company_vehicle_idx")]
        constraints = [
            _Dated.dates_constraint("vehdoc_expires_after_start"),
            models.CheckConstraint(
                condition=Q(kind__in=["registration", "inspection", "permit", "other"]),
                name="vehdoc_kind_valid",
            ),
        ]


class Insurance(_Dated):
    OSAGO = "osago"
    KASKO = "kasko"
    CARGO = "cargo"
    OTHER = "other"
    KINDS = [
        (OSAGO, "ОСАГО"),
        (KASKO, "КАСКО"),
        (CARGO, "Страхование груза"),
        (OTHER, "Другое"),
    ]

    audit_masked_fields = ("policy_number", "notes")

    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="insurances")
    kind = models.CharField(max_length=16, choices=KINDS, default=OSAGO)
    policy_number = models.CharField(max_length=64, blank=True)
    insurer = models.CharField(max_length=255, blank=True)
    starts_at = models.DateField(null=True, blank=True)
    expires_at = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["company", "vehicle"], name="insur_company_vehicle_idx")]
        constraints = [
            _Dated.dates_constraint("insur_expires_after_start"),
            models.CheckConstraint(
                condition=Q(kind__in=["osago", "kasko", "cargo", "other"]),
                name="insur_kind_valid",
            ),
        ]
