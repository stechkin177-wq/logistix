"""Тарифы: к forwarding добавляется logistics (общий слой заказов и рейсов выделен из forwarding).

Самодостаточна, идемпотентна. Тарифы, изменённые миграцией, помечаются в options
(``_added_by_billing_0004``); откат убирает logistics и метку ТОЛЬКО у них. Тарифы, где logistics
был добавлен вручную или раньше, откатом не затрагиваются.
"""

from django.db import migrations

MARK = "_added_by_billing_0004"


def forwards(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    for plan in Plan.objects.all():
        modules = list(plan.modules or [])
        if "forwarding" in modules and "logistics" not in modules:
            plan.modules = [*modules, "logistics"]
            plan.options = {**(plan.options or {}), MARK: True}
            plan.save(update_fields=["modules", "options"])


def backwards(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    for plan in Plan.objects.all():
        options = dict(plan.options or {})
        if options.pop(MARK, None):
            plan.modules = [m for m in (plan.modules or []) if m != "logistics"]
            plan.options = options
            plan.save(update_fields=["modules", "options"])


class Migration(migrations.Migration):
    dependencies = [("billing", "0003_plan_finance_documents_modules")]
    operations = [migrations.RunPython(forwards, backwards)]
