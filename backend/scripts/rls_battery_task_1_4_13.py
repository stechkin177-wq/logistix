# ruff: noqa: E501
"""Проверка RLS под РЕАЛЬНОЙ ролью logistix_app для finance.0008 / finance.0009; выполняется внутри `manage.py shell`.

Подключение приложения (DATABASE_URL) - роль logistix_app (не суперпользователь, без BYPASSRLS).
Владелец (OWNER_URL) нужен только для сравнения «сколько строк существует на самом деле».
Окружение: RLS_STEP (имя шага), RLS_IDS (JSON: компании и id замечаний), OWNER_URL.
Батарея адаптивна: колонки/ограничения 0008 и 0009 проверяются, только если они есть в схеме шага.
Результат - строка `RLS_REPORT={json}`; любое нарушение - исключение (код возврата не 0).
"""

import json
import os

import psycopg
from django.db import DatabaseError, connection, transaction

from apps.core.rls import tenant_tables
from apps.core.tenancy import tenant_context

STEP = os.environ["RLS_STEP"]
IDS = json.loads(os.environ["RLS_IDS"])
OWNER_URL = os.environ["OWNER_URL"]
APP_URL = os.environ["DATABASE_URL"]
A, B = IDS["A"], IDS["B"]
ISSUE = "finance_financemigrationissue"
SETTINGS = "finance_companyfinancialsettings"
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


# --- схема шага --------------------------------------------------------------------------
cols = {
    r[0]
    for r in raw(OWNER_URL)
    .execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", [ISSUE])
    .fetchall()
}
set_cols = {
    r[0]
    for r in raw(OWNER_URL)
    .execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", [SETTINGS])
    .fetchall()
}
HAS_RES = {"resolution", "resolution_data"} <= cols
HAS_SW = {"engine_switched_at", "financial_writes_frozen"} <= set_cols
HAS_UNIQ = bool(
    owner_scalar("SELECT count(*) FROM pg_indexes WHERE indexname='finissue_ambiguous_source_uniq'")
)
ok(HAS_RES == ("resolution" in cols), "колонки resolution/resolution_data появляются вместе")
ok(
    HAS_RES == HAS_UNIQ,
    f"0008: колонки решения и частичная уникальность согласованы ({HAS_RES}/{HAS_UNIQ})",
)
REPORT.update(has_resolution=HAS_RES, has_switch_columns=HAS_SW, has_unique=HAS_UNIQ)

# --- 0. роль и покрытие ---------------------------------------------------------------------
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
for t in (ISSUE, SETTINGS):
    ok(t in covered, f"{t} под RLS")
REPORT["tables"] = len(covered)

# --- 1. fail closed без контекста ---------------------------------------------------------
n_issues = owner_scalar(f"SELECT count(*) FROM {ISSUE}")
n_settings = owner_scalar(f"SELECT count(*) FROM {SETTINGS}")
ok(n_issues >= 4 and n_settings >= 2, f"в таблицах есть данные ({n_issues}/{n_settings})")
with app.cursor() as cur:
    ok(guc(cur) in (None, ""), "на новом соединении контекст пуст")
    for t in (ISSUE, SETTINGS):
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
expects_rls_error(
    lambda: app.cursor().execute(
        f"INSERT INTO {ISSUE} (company_id, issue_type, severity, source_model, message, details, status, resolution_note, created_at) "
        "VALUES (%s, 'x', 'info', '', 'm', '{}', 'open', '', now())",
        [A["company"]],
    ),
    "вставка замечания без контекста",
)
app.rollback()

# --- 2. свои данные: чтение (контекст на сессии, как делает приложение) -----------------------
with app.cursor() as cur:
    cur.execute("SELECT set_config('app.company_id', %s, false)", [str(A["company"])])
    cur.execute(f"SELECT id, company_id FROM {ISSUE} ORDER BY id")
    rows = cur.fetchall()
    ok(rows and {r[1] for r in rows} == {A["company"]}, "A читает только свои замечания")
    ok(
        {r[0] for r in rows} >= set(A["issues"]) and not ({r[0] for r in rows} & set(B["issues"])),
        "A видит свои id и не видит id B",
    )
    cur.execute(f"SELECT company_id FROM {SETTINGS}")
    ok(cur.fetchall() == [(A["company"],)], "A читает ровно свою строку настроек")
    cur.execute("SELECT set_config('app.company_id', %s, false)", [str(B["company"])])
    cur.execute(f"SELECT count(*) FROM {ISSUE} WHERE company_id=%s", [A["company"]])
    ok(cur.fetchone()[0] == 0, "B не видит замечания A")
    cur.execute(f"UPDATE {ISSUE} SET message=message WHERE company_id=%s", [A["company"]])
    ok(cur.rowcount == 0, "B не меняет замечания A")
    cur.execute(f"DELETE FROM {ISSUE} WHERE company_id=%s", [A["company"]])
    ok(cur.rowcount == 0, "B не удаляет замечания A")
    cur.execute(
        f"UPDATE {SETTINGS} SET sync_carrier_price=sync_carrier_price WHERE company_id=%s",
        [A["company"]],
    )
    ok(cur.rowcount == 0, "B не меняет настройки A")
    cur.execute(f"DELETE FROM {SETTINGS} WHERE company_id=%s", [A["company"]])
    ok(cur.rowcount == 0, "B не удаляет настройки A")
app.rollback()

# --- 3. свои данные: ЗАПИСЬ (включая новые колонки) под ролью приложения через tenant_context -----


def run(sql, params=()):
    with connection.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else cur.rowcount


ok(run("SELECT current_user")[0][0] == "logistix_app", "Django подключён ролью приложения")
created = []  # (company, id) созданных батареей замечаний
a_issue = A["issues"][0]
with tenant_context(A["company"]):
    with transaction.atomic():
        before = run(f"SELECT message, issue_type, status FROM {ISSUE} WHERE id=%s", [a_issue])[0]
        ok(
            run(f"UPDATE {ISSUE} SET message=%s WHERE id=%s", ["правка RLS 1.4.13", a_issue]) == 1,
            "A меняет своё замечание",
        )
        if HAS_RES:
            ok(
                run(
                    f"UPDATE {ISSUE} SET resolution=%s, resolution_data=%s::jsonb, status='resolved', resolution_note='rls' WHERE id=%s",
                    ["manual_expense", json.dumps({"category": "OTHER"}), a_issue],
                )
                == 1,
                "A пишет resolution/resolution_data",
            )
            got = run(
                f"SELECT resolution, resolution_data->>'category' FROM {ISSUE} WHERE id=%s",
                [a_issue],
            )[0]
            ok(got == ("manual_expense", "OTHER"), f"A читает записанное решение {got}")
            new_id = run(
                f"INSERT INTO {ISSUE} (company_id, issue_type, severity, source_model, source_id, message, details, status, resolution_note, resolution, resolution_data, created_at) "
                "VALUES (%s, 'rls_probe', 'info', 'OrderService', 987654, 'm', '{}', 'open', '', 'justified_exclusion', '{\"k\": 1}', now()) RETURNING id",
                [A["company"]],
            )[0][0]
        else:
            new_id = run(
                f"INSERT INTO {ISSUE} (company_id, issue_type, severity, source_model, source_id, message, details, status, resolution_note, created_at) "
                "VALUES (%s, 'rls_probe', 'info', 'OrderService', 987654, 'm', '{}', 'open', '', now()) RETURNING id",
                [A["company"]],
            )[0][0]
        created.append((A["company"], new_id))
        ok(
            run(f"SELECT count(*) FROM {ISSUE} WHERE id=%s", [new_id])[0][0] == 1,
            "A читает вставленное",
        )
        if HAS_SW:
            ok(
                run(
                    f"UPDATE {SETTINGS} SET financial_writes_frozen=true, engine_switched_at=now() WHERE company_id=%s",
                    [A["company"]],
                )
                == 1,
                "A переключает флаг заморозки и пишет engine_switched_at",
            )
            got = run(
                f"SELECT financial_writes_frozen, engine_switched_at IS NOT NULL FROM {SETTINGS}"
            )
            ok(got == [(True, True)], f"A читает заморозку {got}")
# транзакция A зафиксирована: проверяем владельцем, что записано ровно у A
ok(
    owner_scalar(f"SELECT message FROM {ISSUE} WHERE id=%s", [a_issue]) == "правка RLS 1.4.13",
    "запись A зафиксирована",
)
if HAS_SW:
    ok(
        owner_scalar(
            f"SELECT financial_writes_frozen FROM {SETTINGS} WHERE company_id=%s", [A["company"]]
        )
        is True,
        "заморозка A записана",
    )
    ok(
        owner_scalar(
            f"SELECT financial_writes_frozen FROM {SETTINGS} WHERE company_id=%s", [B["company"]]
        )
        is False,
        "заморозка B не затронута",
    )
    ok(
        owner_scalar(
            f"SELECT engine_switched_at IS NULL FROM {SETTINGS} WHERE company_id=%s", [B["company"]]
        )
        is True,
        "engine_switched_at B не затронут",
    )

# B не видит и не меняет только что записанное A
with tenant_context(B["company"]):
    ok(
        run(f"SELECT count(*) FROM {ISSUE} WHERE id=%s", [new_id])[0][0] == 0,
        "B не видит новое замечание A",
    )
    ok(
        run(f"UPDATE {ISSUE} SET message='x' WHERE id=%s", [a_issue]) == 0,
        "B не меняет замечание A",
    )
    ok(run(f"DELETE FROM {ISSUE} WHERE id=%s", [new_id]) == 0, "B не удаляет замечание A")
    if HAS_SW:
        ok(
            run(
                f"UPDATE {SETTINGS} SET financial_writes_frozen=false WHERE company_id=%s",
                [A["company"]],
            )
            == 0,
            "B не снимает заморозку A",
        )
        ok(
            run(f"SELECT financial_writes_frozen FROM {SETTINGS}") == [(False,)],
            "B видит только свою строку (не заморожена)",
        )

    # вставка строки A / перенос своей строки в A отклоняются RLS
    def insert_foreign():
        with transaction.atomic():
            run(
                f"INSERT INTO {ISSUE} (company_id, issue_type, severity, source_model, message, details, status, resolution_note, created_at) "
                "VALUES (%s, 'x', 'info', '', 'm', '{}', 'open', '', now())",
                [A["company"]],
            )

    expects_rls_error(insert_foreign, "B вставляет замечание A")
    b_issue = B["issues"][0]

    def move_to_a():
        with transaction.atomic():
            run(f"UPDATE {ISSUE} SET company_id=%s WHERE id=%s", [A["company"], b_issue])

    expects_rls_error(move_to_a, "B переносит своё замечание в A")

# частичная уникальность (0008): работает внутри компании, не пересекает компании
if HAS_UNIQ:
    with tenant_context(A["company"]):
        src = run(
            f"SELECT source_model, source_id FROM {ISSUE} WHERE issue_type='ambiguous_trip_expense' AND source_id IS NOT NULL ORDER BY id"
        )[0]

        def dup_in_a():
            with transaction.atomic():
                run(
                    f"INSERT INTO {ISSUE} (company_id, issue_type, severity, source_model, source_id, message, details, status, resolution_note, resolution, resolution_data, created_at) "
                    "VALUES (%s, 'ambiguous_trip_expense', 'error', %s, %s, 'dup', '{}', 'open', '', '', '{}', now())",
                    [A["company"], src[0], src[1]],
                )

        try:
            dup_in_a()
            ok(False, "дубль ambiguous_trip_expense в одной компании должен отклоняться")
        except DatabaseError as exc:
            ok(
                "finissue_ambiguous_source_uniq" in str(exc) or "unique" in str(exc).lower(),
                f"ожидалась уникальность: {exc}",
            )
    with tenant_context(B["company"]):
        with transaction.atomic():  # тот же источник в ДРУГОЙ компании допустим
            bid = run(
                f"INSERT INTO {ISSUE} (company_id, issue_type, severity, source_model, source_id, message, details, status, resolution_note, resolution, resolution_data, created_at) "
                "VALUES (%s, 'ambiguous_trip_expense', 'error', %s, %s, 'same source in B', '{}', 'open', '', '', '{}', now()) RETURNING id",
                [B["company"], src[0], src[1]],
            )[0][0]
        created.append((B["company"], bid))
    ok(True, "уникальность действует в рамках компании")

# --- 4. сброс контекста: ROLLBACK, savepoint, повторное использование соединения -------------
app = raw(APP_URL)
with app.cursor() as cur:
    cur.execute("SELECT set_config('app.company_id', %s, false)", [str(A["company"])])
    ok(guc(cur) == str(A["company"]), "контекст установлен внутри транзакции")
    app.rollback()
    ok(guc(cur) in (None, ""), "после ROLLBACK контекст не «подвешен»")
    cur.execute(f"SELECT count(*) FROM {ISSUE}")
    ok(cur.fetchone()[0] == 0, "после ROLLBACK строки не видны")
    app.rollback()
with app.cursor() as cur:  # откат до точки сохранения
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

ok(run(f"SELECT count(*) FROM {ISSUE}")[0][0] == 0, "Django без контекста: 0 строк")
with tenant_context(A["company"]):
    ok(run(f"SELECT count(*) FROM {ISSUE}")[0][0] >= 3, "Django в контексте A видит замечания A")
ok(
    run(f"SELECT count(*) FROM {ISSUE}")[0][0] == 0,
    "после выхода из контекста тот же коннект видит 0 строк",
)


class Boom(Exception):
    pass


try:  # откат ЗАПИСИ новых колонок вместе с транзакцией: данные не меняются, контекст не залипает
    with tenant_context(A["company"]), transaction.atomic():
        if HAS_RES:
            run(f"UPDATE {ISSUE} SET resolution='carrier_expense' WHERE id=%s", [A["issues"][1]])
        if HAS_SW:
            run(f"UPDATE {SETTINGS} SET financial_writes_frozen=false")
        raise Boom
except Boom:
    pass
ok(
    run("SELECT current_setting('app.company_id', true)")[0][0] in (None, ""),
    "ROLLBACK: контекст пуст",
)
ok(run(f"SELECT count(*) FROM {ISSUE}")[0][0] == 0, "после ROLLBACK и выхода из контекста: 0 строк")
if HAS_RES:
    ok(
        owner_scalar(f"SELECT resolution FROM {ISSUE} WHERE id=%s", [A["issues"][1]])
        != "carrier_expense",
        "откат: решение не записано",
    )
if HAS_SW:
    ok(
        owner_scalar(
            f"SELECT financial_writes_frozen FROM {SETTINGS} WHERE company_id=%s", [A["company"]]
        )
        is True,
        "откат: заморозка осталась включённой",
    )
with tenant_context(A["company"]):  # точка сохранения при действующем контексте
    with transaction.atomic():
        try:
            with transaction.atomic():
                run(f"SELECT count(*) FROM {ISSUE}")
                raise Boom
        except Boom:
            pass
        ok(
            run("SELECT current_setting('app.company_id', true)")[0][0] == str(A["company"]),
            "GUC = A после отката точки сохранения",
        )
ok(run(f"SELECT count(*) FROM {ISSUE}")[0][0] == 0, "после всех откатов подвешенного контекста нет")
connection.close()
ok(run(f"SELECT count(*) FROM {SETTINGS}")[0][0] == 0, "новое соединение: контекста нет")

# --- 5. возврат данных к исходному состоянию -------------------------------------------------
for company, issue_id in created:
    with tenant_context(company):
        ok(run(f"DELETE FROM {ISSUE} WHERE id=%s", [issue_id]) == 1, "созданное батареей удалено")
with tenant_context(A["company"]):
    run(f"UPDATE {ISSUE} SET message=%s, status=%s WHERE id=%s", [before[0], before[2], a_issue])
    if HAS_RES:
        run(
            f"UPDATE {ISSUE} SET resolution='', resolution_data='{{}}'::jsonb, resolution_note='' WHERE id=%s",
            [a_issue],
        )
    if HAS_SW:
        run(f"UPDATE {SETTINGS} SET financial_writes_frozen=false, engine_switched_at=NULL")
ok(
    owner_scalar(f"SELECT count(*) FROM {ISSUE}") == n_issues,
    "число замечаний вернулось к исходному",
)
connection.close()
print("RLS_REPORT=" + json.dumps(REPORT, ensure_ascii=False))
