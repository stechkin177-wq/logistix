"""Системные коды статусов рейса существующим компаниям (только однозначные сопоставления).

Код назначается значению trip_status, только если: у значения пустой код; в справочнике
компании ровно одно значение с точным названием стандартного статуса; признаки is_initial и
is_final соответствуют стандартным; такой код ещё не занят. Остальное не сопоставляется
(отчёт ручной проверки: management-команда check_system_status_codes). Обратимо как noop:
назначенные коды не снимаются.
"""

from django.db import migrations


def run_backfill(apps):
    """Идемпотентно: повторный запуск ничего не меняет."""
    Company = apps.get_model("core", "Company")
    HandbookValue = apps.get_model("core", "HandbookValue")
    from apps.core.handbooks.status_codes import TRIP_STATUS, automatic_assignments
    from apps.core.handbooks.system_codes import SYSTEM_CODES, system_code_assignment
    from apps.core.tenancy import tenant_context

    codes = SYSTEM_CODES[TRIP_STATUS]
    for company in Company.objects.all():
        with tenant_context(company.id), system_code_assignment():  # RLS: app.company_id
            rows = list(
                HandbookValue.objects.filter(
                    company=company, handbook__code=TRIP_STATUS
                ).values("id", "name", "code", "is_initial", "is_final")
            )
            for pk, code in automatic_assignments(TRIP_STATUS, codes, rows).items():
                HandbookValue.objects.filter(pk=pk, code="").update(code=code)


def forwards(apps, schema_editor):
    run_backfill(apps)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_documents_permissions_numbering"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
