"""Тарифы: к forwarding добавляются finance и documents (доступ к ним раньше шёл через forwarding).

Без этого после перевода эндпоинтов финансов и документов на собственные модули доступ у
компаний пропал бы. Миграция самодостаточна, идемпотентна (уже имеющиеся коды не дублируются)
и обратима: откат убирает finance и documents только у тарифов, где они были добавлены этой
миграцией (по списку, записанному в самом откате: тарифы с forwarding). Остальные модули и тарифы
без forwarding не затрагиваются.
"""

from django.db import migrations

COMPANIONS = ("finance", "documents")


def forwards(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    for plan in Plan.objects.all():
        modules = list(plan.modules or [])
        if "forwarding" not in modules:
            continue
        missing = [c for c in COMPANIONS if c not in modules]
        if missing:
            plan.modules = [*modules, *missing]
            plan.save(update_fields=["modules"])


def backwards(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    for plan in Plan.objects.all():
        modules = list(plan.modules or [])
        if "forwarding" in modules and any(c in modules for c in COMPANIONS):
            plan.modules = [m for m in modules if m not in COMPANIONS]
            plan.save(update_fields=["modules"])


class Migration(migrations.Migration):
    dependencies = [("billing", "0002_default_plans")]
    operations = [migrations.RunPython(forwards, backwards)]
