from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from apps.core.models import TenantModel, User

ACTION_CHOICES = [
    ("create", "Создание"),
    ("update", "Изменение"),
    ("delete", "Удаление"),
    ("restore", "Восстановление"),
    ("login", "Вход"),
]


class AuditLogImmutable(Exception):
    """Попытка изменить или удалить запись журнала аудита."""


class AuditLog(TenantModel):
    """Запись журнала аудита компании. Только добавление.

    Экземплярные save() существующей записи и delete() запрещены. Внимание: queryset-методы
    update()/delete() обходят эту защиту (Django выполняет их на уровне SQL), поэтому ни один
    API не должен выставлять их наружу; доступ клиентов - только чтение.
    """

    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=16, choices=ACTION_CHOICES)
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=64)
    object_repr = models.CharField(max_length=255, blank=True)
    changes = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["company", "created_at"], name="auditlog_company_created"),
            models.Index(
                fields=["company", "object_type", "object_id"], name="auditlog_company_object"
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AuditLogImmutable("Запись журнала аудита изменять нельзя")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AuditLogImmutable("Запись журнала аудита удалять нельзя")

    def __str__(self):
        return f"{self.action} {self.object_type}#{self.object_id}"
