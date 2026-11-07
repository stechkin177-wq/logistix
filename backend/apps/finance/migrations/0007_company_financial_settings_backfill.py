"""Строка CompanyFinancialSettings для каждой существующей компании (совместимые значения).

Миграция самодостаточна: ничего не импортирует из apps.*, контекст компании для RLS выставляется
встроенным set_config с обязательным сбросом. Значения: engine='legacy' (прежний учёт, ничего не
переключается), allow_backdating=True (текущее поведение), expense_creation_mode='manual',
sync_carrier_price=True, income_recognition='all_trips_completed', accounting_method='ACCRUAL',
fiscal_year_start_month=1.

base_currency - значение справочника currency с кодом KZT этой компании (нет - NULL).
completed_status - значение trip_status с кодом COMPLETED ТОЛЬКО если оно ровно одно и активно;
иначе NULL и автоматически НЕ назначается (компания остаётся заблокированной для переключения
на engine=new до ручного сопоставления).

Идемпотентна: у компании с уже существующей строкой ничего не меняется. Обратима как noop
(строки удаляются откатом finance.0004 вместе с таблицей).
"""

from django.db import migrations

CURRENCY_HANDBOOK = "currency"
BASE_CURRENCY_CODE = "KZT"
STATUS_HANDBOOK = "trip_status"
COMPLETED_CODE = "COMPLETED"


def _set_company(connection, company_id):
    """RLS: политика по app.company_id (встроено, без tenant_context приложения)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.company_id', %s, false)", [str(company_id or "")])


def pick_unambiguous(rows, only_active=False):
    """id единственного значения из rows (dict-и {id, is_active}); иначе None."""
    if only_active:
        rows = [r for r in rows if r["is_active"]]
    return rows[0]["id"] if len(rows) == 1 else None


def initial_values(HandbookValue, company_id):
    """Начальные base_currency_id и completed_status_id компании (None - не назначать)."""

    def rows(handbook, code):
        return list(
            HandbookValue.objects.filter(
                company_id=company_id, handbook__code=handbook, code=code
            ).values("id", "is_active")
        )

    return {
        "base_currency_id": pick_unambiguous(rows(CURRENCY_HANDBOOK, BASE_CURRENCY_CODE)),
        "completed_status_id": pick_unambiguous(
            rows(STATUS_HANDBOOK, COMPLETED_CODE), only_active=True
        ),
    }


def run_backfill(apps, connection=None):
    if connection is None:
        from django.db import connection
    Company = apps.get_model("core", "Company")
    HandbookValue = apps.get_model("core", "HandbookValue")
    Settings = apps.get_model("finance", "CompanyFinancialSettings")
    try:
        for company in Company.objects.order_by("id"):
            _set_company(connection, company.id)
            if Settings.objects.filter(company_id=company.id).exists():
                continue
            Settings.objects.create(
                company_id=company.id,
                accounting_method="ACCRUAL",
                fiscal_year_start_month=1,
                allow_backdating=True,
                engine="legacy",
                income_recognition="all_trips_completed",
                expense_creation_mode="manual",
                sync_carrier_price=True,
                **initial_values(HandbookValue, company.id),
            )
    finally:
        _set_company(connection, None)


def forwards(apps, schema_editor):
    run_backfill(apps, schema_editor.connection)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0013_expense_category_handbook"),
        ("finance", "0006_income_link_rate_quote_currency"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
