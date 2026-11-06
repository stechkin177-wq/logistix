"""Права раздела documents системным ролям и правила нумерации документов."""

from django.db import migrations, models

ADD = {
    "Администратор": ["documents.view", "documents.create", "documents.update", "documents.delete"],
    "Менеджер": ["documents.view", "documents.create"],
    "Бухгалтер": ["documents.view", "documents.create"],
    "Диспетчер": ["documents.view", "documents.create"],
    "Наблюдатель": ["documents.view"],
}
KINDS = {
    "contract": {"template": "Д-{year}-{index}", "digits": 5},
    "act": {"template": "АКТ-{year}-{index}", "digits": 5},
    "carrier_order": {"template": "ЗП-{year}-{index}", "digits": 5},
    "cmr": {"template": "CMR-{year}-{index}", "digits": 5},
    "letter": {"template": "ИСХ-{year}-{index}", "digits": 5},
}


def run_backfill(apps):
    """Идемпотентно: дописывает права системным ролям и создаёт недостающие правила."""
    Role = apps.get_model("core", "Role")
    Company = apps.get_model("core", "Company")
    NumberingRule = apps.get_model("core", "NumberingRule")
    from apps.core.tenancy import tenant_context

    for company in Company.objects.all():
        with tenant_context(company.id):  # RLS: политика по app.company_id
            for role in Role.objects.filter(company=company, is_system=True, name__in=ADD):
                missing = [c for c in ADD[role.name] if c not in role.permissions]
                if missing:
                    role.permissions = [*role.permissions, *missing]
                    role.save(update_fields=["permissions"])
            for kind, spec in KINDS.items():
                NumberingRule.objects.get_or_create(company=company, kind=kind, defaults=spec)


def forwards(apps, schema_editor):
    run_backfill(apps)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0009_finance_permissions_vat"),
    ]

    operations = [
        migrations.AlterField(
            model_name="numberingrule",
            name="kind",
            field=models.CharField(
                choices=[
                    ("order", "Заявка"),
                    ("trip", "Рейс"),
                    ("consolidated_trip", "Сборный рейс"),
                    ("invoice_out", "Счёт клиенту"),
                    ("invoice_in", "Счёт от перевозчика"),
                    ("contract", "Договор"),
                    ("act", "Акт"),
                    ("carrier_order", "Заявка перевозчику"),
                    ("cmr", "CMR"),
                    ("letter", "Исходящее письмо"),
                ],
                max_length=32,
            ),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
