from functools import lru_cache

from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.utils import timezone

from .tenancy import NoTenantContext, get_current_company_id


@lru_cache(maxsize=None)
def _has_concrete_field(model, name: str) -> bool:
    try:
        return bool(model._meta.get_field(name).concrete)
    except FieldDoesNotExist:
        return False


class SoftDeleteQuerySet(models.QuerySet):
    """delete() помечает записи удалёнными; hard_delete() удаляет по-настоящему.

    Внимание: каскад от родителя по FK ON DELETE CASCADE удаляет такие записи
    физически (коллектор Django его не перехватывает), поэтому внешние ключи на
    модели с мягким удалением должны использовать PROTECT, как TenantModel.company.
    """

    def delete(self):
        return self.update(deleted_at=timezone.now())

    delete.alters_data = True
    delete.queryset_only = True

    def hard_delete(self):
        return super().delete()

    hard_delete.alters_data = True
    hard_delete.queryset_only = True

    def restore(self):
        """Снимает пометку удаления у записей queryset; возвращает их число."""
        return self.update(deleted_at=None)

    restore.alters_data = True
    restore.queryset_only = True


class BaseManager(models.Manager):
    """Без фильтров; выбирает SoftDeleteQuerySet, если у модели есть deleted_at."""

    queryset_class = None  # свой QuerySet модели без мягкого удаления (например, HandbookValue)

    def get_queryset(self):
        if _has_concrete_field(self.model, "deleted_at"):
            return SoftDeleteQuerySet(self.model, using=self._db)
        return (self.queryset_class or models.QuerySet)(self.model, using=self._db)


class AllObjectsManager(BaseManager):
    pass


class ScopedManager(BaseManager):
    """Один менеджер для TenantModel, SoftDeleteModel и их комбинации.

    Фильтр по компании применяется, если у модели есть поле ``company``
    (без контекста компании — NoTenantContext); фильтр по удалению — если есть
    ``deleted_at``. Так ``class X(TenantModel, SoftDeleteModel)`` работает
    независимо от порядка баз.
    """

    def __init__(self, *, deleted: bool = False):
        super().__init__()
        self._deleted = deleted

    def get_queryset(self):
        qs = super().get_queryset()
        if _has_concrete_field(self.model, "company"):
            company_id = get_current_company_id()
            if company_id is None:
                raise NoTenantContext(f"Нет текущей компании для {self.model.__name__}")
            qs = qs.filter(company_id=company_id)
        if _has_concrete_field(self.model, "deleted_at"):
            qs = qs.filter(deleted_at__isnull=not self._deleted)
        return qs


class TenantManager(ScopedManager):
    """objects для TenantModel."""


class SoftDeleteManager(ScopedManager):
    """objects/trash для SoftDeleteModel."""
