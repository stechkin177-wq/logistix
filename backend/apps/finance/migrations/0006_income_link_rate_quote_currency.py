"""InvoiceItem.income и ExchangeRate.quote_currency с пересборкой уникальности курсов.

Миграция самодостаточна: ничего не импортирует из apps.*, контекст компании для RLS выставляется
встроенным set_config с обязательным сбросом.

Перед пересборкой уникальности (preflight) проверяются существующие курсы: дубликаты
(компания, валюта, дата) и записи «курс тенге к тенге». При проблеме миграция останавливается с
понятной ошибкой и списком, НИЧЕГО не удаляя и не перезаписывая (исторические курсы неизменны).
Откат разрешён, только если нет данных, которые старая схема не представляет: курсов пар валют
(quote_currency задан) и позиций счетов со ссылкой на доход; иначе миграция остановится, не
удаляя их.
"""

import django.db.models.deletion
from django.db import migrations, models

KZT = "KZT"


def _set_company(connection, company_id):
    """RLS: политика по app.company_id (встроено, без tenant_context приложения)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.company_id', %s, false)", [str(company_id or "")])


def find_rate_conflicts(rows):
    """Конфликты в курсах. rows - dict-и {id, company_id, currency_id, currency_code, date}.

    Возвращает список строк-описаний (пустой - конфликтов нет). Ничего не меняет.
    """
    problems = []
    seen = {}
    for r in sorted(rows, key=lambda x: x["id"]):
        if r["currency_code"] == KZT:
            problems.append(
                f"курс #{r['id']} (компания {r['company_id']}, {r['date']}): "
                f"запись для {KZT} (курс тенге к тенге не бывает)"
            )
        key = (r["company_id"], r["currency_id"], r["date"])
        if key in seen:
            problems.append(
                f"курсы #{seen[key]} и #{r['id']} (компания {r['company_id']}, "
                f"валюта {r['currency_code']}, {r['date']}): дубликат на одну дату"
            )
        else:
            seen[key] = r["id"]
    return problems


def preflight(apps, schema_editor):
    """Проверка курсов до пересборки уникальности; при проблеме - остановка без изменений."""
    connection = schema_editor.connection
    Company = apps.get_model("core", "Company")
    ExchangeRate = apps.get_model("finance", "ExchangeRate")
    problems = []
    try:
        for company in Company.objects.order_by("id"):
            _set_company(connection, company.id)
            rows = [
                {
                    "id": r["id"],
                    "company_id": r["company_id"],
                    "currency_id": r["currency_id"],
                    "currency_code": r["currency__code"],
                    "date": r["date"],
                }
                for r in ExchangeRate.objects.filter(company_id=company.id).values(
                    "id", "company_id", "currency_id", "currency__code", "date"
                )
            ]
            problems += find_rate_conflicts(rows)
    finally:
        _set_company(connection, None)
    if problems:
        raise RuntimeError(
            "finance.0006: перед пересборкой уникальности курсов найдены конфликты, "
            "миграция остановлена, данные не изменены. Исправьте их вручную и повторите:\n  "
            + "\n  ".join(problems)
        )


def guard_reverse(apps, schema_editor):
    """Откат невозможен, пока есть данные, которые старая схема не представляет."""
    connection = schema_editor.connection
    Company = apps.get_model("core", "Company")
    ExchangeRate = apps.get_model("finance", "ExchangeRate")
    InvoiceItem = apps.get_model("finance", "InvoiceItem")
    problems = []
    try:
        for company in Company.objects.order_by("id"):
            _set_company(connection, company.id)
            pairs = ExchangeRate.objects.filter(
                company_id=company.id, quote_currency__isnull=False
            ).count()
            items = InvoiceItem.objects.filter(
                company_id=company.id, income__isnull=False
            ).count()
            if pairs:
                problems.append(f"компания {company.id}: курсов пар валют {pairs}")
            if items:
                problems.append(f"компания {company.id}: позиций счетов со ссылкой на доход {items}")
    finally:
        _set_company(connection, None)
    if problems:
        raise RuntimeError(
            "finance.0006: откат остановлен, чтобы не удалить новые финансовые данные:\n  "
            + "\n  ".join(problems)
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_expense_category_handbook"),
        ("finance", "0005_income_expense_ledger"),
    ]

    operations = [
        migrations.RunPython(preflight, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="exchangerate",
            name="exchangerate_company_cur_date_uniq",
        ),
        migrations.AddField(
            model_name="exchangerate",
            name="quote_currency",
            field=models.ForeignKey(
                blank=True,
                help_text="Валюта котировки (значение справочника currency); пусто - тенге",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="core.handbookvalue",
            ),
        ),
        migrations.AddField(
            model_name="invoiceitem",
            name="income",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="invoice_items",
                to="finance.income",
            ),
        ),
        migrations.AddConstraint(
            model_name="exchangerate",
            constraint=models.UniqueConstraint(
                condition=models.Q(("quote_currency__isnull", True)),
                fields=("company", "currency", "date"),
                name="exchangerate_kzt_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="exchangerate",
            constraint=models.UniqueConstraint(
                condition=models.Q(("quote_currency__isnull", False)),
                fields=("company", "currency", "quote_currency", "date"),
                name="exchangerate_pair_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="exchangerate",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("quote_currency__isnull", True),
                    models.Q(("currency", models.F("quote_currency")), _negated=True),
                    _connector="OR",
                ),
                name="exchangerate_currency_ne_quote",
            ),
        ),
            migrations.RunPython(migrations.RunPython.noop, guard_reverse),
    ]
