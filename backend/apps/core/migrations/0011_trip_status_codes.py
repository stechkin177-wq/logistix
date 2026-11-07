"""Системные коды статусов рейса существующим компаниям (только однозначные сопоставления).

Миграция самодостаточна: константы и алгоритм зафиксированы здесь и не зависят от действующего
кода приложения (реестра, дефолтов, tenant_context), который может измениться позже.

Код назначается значению trip_status, только если: у значения пустой код; в справочнике
компании ровно одно значение с точным названием стандартного статуса (регистр и пробелы
строго); признаки is_initial и is_final соответствуют стандартным; такой код ещё не занят.
Остальное не сопоставляется (отчёт ручной проверки: команда check_system_status_codes).
Обратима как noop: назначенные коды не снимаются.
"""

from django.db import migrations

HANDBOOK = "trip_status"
# (название, код, is_initial, is_final)
SPECS = (
    ("Планируется", "PLANNED", True, False),
    ("Ожидает выезда", "ASSIGNED", False, False),
    ("В пути", "IN_PROGRESS", False, False),
    ("Выгрузка", "UNLOADING", False, False),
    ("Завершён", "COMPLETED", False, True),
    ("Отменён", "CANCELLED", False, True),
)


def select_assignments(rows):
    """{id значения: код} только для однозначных сопоставлений. rows - dict-и значений."""
    result = {}
    for name, code, is_initial, is_final in SPECS:
        if any(r["code"] == code for r in rows):
            continue  # код уже занят
        exact = [r for r in rows if r["name"] == name]
        if len(exact) != 1:
            continue  # нет значения или дубликаты
        row = exact[0]
        if row["code"] or bool(row["is_initial"]) != is_initial or bool(row["is_final"]) != is_final:
            continue  # другой код или иные признаки
        result[row["id"]] = code
    return result


def _set_company(connection, company_id):
    """RLS: политика по app.company_id (встроено, без tenant_context приложения)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.company_id', %s, false)", [str(company_id or "")])


def run_backfill(apps, connection=None):
    """Идемпотентно: повторный запуск ничего не меняет."""
    if connection is None:
        from django.db import connection
    Company = apps.get_model("core", "Company")
    HandbookValue = apps.get_model("core", "HandbookValue")
    try:
        for company in Company.objects.all():
            _set_company(connection, company.id)
            rows = list(
                HandbookValue.objects.filter(company_id=company.id, handbook__code=HANDBOOK).values(
                    "id", "name", "code", "is_initial", "is_final"
                )
            )
            for pk, code in select_assignments(rows).items():
                HandbookValue.objects.filter(pk=pk, code="").update(code=code)
    finally:
        _set_company(connection, None)


def forwards(apps, schema_editor):
    run_backfill(apps, schema_editor.connection)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_documents_permissions_numbering"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
