from django.db import models, transaction
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


_ROW_FIELDS = ("code", "is_active", "is_final", "is_initial", "handbook_id", "handbook__code")


def _plain(row: dict) -> dict:
    """Строка values() -> словарь для check_change."""
    return {
        "code": row["code"],
        "is_active": row["is_active"],
        "is_final": row["is_final"],
        "is_initial": row["is_initial"],
        "handbook_id": row["handbook_id"],
        "handbook_code": row["handbook__code"],
    }


def db_rows(model, pks) -> dict[int, dict]:
    """Актуальные строки из БД (простой QuerySet без фильтров компании и без защиты)."""
    rows = model._base_manager.filter(pk__in=list(pks)).values("pk", *_ROW_FIELDS)
    return {r["pk"]: _plain(r) for r in rows}


def handbook_codes(ids) -> dict[int, str]:
    return dict(Handbook._base_manager.filter(pk__in=set(ids)).values_list("pk", "code"))


class HandbookValueQuerySet(models.QuerySet):
    """Массовые операции не обходят защиту системных значений.

    Защита сверяется со строками БД (до и после операции в одной транзакции), поэтому
    работает для update(), bulk_update() (он вызывает update()), выражений Case/F и
    устаревших экземпляров. Нарушение откатывает всю операцию.
    """

    def _system_rows(self):
        cond = Q(pk__in=[])
        for handbook_code, codes in system_codes.SYSTEM_CODES.items():
            cond |= Q(handbook__code=handbook_code, code__in=codes)
        return self.filter(cond)

    def delete(self):
        if not system_codes.maintenance_allowed() and self._system_rows().exists():
            raise system_codes.SystemValueProtected(system_codes.MSG_DELETE)
        return super().delete()

    delete.alters_data = True
    delete.queryset_only = True

    def update(self, **kwargs):
        if system_codes.maintenance_allowed() or not set(kwargs) & system_codes.GUARDED_FIELDS:
            return super().update(**kwargs)
        with transaction.atomic(using=self.db):
            pks = list(self.values_list("pk", flat=True))
            before = db_rows(self.model, pks)
            count = super().update(**kwargs)
            after = db_rows(self.model, pks)
            for pk, old in before.items():
                if pk in after:
                    system_codes.check_change(old, after[pk])
        return count

    update.alters_data = True
    update.queryset_only = True

    def bulk_create(
        self,
        objs,
        batch_size=None,
        ignore_conflicts=False,
        update_conflicts=False,
        update_fields=None,
        unique_fields=None,
    ):
        objs = list(objs)
        if not system_codes.maintenance_allowed():
            if update_conflicts:  # upsert мог бы перезаписать системное значение
                raise system_codes.SystemValueProtected(system_codes.MSG_UPSERT)
            codes = handbook_codes(o.handbook_id for o in objs)
            for obj in objs:
                system_codes.check_change(None, _object_state(obj, codes[obj.handbook_id]))
        return super().bulk_create(
            objs,
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts,
            update_conflicts=update_conflicts,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )

    bulk_create.alters_data = True
    bulk_create.queryset_only = True


def _object_state(obj, handbook_code: str) -> dict:
    return {
        "code": obj.code,
        "is_active": obj.is_active,
        "is_final": obj.is_final,
        "is_initial": obj.is_initial,
        "handbook_id": obj.handbook_id,
        "handbook_code": handbook_code,
    }


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
        """Код значения входит в реестр системных кодов его справочника (по состоянию объекта)."""
        return system_codes.is_system_code(self.handbook.code, self.code)

    def _db_row(self) -> dict | None:
        return db_rows(type(self), [self.pk]).get(self.pk) if self.pk is not None else None

    def delete(self, *args, **kwargs):
        # сверяемся со строкой в БД: объект в памяти мог устареть
        row = self._db_row()
        if (
            row is not None
            and not system_codes.maintenance_allowed()
            and system_codes.is_system_code(row["handbook_code"], row["code"])
        ):
            raise system_codes.SystemValueProtected(system_codes.MSG_DELETE)
        return super().delete(*args, **kwargs)

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        written = None if update_fields is None else set(update_fields)
        if not system_codes.maintenance_allowed() and (
            written is None or written & system_codes.GUARDED_FIELDS
        ):
            old = self._db_row()  # в том числе при _state.adding с существующим pk
            new = _object_state(self, "")
            if old is not None and written is not None:  # пишутся только перечисленные поля
                for field in ("code", "is_active", "is_final", "is_initial", "handbook_id"):
                    listed = field in written or (field == "handbook_id" and "handbook" in written)
                    if not listed:
                        new[field] = old[field]
            if old is not None and new["handbook_id"] == old["handbook_id"]:
                new["handbook_code"] = old["handbook_code"]
            else:
                new["handbook_code"] = handbook_codes([self.handbook_id])[self.handbook_id]
            system_codes.check_change(old, new)
        super().save(*args, **kwargs)
