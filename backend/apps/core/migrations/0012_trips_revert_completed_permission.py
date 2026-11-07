"""Право trips.revert_completed (выход рейса из статуса «Завершён») роли «Администратор».

Миграция самодостаточна: код права и имя роли записаны здесь, действующий каталог прав не
импортируется. Обратима как noop; идемпотентна; пользовательские роли не затрагиваются.
"""

from django.db import migrations

PERMISSION = "trips.revert_completed"
ROLES = ("Администратор",)


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
            for role in Role.objects.filter(company_id=company.id, is_system=True, name__in=ROLES):
                if PERMISSION not in role.permissions:
                    role.permissions = [*role.permissions, PERMISSION]
                    role.save(update_fields=["permissions"])
    finally:
        _set_company(connection, None)


def forwards(apps, schema_editor):
    run_backfill(apps, schema_editor.connection)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0011_trip_status_codes"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
