# ruff: noqa: E501
"""Пошаговая проверка RLS под РЕАЛЬНОЙ ролью logistix_app для finance.0010 (временная БД).

Основная БД и демо-БД не затрагиваются. Роль logistix_app создаётся настоящим deploy/db-init.sql
(NOSUPERUSER NOBYPASSRLS). Миграции идут ПОШАГОВО; после каждого шага батарея
rls_battery_task_1_4_14.py выполняется под ролью приложения:
  (а) fail closed без контекста (чтение, изменение, удаление, вставка) у счетов, оплат, снимков и
      строк переоценки;
  (б) свои данные читаются и ПИШУТСЯ (в том числе сервисом create_revaluation и колонки снимков
      курса счёта и оплаты);
  (в) чужая компания не видит, не меняет, не удаляет, не вставляет и не переносит строки;
  (г) после ROLLBACK, отката точки сохранения и при повторном использовании соединения контекст
      не залипает; откат записи снимков не оставляет следов;
  (д) FORCE ROW LEVEL SECURITY включён у всех таблиц компаний и действует на владельца (проба).
Дополнительно: на БД с данными миграция 0010 не меняет прежние колонки счетов и оплат, новые
колонки пусты; откат 0010 -> 0009 убирает колонки и таблицы без потери прежних данных; повторное
применение проходит; мутационная проверка (снятие FORCE - батарея падает). Код возврата 0 - ОК.
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

# состояние ДО подзадачи 1.4.14: finance 0009. Счета и оплаты вставляются SQL-ом (в модели уже есть
# колонки 0010, которых в схеме 0009 нет); клиенты/перевозчики - ORM (их схема не менялась).
SEED = """
import json
from apps.core.handbooks.models import HandbookValue
from apps.core.models import User
from apps.core.services import create_company_with_defaults
from apps.core.tenancy import tenant_context
from apps.forwarding.models import Carrier
from django.db import connection

out = {}
for key in ("A", "B"):
    user = User.objects.create_user_schema_agnostic(email=f"{key.lower()}@rls1414.kz", password="s3cret-pass-1")
    company = create_company_with_defaults(f"Компания {key}", user, ["forwarding"])
    with tenant_context(company.id):
        get = lambda h, c: HandbookValue.objects.get(handbook__code=h, code=c)
        carrier = Carrier.objects.create(name=f"Перевозчик {key}")
        currency, vat = get("currency", "KZT").id, get("vat_rate", "none").id
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO finance_invoice (company_id, direction, number, external_number, carrier_id, "
                "currency_id, vat_rate_id, issue_date, due_date, rate_to_kzt, status, total_net, total_vat, "
                "total_gross, comment, created_at, updated_at) VALUES (%s, 'in', %s, '', %s, %s, %s, "
                "'2026-05-01', '2026-05-15', 1, 'issued', 100, 0, 100, '', now(), now()) RETURNING id",
                [company.id, f"IN-{key}-1", carrier.id, currency, vat],
            )
            invoice = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO finance_payment (company_id, invoice_id, date, amount, rate_to_kzt, method, "
                "payment_ref, comment, created_at) VALUES (%s, %s, '2026-05-20', 40, 1, 'bank', '', '', now()) "
                "RETURNING id",
                [company.id, invoice],
            )
            payment = cur.fetchone()[0]
        out[key] = {"company": company.id, "invoice": invoice, "payment": payment, "currency": currency}
print("IDS=" + json.dumps(out))
"""


def scalar(url, sql, params=()):
    with psycopg.connect(url, autocommit=True) as conn:
        return conn.execute(sql, params).fetchone()[0]


def columns(url, table):
    with psycopg.connect(url, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name=%s", [table]
        ).fetchall()
    return {r[0] for r in rows}


def tables(url):
    with psycopg.connect(url, autocommit=True) as conn:
        return {
            r[0]
            for r in conn.execute(
                "SELECT relname FROM pg_class WHERE relkind='r' AND relname LIKE 'finance_fxreval%'"
            ).fetchall()
        }


def snapshot(url):
    """Прежние колонки счетов и оплат (для сравнения до/после миграций)."""
    with psycopg.connect(url, autocommit=True) as conn:
        invoices = conn.execute(
            "SELECT id, company_id, direction, number, carrier_id, currency_id, vat_rate_id, issue_date, "
            "due_date, rate_to_kzt, status, total_net, total_vat, total_gross FROM finance_invoice ORDER BY id"
        ).fetchall()
        payments = conn.execute(
            "SELECT id, company_id, invoice_id, date, amount, rate_to_kzt, method FROM finance_payment ORDER BY id"
        ).fetchall()
    return invoices, payments


def battery_step(label, owner_url, app_url, battery, ids, probe_module, reports):
    env = {"RLS_STEP": label, "RLS_IDS": json.dumps(ids), "OWNER_URL": owner_url}
    result = manage(app_url, "shell", stdin=battery, env_extra=env)
    report = json.loads(result.split("RLS_REPORT=")[1].splitlines()[0])
    report["force_probe_checks"] = owner_force_probe(owner_url, owner_url, probe_module)
    reports.append(report)
    print(
        f"OK {label}: таблиц компаний {report['tables']}, под ролью logistix_app проверок "
        f"{report['checks'] + report['force_probe_checks']} "
        f"(снимки курса={report['has_snapshots']}, таблицы переоценки={report['has_revaluation_tables']})"
    )


def main() -> int:
    base_url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    battery = (BACKEND / "scripts" / "rls_battery_task_1_4_14.py").read_text()
    reports = []
    with TempDatabase(base_url, "logistix_rls1414") as db:
        owner_url = db.url
        apply_db_init(owner_url)
        app_url = with_user(owner_url, APP_ROLE, APP_PASSWORD)
        with psycopg.connect(owner_url) as conn:
            row = conn.execute(
                "SELECT rolsuper, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname=%s",
                [APP_ROLE],
            ).fetchone()
        assert row == (False, False, True), f"роль {APP_ROLE}: {row}"

        # состояние до подзадачи: всё, кроме finance.0010
        for app in ("core", "billing", "forwarding", "documents"):
            manage(owner_url, "migrate", app, "--noinput")
        manage(owner_url, "migrate", "finance", "0009", "--noinput")
        assert "base_currency_id" not in columns(owner_url, "finance_invoice")
        assert not tables(owner_url)
        out = manage(owner_url, "shell", stdin=SEED)
        ids = json.loads(out.split("IDS=")[1].splitlines()[0])
        probe_module = load_module(
            BACKEND / "apps" / "finance" / "migrations" / "0005_income_expense_ledger.py", "m0005"
        )
        before = snapshot(owner_url)
        assert len(before[0]) == 2 and len(before[1]) == 2

        # --- состояние 0009 (до 0010): базовая батарея ---
        battery_step("0009", owner_url, app_url, battery, ids, probe_module, reports)

        # --- 0010 ---
        manage(owner_url, "migrate", "finance", "0010", "--noinput")
        assert snapshot(owner_url) == before, "0010 изменила прежние данные счетов и оплат"
        assert {"base_currency_id", "rate_to_base", "rate_to_base_date"} <= columns(
            owner_url, "finance_invoice"
        )
        assert {"base_currency_id", "rate_to_base", "rate_to_base_date"} <= columns(
            owner_url, "finance_payment"
        )
        assert tables(owner_url) == {"finance_fxrevaluation", "finance_fxrevaluationline"}
        assert (
            scalar(
                owner_url,
                "SELECT count(*) FROM finance_invoice WHERE base_currency_id IS NOT NULL OR rate_to_base IS NOT NULL",
            )
            == 0
        ), "существующие счета получили снимок"
        assert (
            scalar(
                owner_url,
                "SELECT count(*) FROM finance_payment WHERE base_currency_id IS NOT NULL OR rate_to_base IS NOT NULL",
            )
            == 0
        ), "существующие оплаты получили снимок"
        battery_step("0010", owner_url, app_url, battery, ids, probe_module, reports)

        # мутационная проверка: без FORCE батарея обязана упасть (проба чувствительна)
        with psycopg.connect(owner_url, autocommit=True) as conn:
            conn.execute("ALTER TABLE finance_fxrevaluation NO FORCE ROW LEVEL SECURITY")
        try:
            battery_step("0010-мутация", owner_url, app_url, battery, ids, probe_module, [])
            raise AssertionError("батарея не заметила снятие FORCE RLS")
        except RuntimeError as exc:
            assert "ENABLE+FORCE RLS" in str(exc), exc
        finally:
            with psycopg.connect(owner_url, autocommit=True) as conn:
                conn.execute("ALTER TABLE finance_fxrevaluation FORCE ROW LEVEL SECURITY")
        print("OK мутация: при снятии FORCE RLS батарея падает")

        # --- откат 0010 -> 0009: колонки и таблицы убраны, прежние данные на месте ---
        with psycopg.connect(owner_url, autocommit=True) as conn:  # значения в новых колонках
            conn.execute(
                "UPDATE finance_invoice SET base_currency_id=currency_id, rate_to_base=1, rate_to_base_date=issue_date"
            )
        manage(owner_url, "migrate", "finance", "0009", "--noinput")
        assert "rate_to_base" not in columns(owner_url, "finance_invoice")
        assert "rate_to_base" not in columns(owner_url, "finance_payment")
        assert not tables(owner_url)
        assert snapshot(owner_url) == before, "откат 0010 повредил прежние данные"
        print(
            "OK откат 0010 -> 0009: колонки снимков и таблицы переоценки удалены, данные без потерь"
        )
        battery_step("0009-после-отката", owner_url, app_url, battery, ids, probe_module, reports)

        # --- повторное применение на данных ---
        manage(owner_url, "migrate", "finance", "0010", "--noinput")
        assert snapshot(owner_url) == before, "повторное применение изменило данные"
        battery_step("0010-повторно", owner_url, app_url, battery, ids, probe_module, reports)

        # --- итоговый контроль покрытия средствами приложения и согласованность моделей ---
        manage(owner_url, "migrate", "--noinput")  # таблицы поздних этапов появляются позже
        out = manage(
            owner_url,
            "shell",
            stdin="from apps.core.rls import tables_missing_rls\nprint('MISSING=%r' % tables_missing_rls())",
        )
        assert "MISSING=[]" in out, out
        manage(owner_url, "makemigrations", "--check", "--dry-run")
        print("tables_missing_rls() == [] и makemigrations --check чисто после 0010")
    total = sum(r["checks"] + r["force_probe_checks"] for r in reports)
    print(
        f"OK: 1.4.14 RLS под ролью {APP_ROLE} проверена после finance.0010 (шагов {len(reports)}, проверок {total})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
