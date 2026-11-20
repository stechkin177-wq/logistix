"""Миграция core.0032: права GPS выдаются системным ролям существующих компаний."""

import importlib
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.db import connection

from apps.core.models import Role
from apps.core.tenancy import tenant_context

pytestmark = pytest.mark.django_db

migration = importlib.import_module("apps.core.migrations.0032_gps_permissions")


def run_forwards():
    migration.forwards(apps, SimpleNamespace(connection=connection))


def perms(company, name):
    with tenant_context(company.id):
        return Role.objects.get(name=name).permissions


def test_gps_permissions_added_to_system_roles_idempotently(make_company):
    company, _, _ = make_company("Old")
    with tenant_context(company.id):  # состояние «до миграции»: прав GPS в ролях нет
        for role in Role.objects.all():
            role.permissions = [p for p in role.permissions if not p.startswith("gps.")]
            role.save(update_fields=["permissions"])
        Role.objects.create(
            company=company, name="Своя", permissions=["fleet.view"], is_system=False
        )
    run_forwards()
    assert {"gps.view", "gps.manage"} <= set(perms(company, "Администратор"))
    for name in ("Менеджер", "Диспетчер", "Механик", "Наблюдатель"):
        got = perms(company, name)
        assert "gps.view" in got and "gps.manage" not in got, name
    assert "gps.view" not in perms(company, "Бухгалтер") and perms(company, "Водитель") == []
    assert perms(company, "Своя") == ["fleet.view"]  # пользовательская роль не тронута
    before = perms(company, "Администратор")
    run_forwards()
    assert perms(company, "Администратор") == before  # повтор ничего не дублирует
