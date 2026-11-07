# ruff: noqa: E501
"""Проверка RLS под РЕАЛЬНОЙ ролью logistix_app для finance.0010 (снимки курса, FxRevaluation); выполняется внутри `manage.py shell`.

Подключение приложения (DATABASE_URL) - роль logistix_app (не суперпользователь, без BYPASSRLS).
Владелец (OWNER_URL) нужен только для сравнения «сколько строк существует на самом деле».
Окружение: RLS_STEP, RLS_IDS (JSON: компании, счета, оплаты, валюта), OWNER_URL.
Батарея адаптивна: колонки снимков и таблицы переоценки проверяются, только если они есть в схеме шага.
Результат - строка `RLS_REPORT={json}`; любое нарушение - исключение (код возврата не 0).
"""

import json
import os
from datetime import date

import psycopg
from django.db import DatabaseError, connection, transaction

from apps.core.rls import tenant_tables
from apps.core.tenancy import tenant_context

STEP = os.environ["RLS_STEP"]
IDS = json.loads(os.environ["RLS_IDS"])
OWNER_URL = os.environ["OWNER_URL"]
APP_URL = os.environ["DATABASE_URL"]
A, B = IDS["A"], IDS["B"]
REVAL, LINE = "finance_fxrevaluation", "finance_fxrevaluationline"
INVOICE, PAYMENT = "finance_invoice", "finance_payment"
REPORT = {"step": STEP, "checks": 0}


def ok(cond, message):
    REPORT["checks"] += 1
    if not cond:
        raise AssertionError(f"[{STEP}] {message}")


def raw(url):
    return psycopg.connect(url, autocommit=False)


def owner_scalar(sql, params=()):
    with raw(OWNER_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


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


def cols(table):
    with raw(OWNER_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name=%s", [table]
        )
        return {r[0] for r in cur.fetchall()}


HAS_SNAP = {"base_currency_id", "rate_to_base", "rate_to_base_date"} <= cols(INVOICE)
HAS_SNAP_PAY = {"base_currency_id", "rate_to_base", "rate_to_base_date"} <= cols(PAYMENT)
HAS_REVAL = bool(owner_scalar("SELECT count(*) FROM pg_class WHERE relname=%s", [REVAL]))
ok(HAS_SNAP == HAS_SNAP_PAY == HAS_REVAL, "колонки снимков и таблицы переоценки появляются вместе")
REPORT.update(has_snapshots=HAS_SNAP, has_revaluation_tables=HAS_REVAL)

# --- 0. роль и покрытие --------------------------------------------------------------------------
app = raw(APP_URL)
with app.cursor() as cur:
    cur.execute(
        "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
    )
    who = cur.fetchone()
app.rollback()
ok(who == ("logistix_app", False, False), f"роль приложения {who}")
with raw(OWNER_URL) as conn, conn.cursor() as cur:
    cur.execute(
        "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid "
        "WHERE n.nspname='public' AND c.relkind='r' AND a.attname='company_id' AND NOT a.attisdropped"
    )
    flags = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    cur.execute(
        "SELECT tablename, qual, with_check FROM pg_policies "
        "WHERE schemaname='public' AND policyname='tenant_isolation' AND cmd='ALL'"
    )
    pols = {r[0]: r for r in cur.fetchall()}
covered = [t for t in tenant_tables() if t in flags]
ok(len(covered) >= 20, f"таблиц компаний: {len(covered)}")
for t in covered:
    ok(flags[t] == (True, True), f"{t}: ENABLE+FORCE RLS {flags[t]}")
    ok(
        t in pols and "app.company_id" in pols[t][1] and "app.company_id" in pols[t][2],
        f"{t}: политика USING + WITH CHECK",
    )
for t in (INVOICE, PAYMENT, *((REVAL, LINE) if HAS_REVAL else ())):
    ok(t in covered, f"{t} под RLS")
REPORT["tables"] = len(covered)

# --- 1. fail closed без контекста ------------------------------------------------------------
tables = [INVOICE, PAYMENT, *((REVAL, LINE) if HAS_REVAL else ())]
n_rows = {t: owner_scalar(f"SELECT count(*) FROM {t}") for t in tables}
ok(n_rows[INVOICE] >= 2 and n_rows[PAYMENT] >= 2, f"в таблицах есть данные {n_rows}")
with app.cursor() as cur:
    ok(guc(cur) in (None, ""), "на новом соединении контекст пуст")
    for t in tables:
        cur.execute(f"SELECT count(*) FROM {t}")
        ok(cur.fetchone()[0] == 0, f"{t}: без контекста видно строк != 0")
        cur.execute("SELECT set_config('app.company_id', '', false)")
        cur.execute(f"SELECT count(*) FROM {t}")
        ok(cur.fetchone()[0] == 0, f"{t}: с пустым контекстом видно строк != 0")
        cur.execute(f"UPDATE {t} SET company_id=company_id")
        ok(cur.rowcount == 0, f"{t}: без контекста обновлено строк != 0")
        cur.execute(f"DELETE FROM {t}")
        ok(cur.rowcount == 0, f"{t}: без контекста удалено строк != 0")
app.rollback()

REVAL_INSERT = (
    f"INSERT INTO {REVAL} (company_id, as_of, kind, base_currency_id, created_at, summary) "
    "VALUES (%s, %s, 'report', %s, now(), '{}') RETURNING id"
)
LINE_INSERT = (
    f"INSERT INTO {LINE} (company_id, revaluation_id, invoice_id, direction, currency_id, open_balance, "
    "applied_rate_source, flags) VALUES (%s, %s, %s, 'out', %s, 10, '', '{}') RETURNING id"
)
if HAS_REVAL:
    expects_rls_error(
        lambda: app.cursor().execute(REVAL_INSERT, [A["company"], "2026-06-01", A["currency"]]),
        "вставка переоценки без контекста",
    )
    app.rollback()

# --- 2. чтение своих данных ------------------------------------------------------------------------
with app.cursor() as cur:
    cur.execute("SELECT set_config('app.company_id', %s, false)", [str(A["company"])])
    for t in (INVOICE, PAYMENT):
        cur.execute(f"SELECT DISTINCT company_id FROM {t}")
        ok(cur.fetchall() == [(A["company"],)], f"A читает только свои строки {t}")
    cur.execute("SELECT set_config('app.company_id', %s, false)", [str(B["company"])])
    for t in (INVOICE, PAYMENT):
        cur.execute(f"SELECT count(*) FROM {t} WHERE company_id=%s", [A["company"]])
        ok(cur.fetchone()[0] == 0, f"B не видит {t} A")
        cur.execute(f"UPDATE {t} SET company_id=company_id WHERE company_id=%s", [A["company"]])
        ok(cur.rowcount == 0, f"B не меняет {t} A")
        cur.execute(f"DELETE FROM {t} WHERE company_id=%s", [A["company"]])
        ok(cur.rowcount == 0, f"B не удаляет {t} A")
app.rollback()


# --- 3. ЗАПИСЬ своих данных под ролью приложения --------------------------------------------------
def run(sql, params=()):
    with connection.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else cur.rowcount


ok(run("SELECT current_user")[0][0] == "logistix_app", "Django подключён ролью приложения")
created = {"A": None, "B": None}
if HAS_REVAL:
    from apps.finance import fx_revaluation

    for key, ids in (("A", A), ("B", B)):
        with tenant_context(ids["company"]):
            reval = fx_revaluation.create_revaluation(
                ids["company"], date(2026, 6, 1), "report", None
            )
            created[key] = reval.pk
            ok(
                reval.lines.count() >= 1,
                f"{key}: сервис записал строки снимка под ролью приложения",
            )
            ok(
                run(f"SELECT count(*) FROM {REVAL}")[0][0] == 1
                and run(f"SELECT count(*) FROM {LINE}")[0][0] == reval.lines.count(),
                f"{key} видит только свой снимок",
            )
    # владелец: ровно по одному снимку у каждой компании
    for key, ids in (("A", A), ("B", B)):
        ok(
            owner_scalar(f"SELECT count(*) FROM {REVAL} WHERE company_id=%s", [ids["company"]])
            == 1,
            f"снимок {key} записан",
        )
    # колонки снимков счёта и оплаты пишутся
    with tenant_context(A["company"]):
        with transaction.atomic():
            ok(
                run(
                    f"UPDATE {INVOICE} SET base_currency_id=%s, rate_to_base=450.5, rate_to_base_date=%s WHERE id=%s",
                    [A["currency"], "2026-05-01", A["invoice"]],
                )
                == 1,
                "A пишет снимок счёта",
            )
            ok(
                run(
                    f"UPDATE {PAYMENT} SET base_currency_id=%s, rate_to_base=460, rate_to_base_date=%s WHERE id=%s",
                    [A["currency"], "2026-05-20", A["payment"]],
                )
                == 1,
                "A пишет снимок оплаты",
            )
        got = run(f"SELECT rate_to_base FROM {INVOICE} WHERE id=%s", [A["invoice"]])
        ok(str(got[0][0]) == "450.500000", f"A читает снимок счёта {got}")
    ok(
        owner_scalar(f"SELECT rate_to_base FROM {INVOICE} WHERE id=%s", [B["invoice"]]) is None,
        "снимок счёта B не затронут",
    )

    # B не видит, не меняет, не удаляет, не вставляет и не переносит строки A
    with tenant_context(B["company"]):
        ok(
            run(f"SELECT count(*) FROM {REVAL} WHERE id=%s", [created["A"]])[0][0] == 0,
            "B не видит снимок A",
        )
        ok(
            run(f"SELECT count(*) FROM {LINE} WHERE revaluation_id=%s", [created["A"]])[0][0] == 0,
            "B не видит строки снимка A",
        )
        ok(
            run(f"UPDATE {REVAL} SET summary='{{}}' WHERE id=%s", [created["A"]]) == 0,
            "B не меняет снимок A",
        )
        ok(run(f"DELETE FROM {REVAL} WHERE id=%s", [created["A"]]) == 0, "B не удаляет снимок A")
        ok(
            run(f"DELETE FROM {LINE} WHERE revaluation_id=%s", [created["A"]]) == 0,
            "B не удаляет строки снимка A",
        )
        ok(
            run(f"UPDATE {INVOICE} SET rate_to_base=1 WHERE id=%s", [A["invoice"]]) == 0,
            "B не меняет снимок счёта A",
        )

        def insert_foreign():
            with transaction.atomic():
                run(REVAL_INSERT, [A["company"], "2026-06-02", A["currency"]])

        expects_rls_error(insert_foreign, "B вставляет снимок A")

        def insert_foreign_line():
            with transaction.atomic():
                run(LINE_INSERT, [A["company"], created["B"], B["invoice"], B["currency"]])

        expects_rls_error(insert_foreign_line, "B вставляет строку снимка A")

        def move_to_a():
            with transaction.atomic():
                run(f"UPDATE {REVAL} SET company_id=%s WHERE id=%s", [A["company"], created["B"]])

        expects_rls_error(move_to_a, "B переносит свой снимок в A")

# --- 4. сброс контекста: ROLLBACK, savepoint, повторное использование соединения ------------------
app = raw(APP_URL)
with app.cursor() as cur:
    cur.execute("SELECT set_config('app.company_id', %s, false)", [str(A["company"])])
    ok(guc(cur) == str(A["company"]), "контекст установлен внутри транзакции")
    app.rollback()
    ok(guc(cur) in (None, ""), "после ROLLBACK контекст не «подвешен»")
    cur.execute(f"SELECT count(*) FROM {INVOICE}")
    ok(cur.fetchone()[0] == 0, "после ROLLBACK строки не видны")
    app.rollback()
with app.cursor() as cur:
    cur.execute("SELECT set_config('app.company_id', %s, false)", [str(A["company"])])
    app.commit()
    cur.execute("SAVEPOINT s1")
    cur.execute("SELECT set_config('app.company_id', %s, false)", [str(B["company"])])
    cur.execute("ROLLBACK TO SAVEPOINT s1")
    ok(guc(cur) == str(A["company"]), "после ROLLBACK TO SAVEPOINT вернулся контекст A (не B)")
    app.rollback()
    cur.execute("SELECT set_config('app.company_id', '', false)")
    app.commit()
app.close()
ok(run(f"SELECT count(*) FROM {INVOICE}")[0][0] == 0, "Django без контекста: 0 строк")


class Boom(Exception):
    pass


if HAS_REVAL:
    try:  # откат записи снимка вместе с транзакцией: следов нет, контекст не залипает
        with tenant_context(A["company"]), transaction.atomic():
            run(REVAL_INSERT, [A["company"], "2026-06-03", A["currency"]])
            run(f"UPDATE {INVOICE} SET rate_to_base=999 WHERE id=%s", [A["invoice"]])
            raise Boom
    except Boom:
        pass
    ok(
        run("SELECT current_setting('app.company_id', true)")[0][0] in (None, ""),
        "ROLLBACK: контекст пуст",
    )
    ok(
        owner_scalar(f"SELECT count(*) FROM {REVAL} WHERE company_id=%s", [A["company"]]) == 1,
        "откат: лишнего снимка нет",
    )
    ok(
        str(owner_scalar(f"SELECT rate_to_base FROM {INVOICE} WHERE id=%s", [A["invoice"]]))
        == "450.500000",
        "откат: снимок счёта не изменился",
    )
with tenant_context(A["company"]):  # точка сохранения при действующем контексте
    with transaction.atomic():
        try:
            with transaction.atomic():
                run(f"SELECT count(*) FROM {INVOICE}")
                raise Boom
        except Boom:
            pass
        ok(
            run("SELECT current_setting('app.company_id', true)")[0][0] == str(A["company"]),
            "GUC = A после отката точки сохранения",
        )
ok(
    run(f"SELECT count(*) FROM {INVOICE}")[0][0] == 0,
    "после всех откатов подвешенного контекста нет",
)
connection.close()
ok(run(f"SELECT count(*) FROM {PAYMENT}")[0][0] == 0, "новое соединение: контекста нет")

# --- 5. возврат данных к исходному состоянию (под ролью приложения; владелец - только проверка) ----
if HAS_REVAL:
    for key, ids in (("A", A), ("B", B)):
        with tenant_context(ids["company"]):
            run(f"DELETE FROM {LINE} WHERE revaluation_id=%s", [created[key]])
            ok(
                run(f"DELETE FROM {REVAL} WHERE id=%s", [created[key]]) == 1,
                f"снимок {key} удалён батареей",
            )
    with tenant_context(A["company"]):
        run(
            f"UPDATE {INVOICE} SET base_currency_id=NULL, rate_to_base=NULL, rate_to_base_date=NULL WHERE id=%s",
            [A["invoice"]],
        )
        run(
            f"UPDATE {PAYMENT} SET base_currency_id=NULL, rate_to_base=NULL, rate_to_base_date=NULL WHERE id=%s",
            [A["payment"]],
        )
    ok(
        owner_scalar(f"SELECT count(*) FROM {REVAL}") == 0
        and owner_scalar(f"SELECT count(*) FROM {LINE}") == 0,
        "снимков не осталось",
    )
connection.close()
print("RLS_REPORT=" + json.dumps(REPORT, ensure_ascii=False))
