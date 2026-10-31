from django.db import models

from .tenancy import NoTenantContext, get_current_company_id


class ScopedManager(models.Manager):
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
        field_names = {f.name for f in self.model._meta.get_fields()}
        if "company" in field_names:
            company_id = get_current_company_id()
            if company_id is None:
                raise NoTenantContext(f"Нет текущей компании для {self.model.__name__}")
            qs = qs.filter(company_id=company_id)
        if "deleted_at" in field_names:
            qs = qs.filter(deleted_at__isnull=not self._deleted)
        return qs


class TenantManager(ScopedManager):
    pass


class SoftDeleteManager(ScopedManager):
    pass
