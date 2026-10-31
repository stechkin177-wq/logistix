from copy import copy

from . import services


class AuditedMixin:
    """Миксин DRF-вьюсета: perform_create/update/destroy пишут create/update(diff)/delete.

    Ставится ПЕРЕД базовыми классами вьюсета. Дополнительные kwargs для save() при создании
    задаёт get_create_kwargs(); вьюсеты с собственным create()/destroy() вызывают
    audit_created()/audit_updated()/audit_deleted() явно.
    """

    def get_create_kwargs(self, serializer) -> dict:
        return {}

    def audit_extra_changes(self, instance) -> dict:
        """Дополнительные записи в changes (например, {"contacts": "changed"} для вложенных
        данных, значения которых в аудит не попадают). Пусто = нет."""
        return {}

    def audit_created(self, instance):
        changes = services.diff({}, services.snapshot(instance), services.masked_fields(instance))
        services.log(
            "create",
            instance,
            self.request.user,
            {**changes, **self.audit_extra_changes(instance)},
            ip=services.client_ip(self.request),
        )

    def audit_updated(self, before: dict, instance):
        changes = services.diff(
            before, services.snapshot(instance), services.masked_fields(instance)
        )
        changes.update(self.audit_extra_changes(instance))
        if not changes:  # пустая правка не пишется
            return
        services.log(
            "update", instance, self.request.user, changes, ip=services.client_ip(self.request)
        )

    def audit_deleted(self, copy_before_delete):
        """copy_before_delete - copy.copy(instance) до удаления (у оригинала pk обнуляется)."""
        services.log(
            "delete",
            copy_before_delete,
            self.request.user,
            services.diff(
                services.snapshot(copy_before_delete),
                {},
                services.masked_fields(copy_before_delete),
            ),
            ip=services.client_ip(self.request),
        )

    def perform_create(self, serializer):
        serializer.save(**self.get_create_kwargs(serializer))
        self.audit_created(serializer.instance)

    def perform_update(self, serializer):
        before = services.snapshot(serializer.instance)
        serializer.save()
        self.audit_updated(before, serializer.instance)

    def perform_destroy(self, instance):
        before = copy(instance)
        instance.delete()
        self.audit_deleted(before)
