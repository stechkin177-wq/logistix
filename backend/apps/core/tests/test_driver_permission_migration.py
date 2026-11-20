"""Миграция core.0034: право driver.use выдаются системным ролям существующих компаний."""

import importlib
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.db import connection

from apps.core.models import Role
from apps.core.tenancy import tenant_context

pytestmark = pytest.mark.django_db

migration = importlib.import_module("apps.core.migrations.0034_driver_use_permission")


def run_forwards():
    migration.forwards(apps, SimpleNamespace(connection=connection))


def perms(company, name):
    with tenant_context(company.id):
        return Role.objects.get(name=name).permissions


def test_driver_use_added_to_driver_role_only_idempotently(make_company):
    company, _, _ = make_company("Old")
    with tenant_context(company.id):  # состояние «до миграции»: права driver.use нет
        for role in Role.objects.all():
            role.permissions = [p for p in role.permissions if p != "driver.use"]
            role.save(update_fields=["permissions"])
        Role.objects.create(
            company=company, name="Своя", permissions=["fleet.view"], is_system=False
        )
    run_forwards()
    assert perms(company, "Водитель") == ["driver.use"]
    assert "driver.use" not in perms(company, "Менеджер")
    assert perms(company, "Своя") == ["fleet.view"]
    run_forwards()
    assert perms(company, "Водитель") == ["driver.use"]  # повтор ничего не дублирует


def test_admin_gets_driver_use_so_it_can_grant_access(make_company):
    """Администратор существующей компании получает driver.use (иначе не выдаст доступ)."""
    mig = importlib.import_module("apps.core.migrations.0035_admin_driver_use")
    company, _, _ = make_company("Old")
    with tenant_context(company.id):
        admin = Role.objects.get(name="Администратор")
        admin.permissions = [p for p in admin.permissions if p != "driver.use"]
        admin.save(update_fields=["permissions"])
    mig.forwards(apps, SimpleNamespace(connection=connection))
    assert "driver.use" in perms(company, "Администратор")
    assert "driver.use" not in perms(company, "Менеджер")
    mig.forwards(apps, SimpleNamespace(connection=connection))
    assert perms(company, "Администратор").count("driver.use") == 1
