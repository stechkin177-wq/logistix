# ruff: noqa: E501
"""RLS новых таблиц под РЕАЛЬНОЙ ролью logistix_app после КАЖДОЙ миграции M1..M6 (временная БД).

Основная БД и демо-БД не затрагиваются. Нужны права CREATE DATABASE/CREATE ROLE (владелец -
суперпользователь, как в docker-compose). Роль logistix_app и её права создаются настоящим
deploy/db-init.sql (NOSUPERUSER NOBYPASSRLS, только DML, пароль разработки). Миграции идут
пошагово; после каждого шага выполняется rls_battery_task_1_4_1.py под ролью приложения:
  (а) без контекста компании - 0 строк, запись отклонена (fail closed);
  (б) в контексте A - чтение и запись своих строк новых таблиц;
  (в) компания B не видит, не меняет, не удаляет, не вставляет и не переносит строки A;
  (г) сброс контекста после ROLLBACK транзакции / точки сохранения и при повторном использовании
      соединения не оставляет «подвешенного» контекста;
  (д) FORCE ROW LEVEL SECURITY действует на владельца таблицы (проба с обычной ролью-владельцем и
      SQL политики из самой миграции) и включён у всех таблиц.
Код возврата 0 - все шаги пройдены.
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

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

# (приложение, имя миграции, название шага, новые таблицы шага)
STEPS = [
    ("finance", "0004", "M1", ["finance_companyfinancialsettings", "finance_financialperiod", "finance_financialperiodevent"]),
    ("core", "0013", "M2", []),
    ("finance", "0005", "M3", ["finance_income", "finance_incometrip", "finance_expense", "finance_expenseallocation", "finance_expenseinvoiceallocation", "finance_financemigrationrun", "finance_financemigrationissue"]),
    ("finance", "0006", "M4", []),
    ("finance", "0007", "M5", []),
    ("core", "0014", "M6", []),
]  # fmt: skip

SEED = """
import json
from datetime import date
from django.db import connection
from apps.core.handbooks import defaults
from apps.core.handbooks.models import HandbookValue
from apps.core.models import Membership, User
from apps.core.services import create_company_with_defaults
from apps.core.signals import company_created
from apps.core.tenancy import tenant_context
from apps.forwarding.models import Carrier, Client, Trip
from apps.forwarding.orders.services import create_order
from apps.finance import engine as finance_engine

# состояние ДО подзадачи: таблицы finance.CompanyFinancialSettings ещё нет (создаётся в finance.0004),
# поэтому определение режима учёта (хуки 1.4.4+) на этом шаге подменяется на прежний режим
finance_engine.company_engine = lambda company_id: "legacy"
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
for key in ("A", "B"):
    user = User.objects.create_user(email=f"{key.lower()}@rls141.kz", password="s3cret-pass-1")
    company = create_company_with_defaults(f"Компания {key}", user, ["forwarding"])
    with tenant_context(company.id):
        get = lambda h, c: HandbookValue.objects.get(handbook__code=h, code=c)
        client = Client.objects.create(name=f"Клиент {key}")
        carrier = Carrier.objects.create(name=f"Перевозчик {key}")
        order = create_order({"client": client}, user)
        trip = Trip.objects.create(
            number=f"T-{key}", carrier=carrier, currency=get("currency", "KZT"),
            status=get("trip_status", "PLANNED"),
        )
        # Invoice - сырым SQL: модель описывает последнюю схему (колонки finance.0010), а БД на finance.0003
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO finance_invoice (company_id, direction, number, external_number, comment, "
                "carrier_id, currency_id, vat_rate_id, order_id, status, total_net, total_vat, "
                "total_gross, created_at, updated_at) "
                "VALUES (%s, 'in', '', '', '', %s, %s, %s, %s, 'draft', 0, 0, 0, now(), now()) RETURNING id",
                [company.id, carrier.id, get("currency", "KZT").id, get("vat_rate", "none").id, order.id],
            )
            invoice_id = cur.fetchone()[0]
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO finance_invoiceitem (company_id, invoice_id, title, amount_net) "
                "VALUES (%s, %s, 'Позиция', 100) RETURNING id",
                [company.id, invoice_id],
            )
            item = cur.fetchone()[0]
        out[key] = {
            "company": company.id, "order": order.id, "trip": trip.id, "item": item,
            "currency": get("currency", "KZT").id, "usd": get("currency", "USD").id,
            "eur": get("currency", "EUR").id,
        }
print("IDS=" + json.dumps(out))
"""  # noqa: E501


def owner_force_probe(db_url: str, owner_url: str, finance_0005) -> int:
    """(д) FORCE RLS действует на ВЛАДЕЛЬЦА: таблица обычной (не супер) роли с SQL политики из миграции."""
    role = "rls_probe_owner_141"
    with psycopg.connect(owner_url, autocommit=True) as admin:
        admin.execute(f"DROP ROLE IF EXISTS {role}")
        admin.execute(f"CREATE ROLE {role} LOGIN PASSWORD 'probe' NOSUPERUSER NOBYPASSRLS")
        admin.execute(f"GRANT CREATE ON SCHEMA public TO {role}")
    probe_url = with_user(owner_url, role, "probe")
    checks = 0
    try:
        with psycopg.connect(probe_url, autocommit=True) as conn:
            conn.execute(
                "CREATE TABLE rls_probe (id serial primary key, company_id int not null, v text)"
            )
            statements = []
            for op in finance_0005._rls("rls_probe").sql:
                statements.append(op)
            for sql in statements:
                conn.execute(sql)
            conn.execute("SELECT set_config('app.company_id', '1', false)")
            conn.execute("INSERT INTO rls_probe (company_id, v) VALUES (1, 'a')")
            n = conn.execute("SELECT count(*) FROM rls_probe").fetchone()[0]
            assert n == 1, "владелец видит свои строки в своём контексте"
            conn.execute("SELECT set_config('app.company_id', '', false)")
            n = conn.execute("SELECT count(*) FROM rls_probe").fetchone()[0]
            assert n == 0, "FORCE RLS: владелец без контекста не должен видеть строки"
            conn.execute("SELECT set_config('app.company_id', '2', false)")
            assert conn.execute("SELECT count(*) FROM rls_probe").fetchone()[0] == 0
            try:
                conn.execute("INSERT INTO rls_probe (company_id, v) VALUES (1, 'x')")
                raise AssertionError("владелец смог вставить строку чужой компании")
            except psycopg.errors.InsufficientPrivilege:
                pass
            # без FORCE владелец обошёл бы политику: доказываем, что проба чувствительна
            conn.execute("ALTER TABLE rls_probe NO FORCE ROW LEVEL SECURITY")
            conn.execute("SELECT set_config('app.company_id', '', false)")
            assert conn.execute("SELECT count(*) FROM rls_probe").fetchone()[0] == 1
            checks += 5
            conn.execute("DROP TABLE rls_probe")
    finally:
        with psycopg.connect(owner_url, autocommit=True) as admin:
            admin.execute(f"DROP OWNED BY {role}")
            admin.execute(f"DROP ROLE IF EXISTS {role}")
    return checks


def load_module(path: Path, name: str):
    # файл миграции читает django.conf.settings (swappable_dependency): настройки нужны, setup() нет
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ.setdefault("DJANGO_DEBUG", "true")
    sys.path.insert(0, str(BACKEND))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    base_url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    battery = (BACKEND / "scripts" / "rls_battery_task_1_4_1.py").read_text()
    reports = []
    with TempDatabase(base_url, "logistix_rls141") as db:
        owner_url = db.url
        apply_db_init(owner_url)  # роль logistix_app и права, как в проде (до миграций)
        app_url = with_user(owner_url, APP_ROLE, APP_PASSWORD)
        with psycopg.connect(owner_url) as conn:
            row = conn.execute(
                "SELECT rolsuper, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname=%s",
                [APP_ROLE],
            ).fetchone()
        assert row == (False, False, True), f"роль {APP_ROLE}: {row}"
        # состояние ДО подзадачи
        manage(owner_url, "migrate", "core", "0012", "--noinput")
        manage(owner_url, "migrate", "billing", "--noinput")
        manage(owner_url, "migrate", "forwarding", "--noinput")
        manage(owner_url, "migrate", "finance", "0003", "--noinput")
        manage(owner_url, "migrate", "documents", "--noinput")
        out = manage(owner_url, "shell", stdin=SEED)
        ids = json.loads(out.split("IDS=")[1].splitlines()[0])
        finance_0005 = load_module(
            BACKEND / "apps" / "finance" / "migrations" / "0005_income_expense_ledger.py", "m0005"
        )
        # исходное состояние тоже проверяется (роль и права на уже созданные таблицы)
        steps = [("-", "-", "base", [])] + STEPS
        for app, name, label, new_tables in steps:
            if label != "base":
                manage(owner_url, "migrate", app, name, "--noinput")
            env = {"RLS_STEP": label, "RLS_IDS": json.dumps(ids), "OWNER_URL": owner_url,
                   "RLS_NEW_TABLES": json.dumps(new_tables)}  # fmt: skip
            result = manage(app_url, "shell", stdin=battery, env_extra=env)
            report = json.loads(result.split("RLS_REPORT=")[1].splitlines()[0])
            report["force_probe_checks"] = owner_force_probe(db.url, owner_url, finance_0005)
            reports.append(report)
            print(
                f"OK {label} ({app} {name}): таблиц компаний {report['tables']}, под ролью "
                f"{report['role'][0]} проверок {report['checks'] + report['force_probe_checks']}, "
                f"таблиц с данными скрыто без контекста {report['tables_with_data_hidden_without_context']}, "
                f"новых таблиц с записью {len(report['new_tables_with_rows'])}"
            )
        # финальный контроль покрытия средствами приложения: модели описывают последнюю схему
        # (в т.ч. finance.0010 из 1.4.14), поэтому БД доводится до неё перед сверкой
        manage(owner_url, "migrate", "--noinput")
        out = manage(
            owner_url,
            "shell",
            stdin="from apps.core.rls import tables_missing_rls\nprint('MISSING=%r' % tables_missing_rls())",
        )
        assert "MISSING=[]" in out, out
        print("tables_missing_rls() == [] после M6")
    print("OK: RLS под ролью logistix_app проверена после каждой миграции M1..M6")
    return 0


if __name__ == "__main__":
    sys.exit(main())
