"""Этап 1.5-C1, данные: участки существующих связей рейс-груз.

* from_stop = первая остановка погрузки груза (наименьший seq), to_stop = последняя остановка
  выгрузки (наибольший seq); если у груза нет такой пары (нет точек или from.seq >= to.seq),
  обе остановки остаются пустыми;
* status: рейс с системным кодом COMPLETED -> done, CANCELLED -> cancelled, иначе planned
  (по коду статуса рейса, не по названию);
* leg_seq = 1, доли пусты (весь груз).
Идемпотентна: заполняются только участки без остановок, статус пересчитывается детерминированно
только для planned. Ничего не удаляется. Откат - без действий (поля удаляет откат 0011).
Самодостаточна (код приложения не импортируется); RLS: контекст компании на время обработки.
"""

from django.db import migrations

LEGS_SQL = """
UPDATE forwarding_tripconsignment tc
SET from_stop_id = s.from_id, to_stop_id = s.to_id
FROM (
    SELECT c.id AS consignment_id,
           (SELECT p.id FROM forwarding_consignmentpoint p
             WHERE p.consignment_id = c.id AND p.kind = 'load'
             ORDER BY p.seq, p.id LIMIT 1) AS from_id,
           (SELECT p.seq FROM forwarding_consignmentpoint p
             WHERE p.consignment_id = c.id AND p.kind = 'load'
             ORDER BY p.seq, p.id LIMIT 1) AS from_seq,
           (SELECT p.id FROM forwarding_consignmentpoint p
             WHERE p.consignment_id = c.id AND p.kind = 'unload'
             ORDER BY p.seq DESC, p.id DESC LIMIT 1) AS to_id,
           (SELECT p.seq FROM forwarding_consignmentpoint p
             WHERE p.consignment_id = c.id AND p.kind = 'unload'
             ORDER BY p.seq DESC, p.id DESC LIMIT 1) AS to_seq
    FROM forwarding_consignment c
    WHERE c.company_id = %s
) s
WHERE tc.company_id = %s
  AND tc.consignment_id = s.consignment_id
  AND tc.from_stop_id IS NULL AND tc.to_stop_id IS NULL
  AND s.from_id IS NOT NULL AND s.to_id IS NOT NULL AND s.from_seq < s.to_seq
"""

STATUS_SQL = """
UPDATE forwarding_tripconsignment tc
SET status = CASE h.code WHEN 'COMPLETED' THEN 'done' WHEN 'CANCELLED' THEN 'cancelled'
                         ELSE 'planned' END
FROM forwarding_trip t
JOIN core_handbookvalue h ON h.id = t.status_id
WHERE tc.company_id = %s AND tc.trip_id = t.id AND tc.status = 'planned'
  AND h.code IN ('COMPLETED', 'CANCELLED')
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
                cursor.execute(LEGS_SQL, [company.id, company.id])
                cursor.execute(STATUS_SQL, [company.id])
    finally:
        _set_company(connection, None)


class Migration(migrations.Migration):
    dependencies = [("forwarding", "0011_tripconsignment_legs"), ("core", "0018_manage_modules_permission")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
