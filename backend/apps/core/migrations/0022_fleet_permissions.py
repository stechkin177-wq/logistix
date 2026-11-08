"""Права раздела fleet системным ролям существующих компаний.

Администратор - fleet.view/create/update/delete; Менеджер, Диспетчер, Наблюдатель - fleet.view;
Механик - fleet.view/create/update.
Самодостаточна (коды прав и имена ролей записаны здесь), идемпотентна (права не дублируются),
пользовательские роли не затрагиваются, обратима как noop (выданные права не отзываются).
"""

from django.db import migrations

ADMIN = "Администратор"
GRANTS = {
    ADMIN: ["fleet.view", "fleet.create", "fleet.update", "fleet.delete"],
    "Менеджер": ["fleet.view"],
    "Диспетчер": ["fleet.view"],
    "Наблюдатель": ["fleet.view"],
    "Механик": ["fleet.view", "fleet.create", "fleet.update"],
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
    dependencies = [("core", "0021_drivers_permissions")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
