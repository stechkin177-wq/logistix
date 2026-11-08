"""Этап 1.5-D1: начальное значение Consignment.location_status у существующих грузов.

Журнал событий не создаётся (он начинается с момента включения), статус вычисляется по уже
имеющимся данным: последняя остановка выполнена или участок, заканчивающийся на ней, завершён ->
delivered; остановка со статусом «прибыли» -> at_stop; выполненная остановка или участок в
пути/завершён -> in_transit; иначе planned. Идемпотентна, затрагивает только строки, где значение
отличается от вычисленного; данные других полей не меняются. Самодостаточна (код приложения не
импортируется). Откат - noop (колонки удаляет откат 0013).
"""

from django.db import migrations


def _set_company(connection, company_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.company_id', %s, false)", [str(company_id or "")])


def derive(stops, legs):
    """(location_status, current_stop_id) по остановкам (по seq) и участкам груза."""
    if not stops:
        done = any(leg["status"] == "done" for leg in legs)
        if done:
            return "delivered", None
        return (
            "in_transit" if any(leg["status"] == "in_progress" for leg in legs) else "planned"
        ), None
    last = stops[-1]
    if last["status"] == "done":
        return "delivered", None
    for leg in legs:
        if leg["status"] != "done":
            continue
        if leg["to"] is None or leg["to"] == last["id"]:
            return "delivered", None
    arrived = [s for s in stops if s["status"] == "arrived"]
    if arrived:
        return "at_stop", arrived[-1]["id"]
    if any(s["status"] == "done" for s in stops) or any(
        leg["status"] in ("in_progress", "done") for leg in legs
    ):
        return "in_transit", None
    return "planned", None


def run_backfill(apps, connection):
    Company = apps.get_model("core", "Company")
    Consignment = apps.get_model("forwarding", "Consignment")
    Point = apps.get_model("forwarding", "ConsignmentPoint")
    Link = apps.get_model("forwarding", "TripConsignment")
    changed = 0
    try:
        for company in Company.objects.all().order_by("id"):
            _set_company(connection, company.id)
            stops_by, legs_by = {}, {}
            for p in Point._base_manager.filter(company_id=company.id).order_by("seq", "id"):
                stops_by.setdefault(p.consignment_id, []).append({"id": p.id, "status": p.status})
            for link in Link._base_manager.filter(company_id=company.id).exclude(
                status="cancelled"
            ):
                legs_by.setdefault(link.consignment_id, []).append(
                    {"status": link.status, "to": link.to_stop_id}
                )
            for c in Consignment._base_manager.filter(company_id=company.id):
                status, stop_id = derive(stops_by.get(c.id, []), legs_by.get(c.id, []))
                if (c.location_status, c.current_stop_id) != (status, stop_id):
                    Consignment._base_manager.filter(pk=c.pk).update(
                        location_status=status, current_stop_id=stop_id
                    )
                    changed += 1
    finally:
        _set_company(connection, None)
    return changed


def forwards(apps, schema_editor):
    run_backfill(apps, schema_editor.connection)


class Migration(migrations.Migration):
    dependencies = [("forwarding", "0013_cargo_transfers_events")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
