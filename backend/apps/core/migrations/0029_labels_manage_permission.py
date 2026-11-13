"""Право labels.manage системным ролям существующих компаний: Администратор, Менеджер, Диспетчер.

Самодостаточна, идемпотентна, пользовательские роли не затрагиваются, обратима как noop.
"""

from django.db import migrations

GRANT = "labels.manage"
ROLES = ["Администратор", "Менеджер", "Диспетчер"]


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
                company_id=company.id, is_system=True, name__in=ROLES
            ):
                if GRANT not in role.permissions:
                    role.permissions = [*role.permissions, GRANT]
                    role.save(update_fields=["permissions"])
    finally:
        _set_company(connection, None)


class Migration(migrations.Migration):
    dependencies = [("core", "0028_labels")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
