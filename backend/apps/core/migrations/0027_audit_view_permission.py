"""Право audit.view ролям, у которых уже есть company.view (сохранение доступа к журналу).

Раньше чтение журнала аудита требовало company.view; теперь - отдельное право audit.view.
Чтобы никто не потерял доступ, право получают все роли (системные и пользовательские) с company.view.
Самодостаточна, идемпотентна, обратима как noop (выданные права не отзываются).
"""

from django.db import migrations


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
            for role in Role._base_manager.filter(company_id=company.id):
                if "company.view" in role.permissions and "audit.view" not in role.permissions:
                    role.permissions = [*role.permissions, "audit.view"]
                    role.save(update_fields=["permissions"])
    finally:
        _set_company(connection, None)


class Migration(migrations.Migration):
    dependencies = [("core", "0026_login_audit_retention")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
