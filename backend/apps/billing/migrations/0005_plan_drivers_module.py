"""Тарифы: к fleet добавляется drivers (модуль водителей выделен как отдельный).

Самодостаточна, идемпотентна. Изменённые тарифы помечаются в options (``_added_by_billing_0005``);
откат убирает drivers и метку ТОЛЬКО у них (добавленное вручную откатом не затрагивается).
"""

from django.db import migrations

MARK = "_added_by_billing_0005"


def forwards(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    for plan in Plan.objects.all():
        modules = list(plan.modules or [])
        if "fleet" in modules and "drivers" not in modules:
            plan.modules = [*modules, "drivers"]
            plan.options = {**(plan.options or {}), MARK: True}
            plan.save(update_fields=["modules", "options"])


def backwards(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    for plan in Plan.objects.all():
        options = dict(plan.options or {})
        if options.pop(MARK, None):
            plan.modules = [m for m in (plan.modules or []) if m != "drivers"]
            plan.options = options
            plan.save(update_fields=["modules", "options"])


class Migration(migrations.Migration):
    dependencies = [("billing", "0004_plan_logistics_module")]
    operations = [migrations.RunPython(forwards, backwards)]
