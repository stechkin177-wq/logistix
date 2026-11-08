"""Данные: универсальный субъект выданных документов существующих записей (A7).

Детерминированно по виду документа, прежние поля не меняются:
  contract -> forwarding.client (client_id); order_request -> forwarding.order (order_id);
  carrier_order и cmr -> forwarding.trip (trip_id); act и invoice_print -> finance.invoice
  (invoice_id); letter -> forwarding.order, если order задан (иначе субъекта нет).
Миграция самодостаточна (код приложения не импортируется), идемпотентна (заполняются только
записи без субъекта) и обратима (откат стирает субъекта только у записей, у которых он
совпадает с вычисляемым по виду, то есть заполнен этой миграцией; позже записанные другие
субъекты не затрагиваются).
"""

from django.db import migrations
from django.db.models import F

# вид -> (subject_type, поле прежней связи)
MAPPING = {
    "contract": ("forwarding.client", "client_id"),
    "order_request": ("forwarding.order", "order_id"),
    "carrier_order": ("forwarding.trip", "trip_id"),
    "cmr": ("forwarding.trip", "trip_id"),
    "act": ("finance.invoice", "invoice_id"),
    "invoice_print": ("finance.invoice", "invoice_id"),
    "letter": ("forwarding.order", "order_id"),
}


def _set_company(connection, company_id):
    """RLS: политика по app.company_id (встроено, без tenant_context приложения)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.company_id', %s, false)", [str(company_id or "")])


def run_backfill(apps, connection=None):
    if connection is None:
        from django.db import connection
    Company = apps.get_model("core", "Company")
    IssuedDocument = apps.get_model("documents", "IssuedDocument")
    try:
        for company in Company.objects.all().order_by("id"):
            _set_company(connection, company.id)
            for kind, (subject_type, field) in MAPPING.items():
                IssuedDocument._base_manager.filter(
                    company_id=company.id, kind=kind, subject_type__isnull=True
                ).exclude(**{f"{field}__isnull": True}).update(
                    subject_type=subject_type, subject_id=F(field)
                )
    finally:
        _set_company(connection, None)


def run_reverse(apps, connection=None):
    if connection is None:
        from django.db import connection
    Company = apps.get_model("core", "Company")
    IssuedDocument = apps.get_model("documents", "IssuedDocument")
    try:
        for company in Company.objects.all().order_by("id"):
            _set_company(connection, company.id)
            for kind, (subject_type, field) in MAPPING.items():
                IssuedDocument._base_manager.filter(
                    company_id=company.id, kind=kind, subject_type=subject_type, subject_id=F(field)
                ).update(subject_type=None, subject_id=None)
    finally:
        _set_company(connection, None)


def forwards(apps, schema_editor):
    run_backfill(apps, schema_editor.connection)


def backwards(apps, schema_editor):
    run_reverse(apps, schema_editor.connection)


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0003_issued_document_subject"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
