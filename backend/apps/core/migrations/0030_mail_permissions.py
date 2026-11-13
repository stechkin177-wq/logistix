"""Права почты (mail.view, mail.send) системным ролям Менеджер и Диспетчер; mail.* - Администратору.

Самодостаточна, идемпотентна, пользовательские роли не затрагиваются, обратима как noop.
"""

from django.db import migrations

GRANTS = {
    "Администратор": ["mail.view", "mail.send", "mail.manage_account"],
    "Менеджер": ["mail.view", "mail.send"],
    "Диспетчер": ["mail.view", "mail.send"],
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
    dependencies = [("core", "0029_labels_manage_permission")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
