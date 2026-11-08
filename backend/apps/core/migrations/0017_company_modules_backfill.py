"""Данные: CompanyModule существующих компаний из Company.modules.

Миграция самодостаточна (код приложения не импортируется). Для каждой компании:
 - включённые модули берутся из Company.modules (core не хранится; неизвестные коды и core
   пропускаются, порядок сохраняется);
 - компаниям с forwarding дополнительно включаются finance и documents (сейчас они доступны
   внутри forwarding, поведение не меняется);
 - проекция Company.modules приводится к включённым модулям: прежние коды сохраняются в прежнем
   порядке, finance и documents добавляются в конец.
Идемпотентна: существующие строки CompanyModule не перезаписываются (включение добавляется, если
строки нет; отключённая вручную строка не включается повторно). Обратима: откат удаляет только
строки, созданные этой миграцией (enabled_by пуст, причина-маркер), и возвращает Company.modules
к списку без добавленных ею finance/documents, если они были добавлены ею.
"""

from django.db import migrations

KNOWN = {
    "documents",
    "forwarding",
    "finance",
    "fleet",
    "drivers",
    "driver_app",
    "gps",
    "ocr",
    "notifications",
    "analytics",
}
FORWARDING_COMPANIONS = ("finance", "documents")
MARKER = "Миграция core.0017: перенос из Company.modules"
MARKER_ADDED = "Миграция core.0017: включено вместе с forwarding"


def _set_company(connection, company_id):
    """RLS: политика по app.company_id (встроено, без tenant_context приложения)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.company_id', %s, false)", [str(company_id or "")])


def run_backfill(apps, connection=None):
    if connection is None:
        from django.db import connection
    from django.utils import timezone

    Company = apps.get_model("core", "Company")
    CompanyModule = apps.get_model("core", "CompanyModule")
    now = timezone.now()
    try:
        for company in Company.objects.all().order_by("id"):
            _set_company(connection, company.id)
            current = [m for m in (company.modules or []) if m in KNOWN]
            wanted = list(dict.fromkeys(current))
            added = []
            if "forwarding" in wanted:
                for code in FORWARDING_COMPANIONS:
                    if code not in wanted:
                        wanted.append(code)
                        added.append(code)
            existing = {
                r.module_code: r for r in CompanyModule._base_manager.filter(company_id=company.id)
            }
            for code in wanted:
                if code in existing:
                    continue
                CompanyModule._base_manager.create(
                    company_id=company.id,
                    module_code=code,
                    enabled=True,
                    enabled_at=now,
                    reason=MARKER_ADDED if code in added else MARKER,
                )
            enabled_codes = [
                r.module_code
                for r in CompanyModule._base_manager.filter(
                    company_id=company.id, enabled=True
                ).order_by("id")
            ]
            # проекция: сначала прежний порядок Company.modules, затем остальные включённые
            projection = [m for m in (company.modules or []) if m in enabled_codes]
            projection += [m for m in enabled_codes if m not in projection]
            if projection != list(company.modules or []):
                company.modules = projection
                company.save(update_fields=["modules"])
    finally:
        _set_company(connection, None)


def run_reverse(apps, connection=None):
    if connection is None:
        from django.db import connection
    Company = apps.get_model("core", "Company")
    CompanyModule = apps.get_model("core", "CompanyModule")
    try:
        for company in Company.objects.all().order_by("id"):
            _set_company(connection, company.id)
            migrated = CompanyModule._base_manager.filter(
                company_id=company.id, enabled_by__isnull=True, reason__in=[MARKER, MARKER_ADDED]
            )
            added = set(migrated.filter(reason=MARKER_ADDED).values_list("module_code", flat=True))
            if added:
                company.modules = [m for m in (company.modules or []) if m not in added]
                company.save(update_fields=["modules"])
            migrated.delete()
    finally:
        _set_company(connection, None)


def forwards(apps, schema_editor):
    run_backfill(apps, schema_editor.connection)


def backwards(apps, schema_editor):
    run_reverse(apps, schema_editor.connection)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0016_companymodule"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
