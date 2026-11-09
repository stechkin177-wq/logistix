# ruff: noqa: E501
"""Проверка обновления с состояния ДО подзадачи 1.4.1 на временных БД (воспроизводимо).

Основная БД и демо-БД не затрагиваются. Нужны права CREATE DATABASE. Код возврата 0 - всё прошло.

БД №1 (данные и откат):
  1. миграции до core.0012 / finance.0003 (состояние до подзадачи);
  2. данные: пять компаний (стандартный trip_status; без COMPLETED; с дубликатом названия;
     переименованный; без KZT), курсы нескольких валют и дат, пользовательская роль;
  3. migrate до конца (M1..M6): курсы НЕИЗМЕННЫ (контрольная сумма и quote_currency IS NULL),
     строки настроек (completed_status только при однозначности), справочник категорий, права;
  4. повторное применение функций M2/M5/M6 (идемпотентность);
  5. откат M6..M1 (на данных без новых сущностей) и повторное применение, повторная проверка.
БД №2 (preflight): искусственный конфликт курсов; миграция finance.0006 останавливается с
  понятной ошибкой, курсы и схема не меняются.
"""

import hashlib
import json
import os
import sys

import psycopg
from task_1_4_1_common import DEFAULT_URL, TempDatabase, manage, manage_result

NEW_PERMS = (
    "finance.close_period",
    "finance.reopen_period",
    "finance.adjust_closed",
    "finance.backdate",
    "finance.manage_settings",
)
ACCOUNTANT_PERMS = ("finance.close_period", "finance.adjust_closed", "finance.backdate")
CATEGORY_CODES = {
    "FUEL", "MAINTENANCE", "REPAIR", "TIRES", "ROAD", "DRIVER", "INSURANCE", "TAX",
    "DEPRECIATION", "ADMINISTRATION", "OTHER",
}  # fmt: skip
SCENARIOS = ("standard", "no_completed", "duplicate", "renamed", "no_kzt")

SEED = """
import json
from apps.core.handbooks import defaults
from apps.core.models import User
from apps.core.services import create_company_with_defaults
from apps.core.signals import company_created

# состояние ДО подзадачи: нет справочника категорий, нет обработчика настроек
defaults.DEFAULTS.pop("expense_category", None)
company_created.receivers = []
# состояние ДО CompanyModule (core.0016): модули пишутся только в Company.modules
from apps.core import services as core_services
from apps.core.models import Company as _Company


def _legacy_modules(company, modules, **kwargs):
    _Company.objects.filter(pk=company.pk).update(modules=list(modules))
    company.modules = list(modules)
    return list(modules)


core_services.set_company_modules = _legacy_modules
out = {}
for key in %(keys)r:
    user = User.objects.create_user_schema_agnostic(email=f"{key}@upgrade141.kz", password="s3cret-pass-1")
    out[key] = create_company_with_defaults(key, user, ["forwarding"]).id
print("IDS=" + json.dumps(out))
"""


def seed_old_state(conn, ids: dict) -> dict:
    """Приводит данные к виду ДО подзадачи: роли без новых прав, курсы, особые статусы рейса."""
    with conn.cursor() as cur:
        for table in ("finance_companyfinancialsettings", "core_handbook"):
            cur.execute("SELECT to_regclass(%s)", [table])
            exists = cur.fetchone()[0] is not None
            assert exists == (table == "core_handbook"), f"исходное состояние: {table}"
        cur.execute("SELECT count(*) FROM core_handbook WHERE code='expense_category'")
        assert cur.fetchone()[0] == 0, "исходное состояние должно быть без expense_category"
        for key, company_id in ids.items():
            cur.execute("SELECT set_config('app.company_id', %s, false)", [str(company_id)])
            for perm in NEW_PERMS:
                cur.execute(
                    "UPDATE core_role SET permissions = COALESCE((SELECT jsonb_agg(p) FROM "
                    "jsonb_array_elements(permissions) p WHERE p <> to_jsonb(%s::text)), "
                    "'[]'::jsonb) WHERE company_id=%s",
                    [perm, company_id],
                )
            cur.execute(
                "INSERT INTO core_role (company_id, name, is_system, permissions) "
                "VALUES (%s, 'Своя роль', false, %s::jsonb)",
                [company_id, json.dumps(["finance.view", "finance.backdate"])],
            )
            status = (
                "SELECT v.id FROM core_handbookvalue v JOIN core_handbook h ON h.id=v.handbook_id "
                "WHERE v.company_id=%s AND h.code='trip_status' AND v.name=%s"
            )
            if key == "no_completed":
                cur.execute(
                    "DELETE FROM core_handbookvalue WHERE id=(" + status + ")",
                    [company_id, "Завершён"],
                )
            elif key == "duplicate":
                cur.execute(status, [company_id, "Завершён"])
                orig = cur.fetchone()[0]
                cur.execute("UPDATE core_handbookvalue SET code='' WHERE id=%s", [orig])
                cur.execute(
                    'INSERT INTO core_handbookvalue (company_id, handbook_id, name, code, "order", '
                    "is_initial, is_final, is_active) SELECT company_id, handbook_id, name, '', 90, "
                    "false, true, true FROM core_handbookvalue WHERE id=%s",
                    [orig],
                )
            elif key == "renamed":
                cur.execute(
                    "UPDATE core_handbookvalue SET name='Выполнен', code='' WHERE id=("
                    + status
                    + ")",
                    [company_id, "Завершён"],
                )
            elif key == "no_kzt":
                cur.execute(
                    "UPDATE core_handbookvalue SET code='' WHERE company_id=%s AND code='KZT'",
                    [company_id],
                )
            rates = [("USD", "2026-05-01", "470.250000"), ("USD", "2026-06-01", "481.500000"),
                     ("EUR", "2026-05-01", "510.100000"), ("RUB", "2026-06-01", "5.430000"),
                     ("RUB", "2026-06-15", "5.512345")]  # fmt: skip
            for code, day, rate in rates:
                cur.execute(
                    "INSERT INTO finance_exchangerate (company_id, currency_id, date, rate, created_at) "
                    "SELECT %s, v.id, %s, %s, now() FROM core_handbookvalue v JOIN core_handbook h "
                    "ON h.id=v.handbook_id WHERE v.company_id=%s AND h.code='currency' AND v.code=%s",
                    [company_id, day, rate, company_id, code],
                )
        cur.execute("SELECT set_config('app.company_id', '', false)")
    conn.commit()
    return {k: v for k, v in ids.items()}


def rates_digest(conn) -> tuple[str, int]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, company_id, currency_id, date, rate::text, created_at FROM finance_exchangerate "
            "ORDER BY id"
        )
        rows = cur.fetchall()
    conn.rollback()  # читающая транзакция не должна держать блокировки на время миграций
    return hashlib.sha256(repr(rows).encode()).hexdigest(), len(rows)


def check_upgraded(conn, ids: dict, rates_before: tuple, label: str, applied: bool = True) -> None:
    def ok(cond, message):
        if not cond:
            raise AssertionError(f"[{label}] {message}")

    digest, count = rates_digest(conn)
    ok((digest, count) == rates_before, "курсы изменились после миграций")
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM finance_exchangerate WHERE quote_currency_id IS NOT NULL")
        ok(cur.fetchone()[0] == 0, "у прежних курсов появилась валюта котировки")
        cur.execute(
            "SELECT company_id, currency_id, date, count(*) FROM finance_exchangerate "
            "GROUP BY 1,2,3 HAVING count(*) > 1"
        )
        ok(cur.fetchall() == [], "дубликаты курсов")
        cur.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename='finance_exchangerate' "
            "AND indexname IN ('exchangerate_kzt_uniq','exchangerate_pair_uniq')"
        )
        ok(
            {r[0] for r in cur.fetchall()} == {"exchangerate_kzt_uniq", "exchangerate_pair_uniq"},
            "индексы курсов",
        )
        for key, company_id in ids.items():
            cur.execute("SELECT set_config('app.company_id', %s, false)", [str(company_id)])
            cur.execute(
                "SELECT engine, allow_backdating, expense_creation_mode, sync_carrier_price, "
                "income_recognition, accounting_method, fiscal_year_start_month, cutover_date, "
                "base_currency_id, completed_status_id FROM finance_companyfinancialsettings "
                "WHERE company_id=%s",
                [company_id],
            )
            rows = cur.fetchall()
            ok(len(rows) == 1, f"{key}: строка настроек ровно одна ({len(rows)})")
            (engine, back, mode, sync, rec, method, month, cutover, base_id, done_id) = rows[0]
            ok(
                (engine, back, mode, sync, rec, method, month, cutover)
                == ("legacy", True, "manual", True, "all_trips_completed", "ACCRUAL", 1, None),
                f"{key}: значения по умолчанию {rows[0]}",
            )
            cur.execute("SELECT code FROM core_handbookvalue WHERE id=%s", [base_id])
            got = cur.fetchone()
            ok(
                (got[0] if got else None) == (None if key == "no_kzt" else "KZT"),
                f"{key}: base_currency",
            )
            if key in ("standard", "no_kzt"):
                cur.execute("SELECT code FROM core_handbookvalue WHERE id=%s", [done_id])
                ok(cur.fetchone()[0] == "COMPLETED", f"{key}: completed_status назначен")
            else:
                ok(done_id is None, f"{key}: completed_status НЕ назначается (неоднозначно/нет)")
            cur.execute(
                "SELECT v.code, v.name, v.order FROM core_handbookvalue v JOIN core_handbook h "
                "ON h.id=v.handbook_id WHERE v.company_id=%s AND h.code='expense_category' "
                "ORDER BY v.order",
                [company_id],
            )
            cats = cur.fetchall()
            ok(
                {c[0] for c in cats} == CATEGORY_CODES and len(cats) == 11,
                f"{key}: категории {cats}",
            )
            ok([c[2] for c in cats] == list(range(1, 12)), f"{key}: порядок категорий")
            cur.execute("SELECT name, permissions FROM core_role WHERE company_id=%s", [company_id])
            roles = {n: set(p) for n, p in cur.fetchall()}
            ok(set(NEW_PERMS) <= roles["Администратор"], f"{key}: Администратор получил пять прав")
            ok(roles["Бухгалтер"] & set(NEW_PERMS) == set(ACCOUNTANT_PERMS), f"{key}: Бухгалтер")
            for name in ("Менеджер", "Диспетчер", "Механик", "Наблюдатель", "Водитель"):
                ok(not roles[name] & set(NEW_PERMS), f"{key}: {name} без новых прав")
            ok(
                roles["Своя роль"] == {"finance.view", "finance.backdate"},
                f"{key}: своя роль не изменена",
            )
        cur.execute("SELECT set_config('app.company_id', '', false)")
    conn.rollback()


SHELL_IDEMPOTENCE = """
import importlib
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
loader = MigrationExecutor(connection).loader
m2 = importlib.import_module("apps.core.migrations.0013_expense_category_handbook")
m6 = importlib.import_module("apps.core.migrations.0014_finance_architecture_permissions")
m5 = importlib.import_module("apps.finance.migrations.0007_company_financial_settings_backfill")
m2.run_backfill(loader.project_state(("core", "0013_expense_category_handbook")).apps)
m6.run_backfill(loader.project_state(("core", "0014_finance_architecture_permissions")).apps)
m5.run_backfill(loader.project_state(("finance", "0007_company_financial_settings_backfill")).apps)
print("IDEMPOTENT_OK")
"""


def scenario_one(base_url: str) -> None:
    with TempDatabase(base_url, "logistix_upgrade141") as db:
        url = db.url
        # 1) состояние ДО подзадачи
        manage(url, "migrate", "core", "0012", "--noinput")
        manage(url, "migrate", "billing", "--noinput")
        manage(url, "migrate", "forwarding", "--noinput")
        manage(url, "migrate", "finance", "0003", "--noinput")
        manage(url, "migrate", "documents", "--noinput")
        out = manage(url, "shell", stdin=SEED % {"keys": SCENARIOS})
        ids = json.loads(out.split("IDS=")[1].splitlines()[0])
        conn = psycopg.connect(url)
        seed_old_state(conn, ids)
        before = rates_digest(conn)
        assert before[1] == 5 * len(SCENARIOS), before
        # 2) обновление M1..M6
        manage(url, "migrate", "--noinput")
        check_upgraded(conn, ids, before, "после обновления")
        # 3) идемпотентность M2, M5, M6
        assert "IDEMPOTENT_OK" in manage(url, "shell", stdin=SHELL_IDEMPOTENCE)
        check_upgraded(conn, ids, before, "после повторного запуска M2/M5/M6")
        out = manage(
            url,
            "shell",
            stdin="from apps.core.rls import tables_missing_rls\nprint('MISSING=%r' % tables_missing_rls())",
        )
        assert "MISSING=[]" in out, out
        # 4) откат M6..M1 и повторное применение
        manage(url, "migrate", "core", "0013", "--noinput")  # M6
        manage(url, "migrate", "finance", "0003", "--noinput")  # M5..M1
        manage(url, "migrate", "core", "0012", "--noinput")  # M2
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('finance_companyfinancialsettings')")
            assert cur.fetchone()[0] is None, "таблица настроек должна исчезнуть при откате"
            cur.execute(
                "SELECT count(*) FROM information_schema.columns WHERE "
                "table_name='finance_exchangerate' AND column_name='quote_currency_id'"
            )
            assert cur.fetchone()[0] == 0
            cur.execute(
                "SELECT count(*) FROM pg_constraint WHERE conname='exchangerate_company_cur_date_uniq'"
            )
            assert cur.fetchone()[0] == 1, "прежняя уникальность курсов должна вернуться"
        conn.rollback()
        assert rates_digest(conn) == before, "курсы изменились после отката"
        manage(url, "migrate", "--noinput")
        check_upgraded(conn, ids, before, "после отката и повторного применения")
        conn.close()
        print("OK 1: обновление, идемпотентность, откат и повторное применение (курсы неизменны)")


def scenario_preflight(base_url: str) -> None:
    with TempDatabase(base_url, "logistix_preflight141") as db:
        url = db.url
        manage(url, "migrate", "core", "0013", "--noinput")
        manage(url, "migrate", "billing", "--noinput")
        manage(url, "migrate", "forwarding", "--noinput")
        manage(url, "migrate", "finance", "0005", "--noinput")
        manage(url, "migrate", "documents", "--noinput")
        out = manage(url, "shell", stdin=SEED.replace("%(keys)r", "['conflict']"))
        ids = json.loads(out.split("IDS=")[1].splitlines()[0])
        company_id = ids["conflict"]
        conn = psycopg.connect(url)
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.company_id', %s, false)", [str(company_id)])
            # старая уникальность снимается вручную: имитируем БД с дубликатами
            cur.execute(
                "ALTER TABLE finance_exchangerate DROP CONSTRAINT exchangerate_company_cur_date_uniq"
            )
            for code, day, rate in (("USD", "2026-06-01", "480"), ("USD", "2026-06-01", "481"),
                                    ("EUR", "2026-06-01", "510"), ("KZT", "2026-06-02", "1")):  # fmt: skip
                cur.execute(
                    "INSERT INTO finance_exchangerate (company_id, currency_id, date, rate, created_at) "
                    "SELECT %s, v.id, %s, %s, now() FROM core_handbookvalue v JOIN core_handbook h "
                    "ON h.id=v.handbook_id WHERE v.company_id=%s AND h.code='currency' AND v.code=%s",
                    [company_id, day, rate, company_id, code],
                )
            cur.execute("SELECT set_config('app.company_id', '', false)")
        conn.commit()
        before = rates_digest(conn)
        assert before[1] == 4
        done = manage_result(url, "migrate", "finance", "0006", "--noinput")
        text = done.stdout + done.stderr
        assert done.returncode != 0, "миграция должна остановиться"
        assert "дубликат" in text and "KZT" in text and "остановлена" in text, text
        assert rates_digest(conn) == before, "preflight изменил курсы"
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM django_migrations WHERE app='finance' AND name LIKE '0006%'"
            )
            assert cur.fetchone()[0] == 0, "миграция не должна считаться применённой"
            cur.execute(
                "SELECT count(*) FROM information_schema.columns WHERE "
                "table_name='finance_exchangerate' AND column_name='quote_currency_id'"
            )
            assert cur.fetchone()[0] == 0, "схема не должна измениться"
        conn.close()
        print("OK 2: preflight остановил миграцию на конфликте курсов, данные и схема не тронуты")
        print(text.strip().splitlines()[-6:])


SHELL_FRESH = """
import json
from apps.core.handbooks.models import HandbookValue
from apps.core.models import Role, User
from apps.core.services import create_company_with_defaults
from apps.core.tenancy import tenant_context
from apps.finance.models import CompanyFinancialSettings
user = User.objects.create_user_schema_agnostic(email="fresh@upgrade141.kz", password="s3cret-pass-1")
company = create_company_with_defaults("Fresh", user, ["forwarding"])
with tenant_context(company.id):
    s = CompanyFinancialSettings.objects.get()
    cats = HandbookValue.objects.filter(handbook__code="expense_category").count()
    perms = {r.name: [p for p in r.permissions if p.startswith("finance.") and p.split(".")[1] in
             ("close_period", "reopen_period", "adjust_closed", "backdate", "manage_settings")]
             for r in Role.objects.filter(is_system=True)}
print("FRESH=" + json.dumps({"engine": s.engine, "base": s.base_currency.code,
      "done": s.completed_status.code, "cats": cats, "admin": len(perms["Администратор"]),
      "acc": sorted(perms["Бухгалтер"]), "other": sum(len(v) for k, v in perms.items()
      if k not in ("Администратор", "Бухгалтер"))}))
"""


def scenario_fresh(base_url: str) -> None:
    with TempDatabase(base_url, "logistix_fresh141") as db:
        url = db.url
        manage(url, "migrate", "--noinput")  # чистая БД с нуля, все миграции
        out = manage(url, "makemigrations", "--check", "--dry-run")
        assert "No changes" in out, out
        out = manage(url, "shell", stdin=SHELL_FRESH)
        got = json.loads(out.split("FRESH=")[1].splitlines()[0])
        assert got == {
            "engine": "legacy", "base": "KZT", "done": "COMPLETED", "cats": 11, "admin": 5,
            "acc": ["finance.adjust_closed", "finance.backdate", "finance.close_period"], "other": 0,
        }, got  # fmt: skip
        out = manage(
            url,
            "shell",
            stdin="from apps.core.rls import tables_missing_rls\nprint('MISSING=%r' % tables_missing_rls())",
        )
        assert "MISSING=[]" in out, out
        print("OK 3: чистая БД с нуля, новая компания получает настройки, категории и права")


def main() -> int:
    base_url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    scenario_one(base_url)
    scenario_preflight(base_url)
    scenario_fresh(base_url)
    print("OK: проверка обновления подзадачи 1.4.1 пройдена")
    return 0


if __name__ == "__main__":
    sys.exit(main())
