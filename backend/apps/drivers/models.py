"""Водители (модуль drivers): карточка водителя и его документы.

Модуль независим от forwarding и fleet. Назначение водителя на рейс - необязательная ссылка
``Trip.driver`` (подзадача 2.3); прежнее текстовое поле ``Trip.driver_name`` сохраняется.
"""

from django.db import models
from django.db.models import Q

from apps.core.models import SoftDeleteModel, TenantModel


class Driver(TenantModel, SoftDeleteModel):
    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    INACTIVE = "inactive"
    STATUSES = [(ACTIVE, "Работает"), (ON_LEAVE, "В отпуске"), (INACTIVE, "Не работает")]

    # ИИН, телефон, номер удостоверения и заметки - персональные данные: значения в аудит не пишутся
    audit_masked_fields = ("iin", "phone", "license_number", "notes")

    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=32, blank=True)
    iin = models.CharField(max_length=12, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    license_number = models.CharField(max_length=64, blank=True)
    license_categories = models.CharField(max_length=32, blank=True)
    license_expires = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUSES, default=ACTIVE)
    # пользователь системы (для мобильной версии водителя); необязателен
    user = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["company", "full_name"], name="driver_company_name_idx")]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "iin"],
                condition=Q(deleted_at__isnull=True) & ~Q(iin=""),
                name="driver_company_iin_uniq",
            ),
        ]

    def __str__(self):
        return self.full_name


class DriverDocument(TenantModel):
    """Документ водителя (удостоверение, медсправка и т.д.). Следует за водителем."""

    LICENSE = "license"
    PASSPORT = "passport"
    MEDICAL = "medical"
    OTHER = "other"
    KINDS = [
        (LICENSE, "Водительское удостоверение"),
        (PASSPORT, "Удостоверение личности"),
        (MEDICAL, "Медицинская справка"),
        (OTHER, "Другое"),
    ]

    audit_masked_fields = ("number", "notes")

    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name="documents")
    kind = models.CharField(max_length=16, choices=KINDS, default=OTHER)
    number = models.CharField(max_length=64, blank=True)
    issued_at = models.DateField(null=True, blank=True)
    expires_at = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["company", "driver"], name="driverdoc_company_driver_idx")]
        constraints = [
            models.CheckConstraint(
                condition=Q(issued_at__isnull=True)
                | Q(expires_at__isnull=True)
                | Q(expires_at__gte=models.F("issued_at")),
                name="driverdoc_expires_after_issued",
            ),
            models.CheckConstraint(
                condition=Q(kind__in=["license", "passport", "medical", "other"]),
                name="driverdoc_kind_valid",
            ),
        ]
