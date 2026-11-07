"""Право trips.revert_completed (выход рейса из статуса «Завершён») роли «Администратор»."""

from django.db import migrations

PERMISSION = "trips.revert_completed"
ROLES = ("Администратор",)


def run_backfill(apps):
    """Идемпотентно: дописывает право системным ролям «Администратор» всех компаний."""
    Role = apps.get_model("core", "Role")
    Company = apps.get_model("core", "Company")
    from apps.core.tenancy import tenant_context

    for company in Company.objects.all():
        with tenant_context(company.id):  # RLS: политика по app.company_id
            for role in Role.objects.filter(company=company, is_system=True, name__in=ROLES):
                if PERMISSION not in role.permissions:
                    role.permissions = [*role.permissions, PERMISSION]
                    role.save(update_fields=["permissions"])


def forwards(apps, schema_editor):
    run_backfill(apps)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0011_trip_status_codes"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
