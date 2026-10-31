"""Поля сериализаторов заказов и грузов: ссылки только на объекты текущей компании."""

from django.db.models import QuerySet
from rest_framework import serializers

from apps.core.handbooks.models import HandbookValue
from apps.core.models import User
from apps.core.tenancy import get_current_company_id


class _KeepCurrentMixin:
    """Текущее значение объекта при PATCH остаётся допустимым, даже если оно больше не
    проходит проверку (отключённое значение справочника, удалённый клиент)."""

    def _current_pk(self):
        instance = getattr(self.parent, "instance", None)
        if instance is None or isinstance(instance, (list, QuerySet)) or not self.source:
            return None
        return getattr(instance, f"{self.source}_id", None)


class ActiveHandbookField(_KeepCurrentMixin, serializers.PrimaryKeyRelatedField):
    """Активное значение справочника handbook_code текущей компании."""

    def __init__(self, handbook_code, **kwargs):
        self.handbook_code = handbook_code
        super().__init__(**kwargs)

    def get_queryset(self):
        return HandbookValue.objects.filter(handbook__code=self.handbook_code)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if not value.is_active and value.pk != self._current_pk():
            raise serializers.ValidationError("Значение справочника отключено")
        return value


class CurrentTolerantField(_KeepCurrentMixin, serializers.PrimaryKeyRelatedField):
    """Объект компании из queryset; неизменённая ссылка принимается, даже если объект уже
    не проходит queryset (клиент мягко удалён, участник отключён)."""

    def to_internal_value(self, data):
        try:
            return super().to_internal_value(data)
        except serializers.ValidationError:
            current = self._current_pk()
            if current is not None and str(data) == str(current):
                return getattr(self.parent.instance, self.source)
            raise


class CompanyUserField(CurrentTolerantField):
    """Активный участник текущей компании (активный пользователь с активным членством)."""

    def get_queryset(self):
        return User.objects.filter(
            is_active=True,
            memberships__company_id=get_current_company_id(),
            memberships__is_active=True,
        )
