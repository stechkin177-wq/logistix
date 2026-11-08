"""Право consignments.transfer системным ролям «Администратор», «Менеджер», «Диспетчер».

Самодостаточна (код права и имена ролей записаны здесь), независима от остальных миграций
этапа 1.5-D, идемпотентна (право не дублируется), пользовательские и прочие системные роли не
затрагиваются, обратима как noop (выданные права не отзываются). Источник: addendum v1.1, разд. 3.2.
"""

from django.db import migrations

PERMISSION = "consignments.transfer"
ROLES = ("Администратор", "Менеджер", "Диспетчер")


def _set_company(connection, company_id):
    """RLS: политика по app.company_id (встроено, без tenant_context приложения)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.company_id', %s, false)", [str(company_id or "")])


def run_backfill(apps, connection=None):
    if connection is None:
        from django.db import connection
    Role = apps.get_model("core", "Role")
    Company = apps.get_model("core", "Company")
    try:
        for company in Company.objects.all():
            _set_company(connection, company.id)
            for role in Role._base_manager.filter(
                company_id=company.id, is_system=True, name__in=ROLES
            ):
                if PERMISSION not in role.permissions:
                    role.permissions = [*role.permissions, PERMISSION]
                    role.save(update_fields=["permissions"])
    finally:
        _set_company(connection, None)


def forwards(apps, schema_editor):
    run_backfill(apps, schema_editor.connection)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0018_manage_modules_permission"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
