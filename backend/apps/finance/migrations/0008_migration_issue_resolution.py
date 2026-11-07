"""FinanceMigrationIssue: сохранённое решение (resolution, resolution_data) и уникальность
проблем ambiguous_trip_expense по (компания, тип, источник, id источника).

Миграция самодостаточна: ничего не импортирует из apps.*, контекст компании для RLS выставляется
встроенным set_config с обязательным сбросом. Перед созданием ограничения (preflight) ищутся
дубликаты проблем по одной строке (открытая и ранее разрешённая); при их наличии миграция
останавливается со списком, ничего не удаляя и не изменяя.
"""

from django.conf import settings
from django.db import migrations, models

ISSUE_TYPE = "ambiguous_trip_expense"


def _set_company(connection, company_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.company_id', %s, false)", [str(company_id or "")])


def find_duplicates(rows):
    """rows - dict-и {id, company_id, source_model, source_id}; список описаний дублей."""
    seen: dict = {}
    problems = []
    for r in sorted(rows, key=lambda x: x["id"]):
        if r["source_id"] is None:
            continue
        key = (r["company_id"], r["source_model"], r["source_id"])
        if key in seen:
            problems.append(
                f"проблемы #{seen[key]} и #{r['id']} (компания {r['company_id']}, "
                f"{r['source_model']} #{r['source_id']}): дубль по одной строке"
            )
        else:
            seen[key] = r["id"]
    return problems


def preflight(apps, schema_editor):
    connection = schema_editor.connection
    Company = apps.get_model("core", "Company")
    Issue = apps.get_model("finance", "FinanceMigrationIssue")
    problems = []
    try:
        for company in Company.objects.order_by("id"):
            _set_company(connection, company.id)
            rows = list(
                Issue.objects.filter(issue_type=ISSUE_TYPE).values(
                    "id", "company_id", "source_model", "source_id"
                )
            )
            problems += find_duplicates(rows)
    finally:
        _set_company(connection, None)
    if problems:
        raise RuntimeError(
            "Миграция остановлена: дубли проблем ambiguous_trip_expense. Разберите вручную "
            "(ничего не удалено): " + "; ".join(problems)
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0014_finance_architecture_permissions"),
        ("finance", "0007_company_financial_settings_backfill"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="financemigrationissue",
            name="resolution",
            field=models.CharField(
                blank=True,
                db_default="",
                help_text="Выбранное решение: carrier_expense, manual_expense, justified_exclusion",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="financemigrationissue",
            name="resolution_data",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(preflight, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="financemigrationissue",
            constraint=models.UniqueConstraint(
                condition=models.Q(("issue_type", "ambiguous_trip_expense")),
                fields=("company", "issue_type", "source_model", "source_id"),
                name="finissue_ambiguous_source_uniq",
            ),
        ),
    ]
