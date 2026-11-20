"""Миграция core.0033: права распознавания выдаются системным ролям существующих компаний."""

import importlib
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.db import connection

from apps.core.models import Role
from apps.core.tenancy import tenant_context

pytestmark = pytest.mark.django_db

migration = importlib.import_module("apps.core.migrations.0033_ocr_permissions")


def run_forwards():
    migration.forwards(apps, SimpleNamespace(connection=connection))


def perms(company, name):
    with tenant_context(company.id):
        return Role.objects.get(name=name).permissions


def test_ocr_permissions_added_to_system_roles_idempotently(make_company):
    company, _, _ = make_company("Old")
    with tenant_context(company.id):  # состояние «до миграции»: прав GPS в ролях нет
        for role in Role.objects.all():
            role.permissions = [p for p in role.permissions if not p.startswith("ocr.")]
            role.save(update_fields=["permissions"])
        Role.objects.create(
            company=company, name="Своя", permissions=["fleet.view"], is_system=False
        )
    run_forwards()
    assert {"ocr.view", "ocr.manage", "ocr.delete"} <= set(perms(company, "Администратор"))
    for name in ("Менеджер", "Бухгалтер", "Диспетчер", "Механик"):
        got = perms(company, name)
        assert {"ocr.view", "ocr.create"} <= set(got), name
        assert "ocr.manage" not in got and "ocr.delete" not in got, name
    assert perms(company, "Наблюдатель") == ["ocr.view"] or "ocr.view" in perms(
        company, "Наблюдатель"
    )
    assert "ocr.view" not in perms(company, "Водитель")
    assert perms(company, "Своя") == ["fleet.view"]  # пользовательская роль не тронута
    before = perms(company, "Администратор")
    run_forwards()
    assert perms(company, "Администратор") == before  # повтор ничего не дублирует
