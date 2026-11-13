"""Ремонтные миграции core.0031 и forwarding.0019: чинят расхождение схемы и не трогают данные.

Расхождение возникло на демо-БД из-за редакций миграций, применённых до исправления: нет таблицы
core_companyauditsettings и столбца forwarding_contract.document_id. Миграции создают недостающее
(под RLS) и остаются пустой операцией на БД, где всё есть.
"""

import importlib

import pytest
from django.apps import apps
from django.db import connection

pytestmark = pytest.mark.django_db

core_0031 = importlib.import_module("apps.core.migrations.0031_repair_login_audit_settings")
fwd_0019 = importlib.import_module("apps.forwarding.migrations.0019_repair_contract_document")


def _columns(table):
    with connection.cursor() as cursor:
        return {c.name for c in connection.introspection.get_table_description(cursor, table)}


def _run(module):
    with connection.schema_editor() as editor:
        module.forwards(apps, editor)


def test_noop_when_schema_is_complete():
    before = (_columns("forwarding_contract"), connection.introspection.table_names())
    _run(core_0031)
    _run(fwd_0019)
    assert before == (_columns("forwarding_contract"), connection.introspection.table_names())


def test_recreates_missing_contract_document_column_without_touching_data():
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE forwarding_contract DROP COLUMN document_id")
    assert "document_id" not in _columns("forwarding_contract")
    _run(fwd_0019)
    assert "document_id" in _columns("forwarding_contract")
    with connection.cursor() as cursor:  # внешний ключ на выданные документы восстановлен
        cursor.execute(
            "SELECT count(*) FROM information_schema.table_constraints c "
            "JOIN information_schema.key_column_usage k USING (constraint_name, table_name) "
            "WHERE c.table_name = 'forwarding_contract' AND k.column_name = 'document_id' "
            "AND c.constraint_type = 'FOREIGN KEY'"
        )
        assert cursor.fetchone()[0] == 1


def test_recreates_missing_audit_settings_table_under_rls():
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE core_companyauditsettings")
    assert "core_companyauditsettings" not in connection.introspection.table_names()
    _run(core_0031)
    assert "core_companyauditsettings" in connection.introspection.table_names()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname = 'core_companyauditsettings'"
        )
        assert cursor.fetchone() == (True, True)
        cursor.execute(
            "SELECT count(*) FROM pg_policies WHERE tablename = 'core_companyauditsettings'"
        )
        assert cursor.fetchone()[0] == 1
