# ruff: noqa: E501
"""Проверка RLS под РЕАЛЬНОЙ ролью logistix_app после миграций этапа 1.5-A; выполняется внутри `manage.py shell`.

Подключение приложения (DATABASE_URL) - роль logistix_app (не суперпользователь, без BYPASSRLS).
Владелец (OWNER_URL) нужен только для сравнения «сколько строк существует на самом деле».
Окружение: RLS_STEP, RLS_IDS (JSON: компании, роли, документы), OWNER_URL.
Батарея адаптивна: таблицы и колонки шага проверяются, только если они есть в схеме.
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
CM, MODULE, PROFILE = "core_companymodule", "core_module", "core_activityprofile"
ROLE, DOC = "core_role", "documents_issueddocument"
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


def owner_rows(sql, params=()):
    with raw(OWNER_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


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


def has_table(name):
    return bool(
        owner_scalar("SELECT count(*) FROM pg_class WHERE relname=%s AND relkind='r'", [name])
    )


def columns(name):
    return {
        r[0]
        for r in owner_rows(
            "SELECT column_name FROM information_schema.columns WHERE table_name=%s", [name]
        )
    }


HAS_CM, HAS_MODULE, HAS_PROFILE = has_table(CM), has_table(MODULE), has_table(PROFILE)
HAS_SUBJECT = {"subject_type", "subject_id"} <= columns(DOC)
ok(HAS_MODULE == HAS_PROFILE, "таблицы каталога появляются вместе")
REPORT.update(has_company_module=HAS_CM, has_catalog=HAS_MODULE, has_subject=HAS_SUBJECT)

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
ok(len(flags) >= 20, f"таблиц компаний: {len(flags)}")
for t, state in flags.items():
    if t in ("core_membership",):
        continue
    if state == (True, True):
        ok(
            t in pols and "app.company_id" in pols[t][1] and "app.company_id" in pols[t][2],
            f"{t}: политика USING + WITH CHECK",
        )
for t in tenant_tables():  # каждая существующая в БД таблица TenantModel закрыта RLS
    if t in flags:
        ok(flags[t] == (True, True), f"{t}: ENABLE+FORCE RLS {flags[t]}")
REPORT["tables"] = len(flags)
if HAS_CM:
    ok(flags.get(CM) == (True, True), f"{CM}: ENABLE+FORCE RLS {flags.get(CM)}")
    ok(CM in pols, f"{CM}: политика tenant_isolation")
for t in (ROLE, DOC):
    ok(flags.get(t) == (True, True), f"{t}: ENABLE+FORCE RLS {flags.get(t)}")

# --- 1. платформенные таблицы каталога: без company, читаются приложением ------------------------
if HAS_MODULE:
    for t in (MODULE, PROFILE):
        ok("company_id" not in columns(t), f"{t}: платформенная таблица без company_id")
    with app.cursor() as cur:
        ok(guc(cur) in (None, ""), "на новом соединении контекст пуст")
        cur.execute(f"SELECT code, is_core, requires FROM {MODULE} ORDER BY sort")
        mods = cur.fetchall()
        ok(
            len(mods) in (11, 12)  # 12 после core.0020 (logistics) and mods[0][0] == "core" and mods[0][1],
            f"каталог читается без контекста: {len(mods)}",
        )
        ok(
            dict((m[0], m[2]) for m in mods)["documents"] == ["core"],
            "documents требует только core",
        )
        cur.execute(f"SELECT count(*) FROM {PROFILE}")
        ok(cur.fetchone()[0] == 3, "три профиля деятельности")
    app.rollback()

# --- 2. CompanyModule: fail closed, свои данные, чужие недоступны --------------------------------
INS = f"INSERT INTO {CM} (company_id, module_code, enabled, reason) VALUES (%s, %s, true, 'rls-проба') RETURNING id"
if HAS_CM:
    total = owner_scalar(f"SELECT count(*) FROM {CM}")
    with app.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {CM}")
        ok(cur.fetchone()[0] == 0, "без контекста строк CompanyModule не видно")
        cur.execute("SELECT set_config('app.company_id', '', false)")
        cur.execute(f"SELECT count(*) FROM {CM}")
        ok(cur.fetchone()[0] == 0, "с пустым контекстом строк не видно")
        cur.execute(f"UPDATE {CM} SET reason=reason")
        ok(cur.rowcount == 0, "без контекста нечего обновлять")
        cur.execute(f"DELETE FROM {CM}")
        ok(cur.rowcount == 0, "без контекста нечего удалять")
    app.rollback()
    expects_rls_error(
        lambda: app.cursor().execute(INS, [A["company"], "analytics"]), "вставка без контекста"
    )
    app.rollback()
    with app.cursor() as cur:
        cur.execute("SELECT set_config('app.company_id', %s, false)", [str(A["company"])])
        cur.execute(f"SELECT DISTINCT company_id FROM {CM}")
        rows = cur.fetchall()
        ok(rows in ([], [(A["company"],)]), f"A видит только свои строки {rows}")
        cur.execute("SELECT set_config('app.company_id', %s, false)", [str(B["company"])])
        cur.execute(f"SELECT count(*) FROM {CM} WHERE company_id=%s", [A["company"]])
        ok(cur.fetchone()[0] == 0, "B не видит строки A")
        cur.execute(f"UPDATE {CM} SET reason='x' WHERE company_id=%s", [A["company"]])
        ok(cur.rowcount == 0, "B не меняет строки A")
        cur.execute(f"DELETE FROM {CM} WHERE company_id=%s", [A["company"]])
        ok(cur.rowcount == 0, "B не удаляет строки A")
    app.rollback()

    def run(sql, params=()):
        with connection.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() if cur.description else cur.rowcount

    ok(run("SELECT current_user")[0][0] == "logistix_app", "Django подключён ролью приложения")
    created = {}
    for key, ids in (("A", A), ("B", B)):  # запись своих данных
        with tenant_context(ids["company"]), transaction.atomic():
            created[key] = run(INS, [ids["company"], "analytics"])[0][0]
            ok(
                run(f"UPDATE {CM} SET enabled=false, reason='выкл' WHERE id=%s", [created[key]])
                == 1,
                f"{key} обновляет свою строку",
            )
            ok(
                run(f"SELECT count(*) FROM {CM} WHERE module_code='analytics'")[0][0] == 1,
                f"{key} видит только свою строку",
            )
            ok(
                run(f"SELECT count(*) FROM {CM} WHERE module_code='analytics' AND reason='выкл'")[
                    0
                ][0]
                == 1,
                f"{key} читает записанное",
            )
    with tenant_context(B["company"]):  # B против строки A
        ok(
            run(f"SELECT count(*) FROM {CM} WHERE id=%s", [created["A"]])[0][0] == 0,
            "B не видит строку A",
        )
        ok(
            run(f"UPDATE {CM} SET reason='взлом' WHERE id=%s", [created["A"]]) == 0,
            "B не меняет строку A",
        )
        ok(run(f"DELETE FROM {CM} WHERE id=%s", [created["A"]]) == 0, "B не удаляет строку A")

        def insert_foreign():
            with transaction.atomic():
                run(INS, [A["company"], "ocr"])

        expects_rls_error(insert_foreign, "B вставляет строку A")

        def move_to_a():
            with transaction.atomic():
                run(f"UPDATE {CM} SET company_id=%s WHERE id=%s", [A["company"], created["B"]])

        expects_rls_error(move_to_a, "B переносит свою строку в A")
    ok(
        owner_scalar(f"SELECT reason FROM {CM} WHERE id=%s", [created["A"]]) == "выкл",
        "строка A не тронута",
    )
    for key, ids in (("A", A), ("B", B)):  # возврат к исходному состоянию
        with tenant_context(ids["company"]):
            ok(run(f"DELETE FROM {CM} WHERE id=%s", [created[key]]) == 1, f"{key}: проба удалена")
    ok(
        owner_scalar(f"SELECT count(*) FROM {CM}") == total,
        "данные CompanyModule вернулись к исходным",
    )

    # --- сброс контекста: ROLLBACK, savepoint, повторное использование соединения ---------------
    app = raw(APP_URL)
    with app.cursor() as cur:
        cur.execute("SELECT set_config('app.company_id', %s, false)", [str(A["company"])])
        ok(guc(cur) == str(A["company"]), "контекст установлен")
        app.rollback()
        ok(guc(cur) in (None, ""), "после ROLLBACK контекст не «подвешен»")
        cur.execute(f"SELECT count(*) FROM {CM}")
        ok(cur.fetchone()[0] == 0, "после ROLLBACK строки не видны")
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
            run(INS, [A["company"], "gps"])
            raise Boom
    except Boom:
        pass
    ok(
        run("SELECT current_setting('app.company_id', true)")[0][0] in (None, ""),
        "после отката Django контекст пуст",
    )
    ok(
        owner_scalar(f"SELECT count(*) FROM {CM} WHERE module_code='gps'") == 0,
        "откат записи не оставил следов",
    )
    connection.close()
    ok(
        run(f"SELECT count(*) FROM {CM}")[0][0] == 0,
        "новое соединение: контекста нет, строк не видно",
    )
else:
    app.close()
    connection.close()

# --- 3. роли (право company.manage_modules) читаются в своём контексте --------------------------
app = raw(APP_URL)
with app.cursor() as cur:
    for key, ids in (("A", A), ("B", B)):
        cur.execute("SELECT set_config('app.company_id', %s, false)", [str(ids["company"])])
        cur.execute(f"SELECT name, permissions FROM {ROLE} WHERE is_system ORDER BY id")
        roles = {r[0]: r[1] for r in cur.fetchall()}
        ok(len(roles) == 7, f"{key} видит свои 7 системных ролей")
        has = {n for n, p in roles.items() if "company.manage_modules" in p}
        if os.environ.get("RLS_EXPECT_PERM") == "1":  # после core.0018 (откат её не отзывает)
            ok(
                has == {"Администратор"},
                f"{key}: право manage_modules только у Администратора: {has}",
            )
        else:
            ok(has == set(), f"{key}: до 0018 права нет: {has}")
        cur.execute(f"SELECT count(*) FROM {ROLE} WHERE company_id <> %s", [ids["company"]])
        ok(cur.fetchone()[0] == 0, f"{key} не видит роли другой компании")
app.rollback()
app.close()

# --- 4. IssuedDocument: колонки субъекта, чтение и запись своих, чужие недоступны ----------------
app = raw(APP_URL)
with app.cursor() as cur:
    cur.execute("SELECT set_config('app.company_id', %s, false)", [str(A["company"])])
    cur.execute(f"SELECT count(*) FROM {DOC}")
    ok(cur.fetchone()[0] == len(A["docs"]), "A видит свои документы")
    cur.execute("SELECT set_config('app.company_id', %s, false)", [str(B["company"])])
    cur.execute(f"SELECT count(*) FROM {DOC} WHERE company_id=%s", [A["company"]])
    ok(cur.fetchone()[0] == 0, "B не видит документы A")
    if HAS_SUBJECT:
        cur.execute(f"UPDATE {DOC} SET subject_type='x.y' WHERE company_id=%s", [A["company"]])
        ok(cur.rowcount == 0, "B не меняет субъекта документов A")
        cur.execute("SELECT set_config('app.company_id', %s, false)", [str(A["company"])])
        doc_id = A["docs"]["contract"]
        cur.execute(f"SELECT subject_type, subject_id FROM {DOC} WHERE id=%s", [doc_id])
        before = cur.fetchone()
        cur.execute(
            f"UPDATE {DOC} SET subject_type='drivers.driver', subject_id=7 WHERE id=%s", [doc_id]
        )
        ok(cur.rowcount == 1, "A пишет субъекта своего документа")
        cur.execute(f"SELECT subject_type, subject_id FROM {DOC} WHERE id=%s", [doc_id])
        ok(cur.fetchone() == ("drivers.driver", 7), "A читает записанного субъекта")
        app.rollback()  # возврат: запись не фиксируется
        cur = app.cursor()
        cur.execute("SELECT set_config('app.company_id', %s, false)", [str(A["company"])])
        cur.execute(f"SELECT subject_type, subject_id FROM {DOC} WHERE id=%s", [doc_id])
        ok(cur.fetchone() == before, "откат записи субъекта не оставил следов")
        cur.execute("SELECT set_config('app.company_id', '', false)")
        cur.execute(f"SELECT count(*) FROM {DOC}")
        ok(cur.fetchone()[0] == 0, "без контекста документы не видны")
app.rollback()
app.close()
print("RLS_REPORT=" + json.dumps(REPORT, ensure_ascii=False))
