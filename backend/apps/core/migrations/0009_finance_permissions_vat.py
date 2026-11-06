"""Права finance.override_limit/cancel_invoice системным ролям и справочник ставок НДС."""

from django.db import migrations

EXTRA = ["finance.override_limit", "finance.cancel_invoice"]
ROLES = ("Администратор", "Бухгалтер")


def run_backfill(apps):
    """Идемпотентно: добавляет недостающие коды системным ролям и сидит справочник НДС."""
    Role = apps.get_model("core", "Role")
    Company = apps.get_model("core", "Company")
    Handbook = apps.get_model("core", "Handbook")
    HandbookValue = apps.get_model("core", "HandbookValue")
    from apps.core.handbooks.defaults import DEFAULTS
    from apps.core.tenancy import tenant_context

    spec = DEFAULTS["vat_rate"]
    for company in Company.objects.all():
        with tenant_context(company.id):  # RLS: политика по app.company_id
            for role in Role.objects.filter(company=company, is_system=True, name__in=ROLES):
                missing = [c for c in EXTRA if c not in role.permissions]
                if missing:
                    role.permissions = [*role.permissions, *missing]
                    role.save(update_fields=["permissions"])
            handbook, created = Handbook.objects.get_or_create(
                company=company,
                code="vat_rate",
                defaults={"name": spec["name"], "group": spec["group"]},
            )
            if created:
                HandbookValue.objects.bulk_create(
                    HandbookValue(
                        company=company,
                        handbook=handbook,
                        name=item["name"],
                        code=item.get("code", ""),
                        order=i,
                    )
                    for i, item in enumerate(spec["values"], start=1)
                )


def forwards(apps, schema_editor):
    run_backfill(apps)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_companybranding"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
