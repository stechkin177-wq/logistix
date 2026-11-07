"""Права финансовой архитектуры системным ролям существующих компаний.

Миграция самодостаточна: коды прав и имена ролей записаны здесь, действующий каталог прав не
импортируется. Матрица по умолчанию (утверждена заказчиком): «Администратор» - все пять прав;
«Бухгалтер» - close_period, adjust_closed, backdate (НЕ reopen_period и НЕ manage_settings);
остальные системные роли и пользовательские роли не затрагиваются. Идемпотентна: уже имеющиеся
права не дублируются. Обратима как noop (выданные права не отзываются).
"""

from django.db import migrations

MATRIX = {
    "Администратор": (
        "finance.close_period",
        "finance.reopen_period",
        "finance.adjust_closed",
        "finance.backdate",
        "finance.manage_settings",
    ),
    "Бухгалтер": (
        "finance.close_period",
        "finance.adjust_closed",
        "finance.backdate",
    ),
}


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
            for role in Role.objects.filter(
                company_id=company.id, is_system=True, name__in=list(MATRIX)
            ):
                missing = [p for p in MATRIX[role.name] if p not in role.permissions]
                if missing:
                    role.permissions = [*role.permissions, *missing]
                    role.save(update_fields=["permissions"])
    finally:
        _set_company(connection, None)


def forwards(apps, schema_editor):
    run_backfill(apps, schema_editor.connection)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0013_expense_category_handbook"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
