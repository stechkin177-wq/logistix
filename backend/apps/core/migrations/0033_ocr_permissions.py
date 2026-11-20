"""Права распознавания документов (ocr.*) системным ролям существующих компаний (как в SYSTEM_ROLES).

Администратор - все, Менеджер, Бухгалтер, Диспетчер - просмотр, загрузка и правка, Механик -
просмотр и загрузка, Наблюдатель - просмотр. Пользовательские роли не затрагиваются.

Самодостаточна, идемпотентна, обратима как noop.
"""

from django.db import migrations

GRANTS = {
    "Администратор": ["ocr.view", "ocr.create", "ocr.update", "ocr.delete", "ocr.manage"],
    "Менеджер": ["ocr.view", "ocr.create", "ocr.update"],
    "Бухгалтер": ["ocr.view", "ocr.create", "ocr.update"],
    "Диспетчер": ["ocr.view", "ocr.create", "ocr.update"],
    "Механик": ["ocr.view", "ocr.create"],
    "Наблюдатель": ["ocr.view"],
}


def _set_company(connection, company_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.company_id', %s, false)", [str(company_id or "")])


def forwards(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    Company = apps.get_model("core", "Company")
    connection = schema_editor.connection
    try:
        for company in Company.objects.all():
            _set_company(connection, company.id)
            for role in Role._base_manager.filter(
                company_id=company.id, is_system=True, name__in=list(GRANTS)
            ):
                missing = [p for p in GRANTS[role.name] if p not in role.permissions]
                if missing:
                    role.permissions = [*role.permissions, *missing]
                    role.save(update_fields=["permissions"])
    finally:
        _set_company(connection, None)


class Migration(migrations.Migration):
    dependencies = [("core", "0032_gps_permissions")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
