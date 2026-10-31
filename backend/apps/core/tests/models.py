"""Тестовые конкретные модели. Приложение подключено только в config/settings_test.py;
таблицы создаёт ручная миграция apps/core/tests/migrations."""

from django.db import models

from apps.core.models import SoftDeleteModel, TenantModel


class PlainTenant(TenantModel):
    name = models.CharField(max_length=50)


class SoftTenant(TenantModel, SoftDeleteModel):
    name = models.CharField(max_length=50)


class SoftOnly(SoftDeleteModel):
    name = models.CharField(max_length=50)
