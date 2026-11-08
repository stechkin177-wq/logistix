# ruff: noqa: E501
"""RLS и миграции на данных этапов 1.5-D (передачи, события, права) и 1.5-E под РЕАЛЬНОЙ ролью logistix_app, пошагово.

Основная БД и демо-БД не затрагиваются: временная БД, роль logistix_app создаётся настоящим
deploy/db-init.sql (NOSUPERUSER NOBYPASSRLS). Состояние ДО этапа: все миграции применены, засеяны две
компании с данными прежнего вида (грузы с точками и остановкой передачи, рейсы разных статусов,
участки), затем откат до forwarding 0012 и core 0018 (это само по себе проверка обратимости). Далее
миграции ПОШАГОВО (STEPS); после КАЖДОГО шага батарея rls_battery_stage_DE.py выполняется под ролью
приложения, а данные шага сверяются с ожидаемыми: location_status/current_stop (0014), право
consignments.transfer ролям (core 0019), прочие данные не меняются. Затем откат всех шагов без потерь,
повторное применение, мутационная проверка (без FORCE RLS батарея падает). Код возврата 0 - всё пройдено.
"""

import json
import os
import sys

import psycopg
from task_1_4_1_common import (
    APP_PASSWORD,
    APP_ROLE,
    BACKEND,
    DEFAULT_URL,
    TempDatabase,
    apply_db_init,
    manage,
    with_user,
)
from verify_rls_task_1_4_1 import load_module, owner_force_probe

SEED = """
import json
from datetime import datetime, timezone
from apps.core.handbooks.models import HandbookValue
from apps.core.models import User
from apps.core.services import create_company_with_defaults
from apps.core.tenancy import tenant_context
from apps.forwarding.models import Carrier, Client, Consignment, ConsignmentPoint, Trip, TripConsignment
from apps.forwarding.orders.services import create_order
from apps.forwarding.trips.services import create_trip

T = datetime(2026, 6, 2, 9, 0, tzinfo=timezone.utc)
def stops(kinds):
    return [{"kind": k, "window_from": T, "city": f"Город {i}"} for i, k in enumerate(kinds, 1)]
def cargo(name, kinds=("load", "unload")):
    return {"name": name, "weight_kg": 1000, "volume_m3": 10, "pallets": 5, "stops": stops(kinds)}
out = {}
for key in ("A", "B"):
    user = User.objects.create_user(email=f"{key.lower()}@stagede.kz", password="s3cret-pass-1")
    company = create_company_with_defaults(f"Компания {key}", user, ["forwarding"])
    with tenant_context(company.id):
        get = lambda h, c: HandbookValue.objects.get(handbook__code=h, code=c)
        client = Client.objects.create(name=f"Клиент {key}")
        carrier = Carrier.objects.create(name=f"Перевозчик {key}")
        order = create_order({"client": client, "consignments": [
            cargo("D"), cargo("P"), cargo("N"), cargo("T"),
            cargo("S", ("load", "transfer", "unload")), cargo("E", ("load", "transfer", "unload"))]}, user)
        cons = {c.name: c for c in Consignment.objects.filter(order=order)}
        def trip(name):
            return create_trip([cons[name].pk], carrier.pk, {}, user)
        td, tp, tt = trip("D"), trip("P"), trip("T")
        Trip.objects.filter(pk=td.pk).update(status=get("trip_status", "COMPLETED"))
        TripConsignment.objects.filter(trip=td).update(status="done")
        Trip.objects.filter(pk=tt.pk).update(status=get("trip_status", "IN_PROGRESS"))
        TripConsignment.objects.filter(trip=tt).update(status="in_progress")
        mid = ConsignmentPoint.objects.get(consignment=cons["S"], kind="transfer")
        ConsignmentPoint.objects.filter(pk=mid.pk).update(status="arrived")
        probe_stop = ConsignmentPoint.objects.get(consignment=cons["E"], kind="transfer")
        roles = {r.name: r.permissions for r in __import__("apps.core.models", fromlist=["Role"]).Role.objects.all()}
    out[key] = {"company": company.id, "probe_cargo": cons["E"].pk, "probe_stop": probe_stop.pk,
                "expect": {str(cons["D"].pk): ["delivered", None], str(cons["P"].pk): ["planned", None],
                           str(cons["N"].pk): ["planned", None], str(cons["T"].pk): ["in_transit", None],
                           str(cons["S"].pk): ["at_stop", mid.pk], str(cons["E"].pk): ["planned", None]},
                "cons": {n: c.pk for n, c in cons.items()}, "roles": sorted(roles)}
print("IDS=" + json.dumps(out))
"""

# (приложение, миграция, шаг)
STEPS = [
    ("forwarding", "0013", "D1-0013"),
    ("forwarding", "0014", "D1-0014"),
    ("core", "0019", "D3-core0019"),
]
ROLLBACK = [("forwarding", "0012"), ("core", "0018")]
HOLDERS = ("Администратор", "Менеджер", "Диспетчер")
PERM = "consignments.transfer"


def rows(url, sql, params=()):
    with psycopg.connect(url, autocommit=True) as conn:
        return conn.execute(sql, params).fetchall()


def scalar(url, sql, params=()):
    return rows(url, sql, params)[0][0]


def with_company(url, company_id, sql, params=()):
    """Запрос владельца в контексте компании (FORCE RLS действует и на владельца)."""
    with psycopg.connect(url, autocommit=False) as conn:
        conn.execute("SELECT set_config('app.company_id', %s, false)", [str(company_id)])
        cur = conn.execute(sql, params)
        data = cur.fetchall() if cur.description else cur.rowcount
        conn.commit()
        return data


def table_exists(url, table):
    return bool(rows(url, "SELECT 1 FROM information_schema.tables WHERE table_name=%s", [table]))


def columns(url, table):
    return {
        r[0]
        for r in rows(
            url, "SELECT column_name FROM information_schema.columns WHERE table_name=%s", [table]
        )
    }


def base_snapshot(url, ids):
    """Данные, которые шаги не должны менять: грузы (без новых колонок), остановки, участки, рейсы."""
    snap = {}
    for key in ("A", "B"):
        cid = ids[key]["company"]
        snap[key] = {
            "cons": with_company(
                url,
                cid,
                "SELECT id, order_id, name, weight_kg, volume_m3, pallets, status_id FROM forwarding_consignment WHERE company_id=%s ORDER BY id",
                [cid],
            ),
            "stops": with_company(
                url,
                cid,
                "SELECT id, consignment_id, kind, seq, status, city FROM forwarding_consignmentpoint WHERE company_id=%s ORDER BY id",
                [cid],
            ),
            "legs": with_company(
                url,
                cid,
                "SELECT id, trip_id, consignment_id, from_stop_id, to_stop_id, status FROM forwarding_tripconsignment WHERE company_id=%s ORDER BY id",
                [cid],
            ),
            "trips": with_company(
                url,
                cid,
                "SELECT id, number, status_id FROM forwarding_trip WHERE company_id=%s ORDER BY id",
                [cid],
            ),
        }
    return snap


def seed_new_tables(url, ids):
    """По строке в каждой новой таблице у каждой компании (батарее нужны данные у обеих)."""
    for key in ("A", "B"):
        cid, cons, stop = ids[key]["company"], ids[key]["probe_cargo"], ids[key]["probe_stop"]
        if table_exists(url, "forwarding_cargotransfer") and not with_company(
            url, cid, "SELECT 1 FROM forwarding_cargotransfer WHERE company_id=%s", [cid]
        ):
            with_company(
                url,
                cid,
                "INSERT INTO forwarding_cargotransfer (company_id, consignment_id, to_stop_id, transfer_kind, carrier_changed, transferred_at, status, source, note, created_at) VALUES (%s, %s, %s, 'to_storage', false, now(), 'confirmed', 'manual', 'seed', now())",
                [cid, cons, stop],
            )
        if table_exists(url, "forwarding_consignmentevent") and not with_company(
            url, cid, "SELECT 1 FROM forwarding_consignmentevent WHERE company_id=%s", [cid]
        ):
            with_company(
                url,
                cid,
                "INSERT INTO forwarding_consignmentevent (company_id, consignment_id, stop_id, event_type, occurred_at, source, note, created_at) VALUES (%s, %s, %s, 'arrived', now(), 'manual', 'seed', now())",
                [cid, cons, stop],
            )


def battery_step(label, owner_url, app_url, battery, ids, probe_module, reports):
    seed_new_tables(owner_url, ids)
    env = {"RLS_STEP": label, "RLS_IDS": json.dumps(ids), "OWNER_URL": owner_url}
    result = manage(app_url, "shell", stdin=battery, env_extra=env)
    report = json.loads(result.split("RLS_REPORT=")[1].splitlines()[0])
    report["force_probe_checks"] = owner_force_probe(owner_url, owner_url, probe_module)
    reports.append(report)
    print(
        f"OK {label}: таблиц компаний {report['tables']}, новые таблицы {report['tables_checked']}, под ролью logistix_app проверок {report['checks'] + report['force_probe_checks']}"
    )


def check_data(label, owner_url, ids, base):
    assert base_snapshot(owner_url, ids) == base, f"{label}: исходные данные изменились"
    has_loc = "location_status" in columns(owner_url, "forwarding_consignment")
    for key in ("A", "B"):
        cid = ids[key]["company"]
        if has_loc and label != "D1-0013":
            got = {
                str(i): [st, stop]
                for i, st, stop in with_company(
                    owner_url,
                    cid,
                    "SELECT id, location_status, current_stop_id FROM forwarding_consignment WHERE company_id=%s",
                    [cid],
                )
            }
            assert got == ids[key]["expect"], (
                f"{label} {key}: location_status {got} != {ids[key]['expect']}"
            )
        elif has_loc:
            got = {
                st
                for (st,) in with_company(
                    owner_url,
                    cid,
                    "SELECT location_status FROM forwarding_consignment WHERE company_id=%s",
                    [cid],
                )
            }
            assert got == {"planned"}, f"{label}: до заполнения planned у всех, получено {got}"
        # права ролей
        perms = {
            name: PERM in perms
            for name, perms in with_company(
                owner_url, cid, "SELECT name, permissions FROM core_role WHERE company_id=%s", [cid]
            )
        }
        if label == "D3-core0019" or label == "final":
            assert all(perms[r] for r in HOLDERS), f"{label} {key}: право у {perms}"
            assert not any(v for n, v in perms.items() if n not in HOLDERS), (
                f"{label} {key}: лишние права {perms}"
            )
        elif label in ("D1-0013", "D1-0014"):
            assert not any(perms.values()), f"{label} {key}: до миграции права ещё нет {perms}"


def main() -> int:
    base_url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    battery = (BACKEND / "scripts" / "rls_battery_stage_DE.py").read_text()
    reports = []
    with TempDatabase(base_url, "logistix_rlsDE") as db:
        owner_url = db.url
        apply_db_init(owner_url)
        app_url = with_user(owner_url, APP_ROLE, APP_PASSWORD)
        row = rows(
            owner_url,
            "SELECT rolsuper, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname=%s",
            [APP_ROLE],
        )[0]
        assert row == (False, False, True), f"роль {APP_ROLE}: {row}"
        manage(owner_url, "migrate", "--noinput")
        ids = json.loads(manage(owner_url, "shell", stdin=SEED).split("IDS=")[1].splitlines()[0])
        for app, name in ROLLBACK:  # состояние ДО этапа
            manage(owner_url, "migrate", app, name, "--noinput")
        assert not table_exists(owner_url, "forwarding_cargotransfer")
        assert "location_status" not in columns(owner_url, "forwarding_consignment")
        # право убираем у ролей: имитация компаний, созданных до этапа
        for key in ("A", "B"):
            with_company(
                owner_url,
                ids[key]["company"],
                "UPDATE core_role SET permissions = (SELECT COALESCE(jsonb_agg(p), '[]'::jsonb) FROM jsonb_array_elements(core_role.permissions) p WHERE p <> to_jsonb(%s::text)) WHERE company_id=%s",
                [PERM, ids[key]["company"]],
            )
        base = base_snapshot(owner_url, ids)
        probe_module = load_module(
            BACKEND / "apps" / "finance" / "migrations" / "0005_income_expense_ledger.py", "m0005"
        )
        battery_step("base", owner_url, app_url, battery, ids, probe_module, reports)

        for app, name, label in STEPS:  # прямой проход пошагово
            manage(owner_url, "migrate", app, name, "--noinput")
            check_data(label, owner_url, ids, base)
            battery_step(label, owner_url, app_url, battery, ids, probe_module, reports)

        for table in (
            "forwarding_cargotransfer",
            "forwarding_consignmentevent",
        ):  # мутационная проверка
            with psycopg.connect(owner_url, autocommit=True) as conn:
                conn.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            try:
                battery_step("мутация", owner_url, app_url, battery, ids, probe_module, [])
                raise AssertionError(f"батарея не заметила снятие FORCE RLS у {table}")
            except RuntimeError as exc:
                assert "ENABLE+FORCE RLS" in str(exc), exc
            finally:
                with psycopg.connect(owner_url, autocommit=True) as conn:
                    conn.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        print("OK мутация: при снятии FORCE RLS батарея падает (обе таблицы)")

        # откат: forwarding до 0012 (таблицы передач/событий и колонки груза исчезают, остальное цело)
        manage(owner_url, "migrate", "forwarding", "0012", "--noinput")
        assert not table_exists(owner_url, "forwarding_cargotransfer") and not table_exists(
            owner_url, "forwarding_consignmentevent"
        )
        assert base_snapshot(owner_url, ids) == base, "откат: данные потеряны или изменены"
        battery_step("откат-0013", owner_url, app_url, battery, ids, probe_module, reports)

        manage(owner_url, "migrate", "--noinput")  # повторное применение на тех же данных
        check_data("final", owner_url, ids, base)
        battery_step("final", owner_url, app_url, battery, ids, probe_module, reports)
        manage(owner_url, "migrate", "--noinput")  # повтор: ничего не применяется
        check_data("final", owner_url, ids, base)
        out = manage(
            owner_url,
            "shell",
            stdin="from apps.core.rls import tables_missing_rls\nprint('MISSING=%r' % tables_missing_rls())",
        )
        assert "MISSING=[]" in out, out
        manage(owner_url, "makemigrations", "--check", "--dry-run")
        print(
            "tables_missing_rls() == [] и makemigrations --check чисто после всех миграций этапов D и E"
        )
    total = sum(r["checks"] + r["force_probe_checks"] for r in reports)
    print(
        f"OK: этапы 1.5-D и 1.5-E: RLS под ролью {APP_ROLE} и миграции на данных проверены (шагов {len(reports)}, проверок {total})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
