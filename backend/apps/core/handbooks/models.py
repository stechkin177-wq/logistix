from django.db import models
from django.db.models import Q

from apps.core.managers import AllObjectsManager, TenantManager
from apps.core.models import TenantModel

from . import system_codes

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


class HandbookValueQuerySet(models.QuerySet):
    """Массовые delete/update не должны обходить защиту системных значений."""

    def _system_rows(self):
        cond = Q(pk__in=[])
        for handbook_code, codes in system_codes.SYSTEM_CODES.items():
            cond |= Q(handbook__code=handbook_code, code__in=codes)
        return self.filter(cond)

    def delete(self):
        if self._system_rows().exists():
            raise system_codes.SystemValueProtected(system_codes.MSG_DELETE)
        return super().delete()

    delete.alters_data = True
    delete.queryset_only = True

    def update(self, **kwargs):
        touched = set(kwargs) & {*system_codes.PROTECTED_FIELDS, "handbook", "handbook_id"}
        if touched and self._system_rows().exists():
            raise system_codes.SystemValueProtected(system_codes.MSG_CODE)
        new_code = kwargs.get("code")
        if new_code:
            for handbook_code, codes in system_codes.SYSTEM_CODES.items():
                if new_code in codes and (
                    self.filter(handbook__code=handbook_code).exclude(code=new_code).exists()
                ):
                    if not system_codes.assignment_allowed():
                        raise system_codes.SystemValueProtected(system_codes.MSG_RESERVED, "code")
        return super().update(**kwargs)

    update.alters_data = True
    update.queryset_only = True


class HandbookValueManager(TenantManager):
    queryset_class = HandbookValueQuerySet


class HandbookValueAllManager(AllObjectsManager):
    queryset_class = HandbookValueQuerySet


class HandbookValue(TenantModel):
    """Значение справочника. code - краткий код (валюта KZT, страна KZ), уникален в справочнике."""

    handbook = models.ForeignKey(Handbook, on_delete=models.PROTECT, related_name="values")
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=32, blank=True)
    order = models.PositiveIntegerField(default=0)
    is_initial = models.BooleanField(default=False)
    is_final = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    objects = HandbookValueManager()
    all_objects = HandbookValueAllManager()

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

    @property
    def is_system(self) -> bool:
        """Код значения входит в реестр системных кодов его справочника."""
        return system_codes.is_system_code(self.handbook.code, self.code)

    def delete(self, *args, **kwargs):
        if self.is_system:
            raise system_codes.SystemValueProtected(system_codes.MSG_DELETE)
        return super().delete(*args, **kwargs)

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        fields = None if update_fields is None else set(update_fields)
        guarded = {*system_codes.PROTECTED_FIELDS, "handbook"}
        if fields is None or fields & guarded:
            old = None
            if not self._state.adding:
                row = (
                    HandbookValue.all_objects.filter(pk=self.pk)
                    .values("code", "is_active", "is_final", "handbook__code")
                    .first()
                )
                if row is not None:
                    old = {
                        "code": row["code"],
                        "is_active": row["is_active"],
                        "is_final": row["is_final"],
                        "handbook_code": row["handbook__code"],
                    }
            system_codes.check_change(
                self.handbook.code,
                old=old,
                new={"code": self.code, "is_active": self.is_active, "is_final": self.is_final},
                fields=fields,
            )
        super().save(*args, **kwargs)
