"""Тарифы: к forwarding добавляется logistics (общий слой заказов и рейсов выделен из forwarding).

Самодостаточна, идемпотентна. Откат убирает logistics только у тарифов с forwarding.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    for plan in Plan.objects.all():
        modules = list(plan.modules or [])
        if "forwarding" in modules and "logistics" not in modules:
            plan.modules = [*modules, "logistics"]
            plan.save(update_fields=["modules"])


def backwards(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    for plan in Plan.objects.all():
        modules = list(plan.modules or [])
        if "logistics" in modules:
            plan.modules = [m for m in modules if m != "logistics"]
            plan.save(update_fields=["modules"])


class Migration(migrations.Migration):
    dependencies = [("billing", "0003_plan_finance_documents_modules")]
    operations = [migrations.RunPython(forwards, backwards)]
