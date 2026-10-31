from django.db import migrations

# ВНИМАНИЕ: значения лимитов предварительные (provisional), подлежат уточнению
# владельцем продукта. Цены в коде и миграциях не хранятся. null = без ограничений.
_NO_LIMITS = {
    "max_users": None,
    "max_vehicles": None,
    "max_orders_per_month": None,
    "max_ocr_per_month": None,
}
PLANS = [
    {
        "code": "start",
        "name": "Старт",
        "billing_type": "monthly",
        "limits": {
            "max_users": 5,
            "max_vehicles": 5,
            "max_orders_per_month": 200,
            "max_ocr_per_month": 50,
        },
        "options": {"white_label": False, "custom_domain": False},
    },
    {
        "code": "business",
        "name": "Бизнес",
        "billing_type": "yearly",
        "limits": {
            "max_users": 50,
            "max_vehicles": 50,
            "max_orders_per_month": 5000,
            "max_ocr_per_month": 1000,
        },
        "options": {"white_label": True, "custom_domain": True},
    },
    {
        "code": "lifetime",
        "name": "Бессрочный",
        "billing_type": "lifetime",
        "limits": _NO_LIMITS,
        "options": {"white_label": True, "custom_domain": True},
    },
]


def seed_plans(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    for data in PLANS:
        Plan.objects.update_or_create(
            code=data["code"],
            defaults={**data, "modules": ["forwarding", "fleet"], "is_active": True},
        )


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial")]
    operations = [migrations.RunPython(seed_plans, migrations.RunPython.noop)]
