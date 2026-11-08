# ruff: noqa: E501
"""Проверка RLS под РЕАЛЬНОЙ ролью logistix_app после миграций этапов 1.5-B и 1.5-C; выполняется внутри `manage.py shell`.

Подключение приложения (DATABASE_URL) - роль logistix_app (не суперпользователь, без BYPASSRLS).
Владелец (OWNER_URL) нужен только для сравнения «сколько строк существует на самом деле».
Проверяются таблицы forwarding_consignmentpoint (остановки) и forwarding_tripconsignment (участки):
ENABLE+FORCE RLS и политика, fail closed без контекста, чтение/запись своих строк, чужая компания не
видит/не меняет/не удаляет/не вставляет/не переносит, сброс контекста после ROLLBACK, savepoint,
повторного использования соединения. Батарея адаптивна: колонки шага проверяются, только если они есть.
Окружение: RLS_STEP, RLS_IDS (JSON), OWNER_URL. Результат - строка `RLS_REPORT={json}`; нарушение - исключение.
"""

import json
import os

import psycopg
from django.db import DatabaseError, connection, transaction

from apps.core.rls import tables_missing_rls, tenant_tables
from apps.core.tenancy import tenant_context

STEP = os.environ["RLS_STEP"]
IDS = json.loads(os.environ["RLS_IDS"])
OWNER_URL = os.environ["OWNER_URL"]
APP_URL = os.environ["DATABASE_URL"]
A, B = IDS["A"], IDS["B"]
PT, TC = "forwarding_consignmentpoint", "forwarding_tripconsignment"
REPORT = {"step": STEP, "checks": 0}


def ok(cond, message):
    REPORT["checks"] += 1
    if not cond:
        raise AssertionError(f"[{STEP}] {message}")


def raw(url):
    return psycopg.connect(url, autocommit=False)


def owner_rows(sql, params=()):
    with raw(OWNER_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def owner_scalar(sql, params=()):
    return owner_rows(sql, params)[0][0]


def columns(table):
    return {
        r[0]
        for r in owner_rows(
            "SELECT column_name FROM information_schema.columns WHERE table_name=%s", [table]
        )
    }


def guc(cur):
    cur.execute("SELECT current_setting('app.company_id', true)")
    return cur.fetchone()[0]


def expects_rls_error(fn, label):
    try:
        fn()
    except (psycopg.errors.InsufficientPrivilege, DatabaseError) as exc:
        ok("row-level security" in str(exc), f"{label}: ожидалась ошибка RLS, получено {exc}")
        return
    ok(False, f"{label}: операция должна быть отклонена RLS")


COLS = {PT: columns(PT), TC: columns(TC)}
REPORT.update(
    has_seq="seq" in COLS[PT],
    has_unique_seq=bool(
        owner_rows("SELECT 1 FROM pg_constraint WHERE conname='point_consignment_seq_uniq'")
    ),
    has_legs="from_stop_id" in COLS[TC],
)


def point_insert(company, consignment):
    cols = [
        "company_id",
        "consignment_id",
        "kind",
        "window_from",
        "city",
        "street",
        "contact",
        "postal_code",
        "note",
    ]
    vals = [company, consignment, "load", "2026-06-01T00:00:00Z", "rls", "", "", "", ""]
    if "seq" in COLS[PT]:
        cols.append("seq")
        vals.append(1)
    if "status" in COLS[PT]:
        cols.append("status")
        vals.append("planned")
    marks = ", ".join(["%s"] * len(cols))
    return f"INSERT INTO {PT} ({', '.join(cols)}) VALUES ({marks}) RETURNING id", vals


def leg_insert(company, trip, consignment):
    cols = ["company_id", "trip_id", "consignment_id"]
    vals = [company, trip, consignment]
    if "leg_seq" in COLS[TC]:
        cols.append("leg_seq")
        vals.append(1)
    if "status" in COLS[TC]:
        cols.append("status")
        vals.append("planned")
    marks = ", ".join(["%s"] * len(cols))
    return f"INSERT INTO {TC} ({', '.join(cols)}) VALUES ({marks}) RETURNING id", vals


def make_insert(table, ids):
    if table == PT:
        return point_insert(ids["company"], ids["probe_cargo"])
    return leg_insert(ids["company"], ids["probe_trip"], ids["probe_cargo"])


TOUCH = {PT: "note = 'x'", TC: "consignment_id = consignment_id"}

# --- 0. роль и покрытие --------------------------------------------------------------------
app = raw(APP_URL)
with app.cursor() as cur:
    cur.execute(
        "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
    )
    who = cur.fetchone()
app.rollback()
ok(who == ("logistix_app", False, False), f"роль приложения {who}")
flags = {
    r[0]: (r[1], r[2])
    for r in owner_rows(
        "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid "
        "WHERE n.nspname='public' AND c.relkind='r' AND a.attname='company_id' AND NOT a.attisdropped"
    )
}
pols = {
    r[0]: r
    for r in owner_rows(
        "SELECT tablename, qual, with_check FROM pg_policies "
        "WHERE schemaname='public' AND policyname='tenant_isolation' AND cmd='ALL'"
    )
}
for t in (PT, TC):
    ok(flags.get(t) == (True, True), f"{t}: ENABLE+FORCE RLS {flags.get(t)}")
    ok(
        t in pols and "app.company_id" in pols[t][1] and "app.company_id" in pols[t][2],
        f"{t}: политика USING + WITH CHECK",
    )
for t in tenant_tables():
    if t in flags:
        ok(flags[t] == (True, True), f"{t}: ENABLE+FORCE RLS {flags[t]}")
REPORT["tables"] = len(flags)
# таблицы более поздних этапов (D-E) в состоянии «до этапа» ещё не созданы: проверяются существующие
missing = [
    t
    for t in tables_missing_rls()
    if owner_rows("SELECT 1 FROM information_schema.tables WHERE table_name=%s", [t])
]
ok(missing == [], f"tables_missing_rls() пуст среди существующих таблиц: {missing}")

# --- 1-2. fail closed, свои данные, чужие недоступны --------------------------------------------
for table in (PT, TC):
    total = owner_scalar(f"SELECT count(*) FROM {table}")
    own = {
        k: owner_scalar(f"SELECT count(*) FROM {table} WHERE company_id=%s", [ids["company"]])
        for k, ids in (("A", A), ("B", B))
    }
    ok(
        own["A"] > 0 and own["B"] > 0 and own["A"] + own["B"] == total,
        f"{table}: у обеих компаний есть данные {own}",
    )
    with app.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")
        ok(cur.fetchone()[0] == 0, f"{table}: без контекста строк не видно")
        cur.execute("SELECT set_config('app.company_id', '', false)")
        cur.execute(f"SELECT count(*) FROM {table}")
        ok(cur.fetchone()[0] == 0, f"{table}: с пустым контекстом строк не видно")
        cur.execute(f"UPDATE {table} SET {TOUCH[table]}")
        ok(cur.rowcount == 0, f"{table}: без контекста нечего обновлять")
        cur.execute(f"DELETE FROM {table}")
        ok(cur.rowcount == 0, f"{table}: без контекста нечего удалять")
    app.rollback()
    sql, params = make_insert(table, A)
    expects_rls_error(lambda: app.cursor().execute(sql, params), f"{table}: вставка без контекста")
    app.rollback()
    with app.cursor() as cur:
        for key, ids, other in (("A", A, B), ("B", B, A)):
            cur.execute("SELECT set_config('app.company_id', %s, false)", [str(ids["company"])])
            cur.execute(f"SELECT DISTINCT company_id FROM {table}")
            ok(cur.fetchall() == [(ids["company"],)], f"{table}: {key} видит только свои строки")
            cur.execute(f"SELECT count(*) FROM {table}")
            ok(cur.fetchone()[0] == own[key], f"{table}: {key} видит все свои {own[key]} строк")
            cur.execute(f"SELECT count(*) FROM {table} WHERE company_id=%s", [other["company"]])
            ok(cur.fetchone()[0] == 0, f"{table}: {key} не видит чужие строки")
            cur.execute(
                f"UPDATE {table} SET {TOUCH[table]} WHERE company_id=%s", [other["company"]]
            )
            ok(cur.rowcount == 0, f"{table}: {key} не меняет чужие строки")
            cur.execute(f"DELETE FROM {table} WHERE company_id=%s", [other["company"]])
            ok(cur.rowcount == 0, f"{table}: {key} не удаляет чужие строки")
    app.rollback()
    # вставка строки чужой компании из своего контекста отвергается
    for ids, other in ((A, B), (B, A)):
        sql, params = make_insert(table, other)

        def foreign_insert(ids=ids, sql=sql, params=params):
            with raw(APP_URL) as conn, conn.cursor() as cur:
                cur.execute("SELECT set_config('app.company_id', %s, false)", [str(ids["company"])])
                cur.execute(sql, params)

        expects_rls_error(foreign_insert, f"{table}: вставка строки чужой компании")

    # запись своих строк через Django (tenant_context + синхронизация GUC)
    def run(sql, params=()):
        with connection.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() if cur.description else cur.rowcount

    ok(run("SELECT current_user")[0][0] == "logistix_app", "Django подключён ролью приложения")
    created = {}
    for key, ids in (("A", A), ("B", B)):
        with tenant_context(ids["company"]), transaction.atomic():
            sql, params = make_insert(table, ids)
            created[key] = run(sql, params)[0][0]
            ok(
                run(f"UPDATE {table} SET {TOUCH[table]} WHERE id=%s", [created[key]]) == 1,
                f"{table}: {key} обновляет свою строку",
            )
            ok(
                run(f"SELECT count(*) FROM {table} WHERE id=%s", [created[key]])[0][0] == 1,
                f"{table}: {key} читает записанное",
            )
    with tenant_context(B["company"]):
        ok(
            run(f"SELECT count(*) FROM {table} WHERE id=%s", [created["A"]])[0][0] == 0,
            f"{table}: B не видит строку A",
        )
        ok(
            run(f"UPDATE {table} SET {TOUCH[table]} WHERE id=%s", [created["A"]]) == 0,
            f"{table}: B не меняет строку A",
        )
        ok(
            run(f"DELETE FROM {table} WHERE id=%s", [created["A"]]) == 0,
            f"{table}: B не удаляет строку A",
        )

        def move_to_a(table=table, row=created["B"]):
            with transaction.atomic():
                run(f"UPDATE {table} SET company_id=%s WHERE id=%s", [A["company"], row])

        expects_rls_error(move_to_a, f"{table}: B переносит свою строку в A")
    for key, ids in (("A", A), ("B", B)):  # возврат к исходному состоянию
        with tenant_context(ids["company"]):
            ok(
                run(f"DELETE FROM {table} WHERE id=%s", [created[key]]) == 1,
                f"{table}: {key}: проба удалена",
            )
    ok(
        owner_scalar(f"SELECT count(*) FROM {table}") == total,
        f"{table}: данные вернулись к исходным",
    )

    # --- сброс контекста: ROLLBACK, savepoint, откат Django, новое соединение ---------------------
    app = raw(APP_URL)
    with app.cursor() as cur:
        cur.execute("SELECT set_config('app.company_id', %s, false)", [str(A["company"])])
        ok(guc(cur) == str(A["company"]), "контекст установлен")
        app.rollback()
        ok(guc(cur) in (None, ""), f"{table}: после ROLLBACK контекст не «подвешен»")
        cur.execute(f"SELECT count(*) FROM {table}")
        ok(cur.fetchone()[0] == 0, f"{table}: после ROLLBACK строки не видны")
        app.rollback()
    with app.cursor() as cur:
        cur.execute("SELECT set_config('app.company_id', %s, false)", [str(A["company"])])
        app.commit()
        cur.execute("SAVEPOINT s1")
        cur.execute("SELECT set_config('app.company_id', %s, false)", [str(B["company"])])
        cur.execute("ROLLBACK TO SAVEPOINT s1")
        ok(guc(cur) == str(A["company"]), "после ROLLBACK TO SAVEPOINT вернулся контекст A")
        app.rollback()
        cur.execute("SELECT set_config('app.company_id', '', false)")
        app.commit()
    app.close()

    class Boom(Exception):
        pass

    try:
        with tenant_context(A["company"]), transaction.atomic():
            sql, params = make_insert(table, A)
            run(sql, params)
            raise Boom
    except Boom:
        pass
    ok(
        run("SELECT current_setting('app.company_id', true)")[0][0] in (None, ""),
        f"{table}: после отката Django контекст пуст",
    )
    ok(
        owner_scalar(f"SELECT count(*) FROM {table}") == total,
        f"{table}: откат записи не оставил следов",
    )
    connection.close()
    ok(
        run(f"SELECT count(*) FROM {table}")[0][0] == 0,
        f"{table}: новое соединение: контекста нет, строк не видно",
    )
    app = raw(APP_URL)

app.close()
print("RLS_REPORT=" + json.dumps(REPORT, ensure_ascii=False))
