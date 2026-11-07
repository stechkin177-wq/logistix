"""Справочник «Категории расходов» (expense_category) существующим компаниям.

Миграция самодостаточна: справочник и значения записаны здесь и не зависят от действующего
кода приложения (дефолтов, реестра системных кодов, tenant_context). Идемпотентна: справочник
создаётся, только если его нет; значения - только те коды, которых в справочнике ещё нет;
существующие значения и пользовательские правки не затрагиваются. Обратима как noop (созданные
справочники и значения не удаляются: на них могут ссылаться расходы).
"""

from django.db import migrations

HANDBOOK = {"code": "expense_category", "name": "Категории расходов", "group": "Финансы"}
# (название, системный код) в порядке отображения
VALUES = (
    ("Топливо", "FUEL"),
    ("Техобслуживание", "MAINTENANCE"),
    ("Ремонт", "REPAIR"),
    ("Шины", "TIRES"),
    ("Дороги и сборы", "ROAD"),
    ("Водитель", "DRIVER"),
    ("Страхование", "INSURANCE"),
    ("Налоги", "TAX"),
    ("Амортизация", "DEPRECIATION"),
    ("Административные", "ADMINISTRATION"),
    ("Прочее", "OTHER"),
)


def _set_company(connection, company_id):
    """RLS: политика по app.company_id (встроено, без tenant_context приложения)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.company_id', %s, false)", [str(company_id or "")])


def run_backfill(apps, connection=None):
    """Идемпотентно: повторный запуск ничего не меняет."""
    if connection is None:
        from django.db import connection
    Company = apps.get_model("core", "Company")
    Handbook = apps.get_model("core", "Handbook")
    HandbookValue = apps.get_model("core", "HandbookValue")
    try:
        for company in Company.objects.all():
            _set_company(connection, company.id)
            handbook, _ = Handbook.objects.get_or_create(
                company_id=company.id,
                code=HANDBOOK["code"],
                defaults={"name": HANDBOOK["name"], "group": HANDBOOK["group"]},
            )
            existing = HandbookValue.objects.filter(handbook_id=handbook.id)
            present = set(existing.values_list("code", flat=True))
            next_order = max(existing.values_list("order", flat=True), default=0)
            for name, code in VALUES:
                if code in present:
                    continue
                next_order += 1
                HandbookValue.objects.create(
                    company_id=company.id,
                    handbook_id=handbook.id,
                    name=name,
                    code=code,
                    order=next_order,
                    is_initial=False,
                    is_final=False,
                    is_active=True,
                )
    finally:
        _set_company(connection, None)


def forwards(apps, schema_editor):
    run_backfill(apps, schema_editor.connection)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0012_trips_revert_completed_permission"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
