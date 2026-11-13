"""Ремонт схемы: столбец forwarding_contract.document_id (связь договора с выданным документом).

Зачем: на демо-БД применилась первая редакция 0017 (до появления Contract.document), поэтому
столбца там нет. Что делает: добавляет столбец с внешним ключом и индексом ТОЛЬКО если его нет;
на новой БД это пустая операция. Ничего не удаляет. Старый столбец documents_issueddocument.contract_id
(из снятой редакции documents.0005) не трогается. Состояние моделей не меняется (поле уже в 0017).
"""

from django.db import migrations


def forwards(apps, schema_editor):
    connection = schema_editor.connection
    Contract = apps.get_model("forwarding", "Contract")
    field = Contract._meta.get_field("document")
    with connection.cursor() as cursor:
        columns = {
            c.name for c in connection.introspection.get_table_description(cursor, Contract._meta.db_table)
        }
    if field.column in columns:
        return
    schema_editor.add_field(Contract, field)


class Migration(migrations.Migration):
    dependencies = [("forwarding", "0018_requisites_contracts_backfill")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
