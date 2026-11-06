"""Стартовые шаблоны документов для уже существующих компаний."""

from django.db import migrations


def run_backfill(apps):
    """Идемпотентно: недостающие шаблоны и стартовые версии для каждой компании."""
    from apps.documents.starter import _seed

    Company = apps.get_model("core", "Company")
    DocumentTemplate = apps.get_model("documents", "DocumentTemplate")
    DocumentTemplateVersion = apps.get_model("documents", "DocumentTemplateVersion")
    for company_id in Company.objects.values_list("id", flat=True):
        _seed(company_id, DocumentTemplate.objects, DocumentTemplateVersion.objects)


def forwards(apps, schema_editor):
    run_backfill(apps)


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
