"""Этап 1.5-B1, данные: seq существующих точек (load=1, unload=2; одна точка - seq=1).

По грузу: сначала погрузки, затем остальные виды, внутри - по id; номера 1..N. Ничего не
удаляется и не меняется, кроме seq. Идемпотентна (повтор даёт те же номера). Откат - без
действий: поле seq удаляется откатом 0008. Самодостаточна (код приложения не импортируется);
RLS: контекст компании выставляется на время обработки каждой компании.
"""

from django.db import migrations

FORWARD_SQL = """
UPDATE forwarding_consignmentpoint p
SET seq = s.rn
FROM (
    SELECT id, row_number() OVER (
        PARTITION BY consignment_id
        ORDER BY CASE kind WHEN 'load' THEN 0 WHEN 'unload' THEN 2 ELSE 1 END, id
    ) AS rn
    FROM forwarding_consignmentpoint
    WHERE company_id = %s
) s
WHERE p.id = s.id AND p.company_id = %s AND p.seq <> s.rn
"""


def _set_company(connection, company_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.company_id', %s, false)", [str(company_id or "")])


def forwards(apps, schema_editor):
    connection = schema_editor.connection
    Company = apps.get_model("core", "Company")
    try:
        for company in Company.objects.all().order_by("id"):
            _set_company(connection, company.id)
            with connection.cursor() as cursor:
                cursor.execute(FORWARD_SQL, [company.id, company.id])
    finally:
        _set_company(connection, None)


class Migration(migrations.Migration):
    dependencies = [("forwarding", "0008_stops_schema")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
