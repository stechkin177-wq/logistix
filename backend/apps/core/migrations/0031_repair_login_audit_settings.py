"""Ремонт схемы: таблица core_companyauditsettings (настройки срока хранения журнала входов) под RLS.

Зачем: миграция 0026 была переписана после того, как её первая редакция (столбец
Company.login_audit_retention_days) попала на демо-БД, поэтому там таблицы настроек нет.
Что делает: создаёт таблицу и включает RLS ТОЛЬКО если таблицы ещё нет. На новой БД это пустая
операция. Ничего не удаляет и не меняет: столбец Company.login_audit_retention_days на старых БД
остаётся нетронутым (код его не использует). Состояние моделей не меняется (модель уже в 0026).
"""

from django.db import migrations

from apps.core.rls import enable_rls

TABLE = "core_companyauditsettings"


def forwards(apps, schema_editor):
    connection = schema_editor.connection
    if TABLE in connection.introspection.table_names():
        return
    schema_editor.create_model(apps.get_model("core", "CompanyAuditSettings"))
    for sql in enable_rls(TABLE):
        schema_editor.execute(sql)


class Migration(migrations.Migration):
    dependencies = [("core", "0030_mail_permissions")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
