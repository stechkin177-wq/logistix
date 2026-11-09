# ruff: noqa: E501
"""RLS и миграции на данных этапов 1.5-B (остановки) и 1.5-C (участки) под РЕАЛЬНОЙ ролью logistix_app, пошагово.

Основная БД и демо-БД не затрагиваются: временная БД, роль logistix_app создаётся настоящим
deploy/db-init.sql (NOSUPERUSER NOBYPASSRLS). Состояние ДО этапа получается так: все миграции
применены, засеяны две компании с данными прежнего вида (грузы с погрузкой и выгрузкой, груз без
точек, груз с одной точкой, рейсы всех статусов, сборный рейс, перегруз - один груз в трёх
рейсах), затем forwarding откатывается до 0007 (это само по себе проверка обратимости). Далее
миграции идут ПОШАГОВО: forwarding 0008 (схема остановок), 0009 (seq), 0010 (ограничения seq),
0011 (схема участков), 0012 (заполнение участков). После КАЖДОГО шага батарея
rls_battery_stage_BC.py выполняется под ролью приложения; проверяются и данные шага (seq, from_stop/
to_stop, status), ничего не теряется. Затем откат всех шагов до 0007 без потерь, защита отката
(промежуточная остановка не позволяет откатить 0008), повторное применение и мутационная проверка
(без FORCE RLS батарея падает). Код возврата 0 - всё пройдено.
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
    manage_result,
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
def cargo(name, w=1000):
    return {"name": name, "weight_kg": w, "volume_m3": 10, "pallets": 5, "points": [
        {"kind": "load", "window_from": T, "city": "Шымкент", "street": "ул. 1"},
        {"kind": "unload", "window_from": T, "city": "Алматы", "street": "ул. 2"}]}
out = {}
for key in ("A", "B"):
    user = User.objects.create_user_schema_agnostic(email=f"{key.lower()}@stagebc.kz", password="s3cret-pass-1")
    company = create_company_with_defaults(f"Компания {key}", user, ["forwarding"])
    with tenant_context(company.id):
        get = lambda h, c: HandbookValue.objects.get(handbook__code=h, code=c)
        client = Client.objects.create(name=f"Клиент {key}")
        client2 = Client.objects.create(name=f"Клиент 2 {key}")
        carrier = Carrier.objects.create(name=f"Перевозчик {key}")
        order1 = create_order({"client": client, "consignments": [cargo("K1"), cargo("K2"), cargo("K3"), cargo("K5"), cargo("E")]}, user)
        order2 = create_order({"client": client2, "consignments": [cargo("K4")]}, user)
        cons = {c.name: c for c in Consignment.objects.filter(order__in=[order1, order2])}
        ConsignmentPoint.objects.filter(consignment=cons["K3"]).delete()                 # груз без точек
        ConsignmentPoint.objects.filter(consignment=cons["E"]).delete()                  # груз для проб RLS
        ConsignmentPoint.objects.filter(consignment=cons["K5"], kind="unload").delete()  # груз с одной точкой
        def trip(names):
            return create_trip([cons[n].pk for n in names], carrier.pk, {}, user)
        trips = {
            "planned": trip(["K1", "K2"]), "done": trip(["K1"]), "cancelled": trip(["K2"]),
            "nopoints": trip(["K3"]), "onepoint": trip(["K5"]), "cons": trip(["K4", "K1"]),
        }
        Trip.objects.filter(pk=trips["done"].pk).update(status=get("trip_status", "COMPLETED"))
        Trip.objects.filter(pk=trips["cancelled"].pk).update(status=get("trip_status", "CANCELLED"))
        probe_trip = Trip.objects.create(number=f"PROBE-{key}", carrier=carrier, currency=get("currency", "KZT"), status=get("trip_status", "PLANNED"))
        # ожидаемые участки после миграции: по грузам с парой load/unload, статус по коду рейса
        status_by_trip = {trips["done"].pk: "done", trips["cancelled"].pk: "cancelled"}
        expect = {}
        for link in TripConsignment.objects.all():
            pts = list(ConsignmentPoint.objects.filter(consignment_id=link.consignment_id).order_by("seq", "id"))
            load = next((p for p in pts if p.kind == "load"), None)
            unload = next((p for p in reversed(pts) if p.kind == "unload"), None)
            pair = (load.pk, unload.pk) if load and unload else (None, None)
            expect[f"{link.trip_id}:{link.consignment_id}"] = [pair[0], pair[1], status_by_trip.get(link.trip_id, "planned")]
    out[key] = {"company": company.id, "expect": expect, "probe_cargo": cons["E"].pk, "probe_trip": probe_trip.pk,
                "cons": {n: c.pk for n, c in cons.items()}, "trips": {n: t.pk for n, t in trips.items()}}
print("IDS=" + json.dumps(out))
"""

# (приложение, миграция, шаг)
STEPS = [
    ("forwarding", "0008", "B1-0008"),
    ("forwarding", "0009", "B1-0009"),
    ("forwarding", "0010", "B1-0010"),
    ("forwarding", "0011", "C1-0011"),
    ("forwarding", "0012", "C1-0012"),
]
POINT_LEGACY = (
    "id, company_id, consignment_id, kind, window_from, window_to, country_id, city, street, method_id, "
    "contact, postal_code, lat, lng, note"
)


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


def columns(url, table):
    return {
        r[0]
        for r in rows(
            url, "SELECT column_name FROM information_schema.columns WHERE table_name=%s", [table]
        )
    }


def constraint(url, name):
    return rows(url, "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname=%s", [name])


def points_by_company(url, ids, cols):
    return {
        key: with_company(
            url,
            ids[key]["company"],
            f"SELECT {cols} FROM forwarding_consignmentpoint WHERE company_id=%s ORDER BY id",
            [ids[key]["company"]],
        )
        for key in ("A", "B")
    }


def links_by_company(url, ids, cols="id, company_id, trip_id, consignment_id"):
    return {
        key: with_company(
            url,
            ids[key]["company"],
            f"SELECT {cols} FROM forwarding_tripconsignment WHERE company_id=%s ORDER BY id",
            [ids[key]["company"]],
        )
        for key in ("A", "B")
    }


def battery_step(label, owner_url, app_url, battery, ids, probe_module, reports):
    env = {"RLS_STEP": label, "RLS_IDS": json.dumps(ids), "OWNER_URL": owner_url}
    result = manage(app_url, "shell", stdin=battery, env_extra=env)
    report = json.loads(result.split("RLS_REPORT=")[1].splitlines()[0])
    report["force_probe_checks"] = owner_force_probe(owner_url, owner_url, probe_module)
    reports.append(report)
    print(
        f"OK {label}: таблиц компаний {report['tables']}, под ролью logistix_app проверок "
        f"{report['checks'] + report['force_probe_checks']} (seq={report['has_seq']}, "
        f"unique(seq)={report['has_unique_seq']}, участки={report['has_legs']})"
    )


def check_data(label, owner_url, ids, base_points, base_links):
    """Проверки данных шага (владелец БД, в контексте каждой компании)."""
    assert points_by_company(owner_url, ids, POINT_LEGACY) == base_points, (
        f"{label}: исходные поля точек изменились"
    )
    assert links_by_company(owner_url, ids) == base_links, (
        f"{label}: связи рейс-груз изменились или потеряны"
    )
    has_seq = "seq" in columns(owner_url, "forwarding_consignmentpoint")
    if has_seq:
        for key in ("A", "B"):
            cons = ids[key]["cons"]
            seqs = {}
            for pid, cid, kind, seq in with_company(
                owner_url,
                ids[key]["company"],
                "SELECT id, consignment_id, kind, seq FROM forwarding_consignmentpoint WHERE company_id=%s ORDER BY id",
                [ids[key]["company"]],
            ):
                seqs.setdefault(cid, {})[kind] = seq
            if label == "B1-0008":
                assert all(s == 1 for d in seqs.values() for s in d.values()), (
                    f"{key}: до заполнения seq=1 у всех"
                )
            else:
                for name in ("K1", "K2", "K4"):
                    assert seqs[cons[name]] == {"load": 1, "unload": 2}, (
                        key,
                        name,
                        seqs[cons[name]],
                    )
                assert seqs[cons["K5"]] == {"load": 1}, (
                    key,
                    seqs[cons["K5"]],
                )  # одна точка - seq=1
                assert cons["K3"] not in seqs and cons["E"] not in seqs
    # ограничения точек
    kind_def = " ".join(r[0] for r in constraint(owner_url, "point_kind_valid"))
    if has_seq:
        assert "transit" in kind_def and "customs" in kind_def, kind_def
        assert not constraint(owner_url, "point_consignment_kind_uniq"), (
            "уникальность (груз, вид) снята"
        )
    else:
        assert "transit" not in kind_def and constraint(owner_url, "point_consignment_kind_uniq")
    assert (
        bool(constraint(owner_url, "point_consignment_seq_uniq"))
        == (label not in ("B1-0008", "B1-0009"))
        or not has_seq
    )
    if label in ("B1-0010", "C1-0011", "C1-0012", "final"):
        assert constraint(owner_url, "point_consignment_seq_uniq") and constraint(
            owner_url, "point_seq_gte_1"
        )
    # участки
    has_legs = "from_stop_id" in columns(owner_url, "forwarding_tripconsignment")
    if has_legs:
        assert not constraint(owner_url, "tripcons_trip_cons_uniq"), "старая уникальность заменена"
        for name in ("tripcons_trip_cons_leg_uniq", "tripcons_stops_both_or_none"):
            assert constraint(owner_url, name), name
        # частичная уникальность - уникальный индекс, а не constraint
        partial = rows(
            owner_url,
            "SELECT indexdef FROM pg_indexes WHERE indexname='tripcons_trip_cons_whole_uniq'",
        )
        assert partial and "WHERE" in partial[0][0], partial
        for key in ("A", "B"):
            data = {
                f"{t}:{c}": [f, to, st]
                for t, c, f, to, st, ls in with_company(
                    owner_url,
                    ids[key]["company"],
                    "SELECT trip_id, consignment_id, from_stop_id, to_stop_id, status, leg_seq FROM forwarding_tripconsignment WHERE company_id=%s",
                    [ids[key]["company"]],
                )
            }
            if label == "C1-0011":
                assert all(v == [None, None, "planned"] for v in data.values()), (
                    "до заполнения: пусто и planned"
                )
            else:
                assert data == ids[key]["expect"], (
                    f"{key}: участки {data} != ожидаемым {ids[key]['expect']}"
                )
                assert all(
                    ls == 1
                    for (ls,) in with_company(
                        owner_url,
                        ids[key]["company"],
                        "SELECT leg_seq FROM forwarding_tripconsignment WHERE company_id=%s",
                        [ids[key]["company"]],
                    )
                )
    else:
        assert constraint(owner_url, "tripcons_trip_cons_uniq")


def main() -> int:
    base_url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    battery = (BACKEND / "scripts" / "rls_battery_stage_BC.py").read_text()
    reports = []
    with TempDatabase(base_url, "logistix_rlsBC") as db:
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
        out = manage(owner_url, "shell", stdin=SEED)
        ids = json.loads(out.split("IDS=")[1].splitlines()[0])
        manage(owner_url, "migrate", "forwarding", "0007", "--noinput")  # состояние ДО этапа
        assert "seq" not in columns(owner_url, "forwarding_consignmentpoint")
        assert "from_stop_id" not in columns(owner_url, "forwarding_tripconsignment")
        base_points = points_by_company(owner_url, ids, POINT_LEGACY)
        base_links = links_by_company(owner_url, ids)
        n_points = sum(len(v) for v in base_points.values())
        n_links = sum(len(v) for v in base_links.values())
        assert n_links == 2 * 8 and n_points == 2 * 7, (
            n_links,
            n_points,
        )  # 8 связей и 7 точек на компанию
        probe_module = load_module(
            BACKEND / "apps" / "finance" / "migrations" / "0005_income_expense_ledger.py", "m0005"
        )
        battery_step("base", owner_url, app_url, battery, ids, probe_module, reports)

        # --- прямой проход пошагово ---
        for app, name, label in STEPS:
            manage(owner_url, "migrate", app, name, "--noinput")
            check_data(label, owner_url, ids, base_points, base_links)
            battery_step(label, owner_url, app_url, battery, ids, probe_module, reports)

        # --- мутационная проверка: без FORCE RLS батарея обязана упасть ---
        for table in ("forwarding_tripconsignment", "forwarding_consignmentpoint"):
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

        # --- защита отката: промежуточная остановка не вмещается в прежнюю схему ---
        key = "A"
        cid = ids[key]["probe_cargo"]
        pid = with_company(
            owner_url,
            ids[key]["company"],
            "INSERT INTO forwarding_consignmentpoint (company_id, consignment_id, kind, seq, status, window_from, city, street, contact, postal_code, note) "
            "VALUES (%s, %s, 'transit', 1, 'planned', now(), 'Проба', '', '', '', '') RETURNING id",
            [ids[key]["company"], cid],
        )[0][0]
        done = manage_result(owner_url, "migrate", "forwarding", "0007", "--noinput")
        assert done.returncode != 0 and "forwarding.0008" in (done.stdout + done.stderr), (
            done.stdout + done.stderr
        )
        assert (
            scalar(
                owner_url,
                "SELECT count(*) FROM information_schema.columns WHERE table_name='forwarding_consignmentpoint' AND column_name='seq'",
            )
            == 1
        )
        assert (
            with_company(
                owner_url,
                ids[key]["company"],
                "SELECT count(*) FROM forwarding_consignmentpoint WHERE id=%s",
                [pid],
            )[0][0]
            == 1
        ), "данные не удалены"
        print("OK защита отката: промежуточную остановку откат 0008 не уничтожает")
        with_company(
            owner_url,
            ids[key]["company"],
            "DELETE FROM forwarding_consignmentpoint WHERE id=%s",
            [pid],
        )
        manage(owner_url, "migrate", "forwarding", "--noinput")  # вернулись в конечное состояние

        # --- откат всех шагов: данные без потерь ---
        for app, name, label in reversed(STEPS):
            target = {
                "0012": "0011",
                "0011": "0010",
                "0010": "0009",
                "0009": "0008",
                "0008": "0007",
            }[name]
            manage(owner_url, "migrate", app, target, "--noinput")
            assert links_by_company(owner_url, ids) == base_links, f"откат {name}: связи потеряны"
            assert points_by_company(owner_url, ids, POINT_LEGACY) == base_points, (
                f"откат {name}: точки изменились"
            )
            battery_step(f"откат-{name}", owner_url, app_url, battery, ids, probe_module, reports)
        assert not constraint(owner_url, "point_consignment_seq_uniq") and constraint(
            owner_url, "point_consignment_kind_uniq"
        )
        assert constraint(owner_url, "tripcons_trip_cons_uniq")

        # --- повторное применение на тех же данных ---
        manage(owner_url, "migrate", "--noinput")
        check_data("final", owner_url, ids, base_points, base_links)
        battery_step("final", owner_url, app_url, battery, ids, probe_module, reports)
        manage(owner_url, "migrate", "--noinput")  # повтор: ничего не применяется
        check_data("final", owner_url, ids, base_points, base_links)
        out = manage(
            owner_url,
            "shell",
            stdin="from apps.core.rls import tables_missing_rls\nprint('MISSING=%r' % tables_missing_rls())",
        )
        assert "MISSING=[]" in out, out
        manage(owner_url, "makemigrations", "--check", "--dry-run")
        print(
            "tables_missing_rls() == [] и makemigrations --check чисто после всех миграций этапов B и C"
        )
    total = sum(r["checks"] + r["force_probe_checks"] for r in reports)
    print(
        f"OK: этапы 1.5-B и 1.5-C: RLS под ролью {APP_ROLE} и миграции на данных проверены (шагов {len(reports)}, проверок {total})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
