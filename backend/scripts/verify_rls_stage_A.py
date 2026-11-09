# ruff: noqa: E501
"""RLS и миграции на данных этапа 1.5-A под РЕАЛЬНОЙ ролью logistix_app, пошагово (временная БД).

Основная БД и демо-БД не затрагиваются. Роль logistix_app создаётся настоящим deploy/db-init.sql
(NOSUPERUSER NOBYPASSRLS). Состояние ДО этапа: core 0014, billing 0002, documents 0002; две
компании с данными (A: forwarding, B: forwarding+fleet; клиент, заказ, рейс, счёт, выданные
документы всех видов). Далее миграции идут ПОШАГОВО:
  core 0015 (каталог), core 0016 (CompanyModule + RLS), core 0017 (перенос Company.modules),
  billing 0003 (тарифы), core 0018 (право company.manage_modules), documents 0003 (субъект),
  documents 0004 (заполнение субъекта).
После КАЖДОГО шага батарея rls_battery_stage_A.py выполняется под ролью приложения (fail closed,
свои данные читаются и пишутся, чужая компания не видит/не меняет/не удаляет/не вставляет/не
переносит, контекст не залипает после ROLLBACK и savepoint). Данные: CompanyModule создан,
finance и documents включены у компаний с forwarding, Company.modules совместимо, тарифы
дополнены, субъекты документов заполнены, старые поля не тронуты. Затем откат всех шагов и
повторное применение без потерь, мутационная проверка (без FORCE RLS батарея падает) и итоговый
контроль покрытия RLS. Код возврата 0 - всё пройдено.
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
from django.db import connection
from apps.core.handbooks.models import HandbookValue
from apps.core.models import Company, Role, User
from apps.core.services import create_company_with_defaults
from apps.core.tenancy import tenant_context
from apps.forwarding.models import Carrier, Client, Trip
from apps.forwarding.orders.services import create_order
from apps.core import services as core_services

# состояние ДО CompanyModule (core.0016): модули пишутся только в Company.modules
def _legacy_modules(company, modules, **kwargs):
    Company.objects.filter(pk=company.pk).update(modules=list(modules))
    company.modules = list(modules)
    return list(modules)

core_services.set_company_modules = _legacy_modules
LEGACY = {"A": ["forwarding"], "B": ["forwarding", "fleet"]}
KINDS = {  # вид -> какая связь заполнена
    "contract": "client_id", "order_request": "order_id", "carrier_order": "trip_id", "cmr": "trip_id",
    "act": "invoice_id", "invoice_print": "invoice_id", "letter": "order_id",
}
out = {}
for key in ("A", "B"):
    user = User.objects.create_user_schema_agnostic(email=f"{key.lower()}@stagea.kz", password="s3cret-pass-1")
    company = create_company_with_defaults(f"Компания {key}", user, ["forwarding"])
    Company.objects.filter(pk=company.pk).update(modules=LEGACY[key])
    with tenant_context(company.id):
        get = lambda h, c: HandbookValue.objects.get(handbook__code=h, code=c)
        client = Client.objects.create(name=f"Клиент {key}")
        carrier = Carrier.objects.create(name=f"Перевозчик {key}")
        order = create_order({"client": client}, user)
        trip = Trip.objects.create(
            number=f"T-{key}", carrier=carrier, currency=get("currency", "KZT"),
            status=get("trip_status", "PLANNED"),
        )
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO finance_invoice (company_id, direction, number, external_number, comment, "
                "client_id, currency_id, vat_rate_id, order_id, status, total_net, total_vat, "
                "total_gross, created_at, updated_at) "
                "VALUES (%s, 'out', %s, '', '', %s, %s, %s, %s, 'issued', 0, 0, 0, now(), now()) RETURNING id",
                [company.id, f"СЧ-{key}", client.id, get("currency", "KZT").id, get("vat_rate", "none").id, order.id],
            )
            invoice_id = cur.fetchone()[0]
            cur.execute("SELECT id FROM documents_documenttemplateversion WHERE company_id=%s LIMIT 1", [company.id])
            version_id = cur.fetchone()[0]
        links = {"client_id": client.id, "order_id": order.id, "trip_id": trip.id, "invoice_id": invoice_id}
        docs = {}
        for i, (kind, field) in enumerate(KINDS.items()):
            with connection.cursor() as cur:
                cur.execute(
                    f"INSERT INTO documents_issueddocument (company_id, kind, template_version_id, number, issue_date, "
                    f"language, {field}, snapshot, created_at) VALUES (%s, %s, %s, %s, '2026-11-01', 'ru', %s, '{{}}', now()) RETURNING id",
                    [company.id, kind, version_id, f"{kind}-{key}-{i}", links[field]],
                )
                docs[kind] = cur.fetchone()[0]
        # письмо без заказа: субъекта нет
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO documents_issueddocument (company_id, kind, template_version_id, number, issue_date, "
                "language, snapshot, created_at) VALUES (%s, 'letter', %s, %s, '2026-11-01', 'ru', '{}', now()) RETURNING id",
                [company.id, version_id, f"letter-free-{key}"],
            )
            docs["letter_free"] = cur.fetchone()[0]
        for role in Role.objects.filter(is_system=True):  # состояние ДО core.0018: права ещё нет
            role.permissions = [p for p in role.permissions if p != "company.manage_modules"]
            role.save(update_fields=["permissions"])
        admin_role = Role.objects.get(name="Администратор").id
    out[key] = {"company": company.id, "admin_role": admin_role, "docs": docs, "links": links,
                "modules": LEGACY[key]}
print("IDS=" + json.dumps(out))
"""

EXPECT_SUBJECT = {
    "contract": ("forwarding.client", "client_id"),
    "order_request": ("forwarding.order", "order_id"),
    "carrier_order": ("forwarding.trip", "trip_id"),
    "cmr": ("forwarding.trip", "trip_id"),
    "act": ("finance.invoice", "invoice_id"),
    "invoice_print": ("finance.invoice", "invoice_id"),
    "letter": ("forwarding.order", "order_id"),
}
# (приложение, миграция, шаг)
STEPS = [
    ("core", "0015", "A1-0015"),
    ("core", "0016", "A2-0016"),
    ("core", "0017", "A2-0017"),
    ("billing", "0003", "A2-billing-0003"),
    ("core", "0018", "A5-0018"),
    ("documents", "0003", "A7-0003"),
    ("documents", "0004", "A7-0004"),
]


def rows(url, sql, params=()):
    with psycopg.connect(url, autocommit=True) as conn:
        return conn.execute(sql, params).fetchall()


def scalar(url, sql, params=()):
    return rows(url, sql, params)[0][0]


def company_modules(url):
    return {r[0]: r[1] for r in rows(url, "SELECT id, modules FROM core_company ORDER BY id")}


def cm_state(url):
    out = {}
    for company_id, code, enabled in rows(
        url, "SELECT company_id, module_code, enabled FROM core_companymodule ORDER BY id"
    ):
        out.setdefault(company_id, {})[code] = enabled
    return out


def legacy_doc_fields(url):
    return rows(
        url,
        "SELECT id, kind, number, client_id, order_id, trip_id, invoice_id FROM documents_issueddocument ORDER BY id",
    )


PERM_APPLIED = {"value": False}  # право выдано core.0018; откат миграции его не отзывает


def battery_step(label, owner_url, app_url, battery, ids, probe_module, reports):
    if label == "A5-0018":
        PERM_APPLIED["value"] = True
    env = {
        "RLS_STEP": label,
        "RLS_IDS": json.dumps(ids),
        "OWNER_URL": owner_url,
        "RLS_EXPECT_PERM": "1" if PERM_APPLIED["value"] else "0",
    }
    result = manage(app_url, "shell", stdin=battery, env_extra=env)
    report = json.loads(result.split("RLS_REPORT=")[1].splitlines()[0])
    report["force_probe_checks"] = owner_force_probe(owner_url, owner_url, probe_module)
    reports.append(report)
    print(
        f"OK {label}: таблиц компаний {report['tables']}, под ролью logistix_app проверок "
        f"{report['checks'] + report['force_probe_checks']} (CompanyModule={report['has_company_module']}, "
        f"каталог={report['has_catalog']}, субъект={report['has_subject']})"
    )


def check_data(label, owner_url, ids, initial):
    """Проверки данных на текущем шаге (владелец БД, без RLS)."""
    a, b = ids["A"]["company"], ids["B"]["company"]
    plans = {r[0]: r[1] for r in rows(owner_url, "SELECT code, modules FROM billing_plan")}
    if label in ("A2-0017", "A2-billing-0003", "A5-0018", "A7-0003", "A7-0004", "final"):
        state = cm_state(owner_url)
        # core.0020 (logistics) применяется только в итоговом состоянии
        more = {"logistics": True} if label == "final" else {}
        more_set = {"logistics"} if label == "final" else set()
        assert state[a] == {"forwarding": True, "finance": True, "documents": True, **more}, state[a]
        assert state[b] == {
            "forwarding": True,
            "fleet": True,
            "finance": True,
            "documents": True,
            **more,
        }, state[b]
        assert all("core" not in codes for codes in state.values()), "core не хранится"
        modules = company_modules(owner_url)
        assert modules[a][:1] == initial[a] and set(modules[a]) == {
            "forwarding",
            "finance",
            "documents",
            *more_set,
        }, modules[a]
        assert modules[b][:2] == initial[b] and set(modules[b]) == {
            "forwarding",
            "fleet",
            "finance",
            "documents",
            *more_set,
        }, modules[b]
        for company_id, codes in state.items():  # проекция совпадает с CompanyModule
            assert set(modules[company_id]) == {c for c, on in codes.items() if on}
    if label in ("A2-billing-0003", "A5-0018", "A7-0003", "A7-0004", "final"):
        for code in ("start", "business", "lifetime"):
            assert {"forwarding", "finance", "documents"} <= set(plans[code]), plans[code]
    else:
        for code in ("start", "business", "lifetime"):
            assert "finance" not in plans[code], plans[code]
    if label in ("A7-0004", "final"):
        for key in ("A", "B"):
            for kind, doc_id in ids[key]["docs"].items():
                subject = rows(
                    owner_url,
                    "SELECT subject_type, subject_id FROM documents_issueddocument WHERE id=%s",
                    [doc_id],
                )[0]
                if kind == "letter_free":
                    assert subject == (None, None), subject
                else:
                    sub_type, field = EXPECT_SUBJECT[kind]
                    assert subject == (sub_type, ids[key]["links"][field]), (kind, subject)
    elif label == "A7-0003":
        assert (
            scalar(
                owner_url,
                "SELECT count(*) FROM documents_issueddocument WHERE subject_type IS NOT NULL",
            )
            == 0
        )


def main() -> int:
    base_url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    battery = (BACKEND / "scripts" / "rls_battery_stage_A.py").read_text()
    reports = []
    with TempDatabase(base_url, "logistix_rlsA") as db:
        owner_url = db.url
        apply_db_init(owner_url)
        app_url = with_user(owner_url, APP_ROLE, APP_PASSWORD)
        row = rows(
            owner_url,
            "SELECT rolsuper, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname=%s",
            [APP_ROLE],
        )[0]
        assert row == (False, False, True), f"роль {APP_ROLE}: {row}"
        # состояние ДО этапа 1.5-A
        manage(owner_url, "migrate", "core", "0014", "--noinput")
        manage(owner_url, "migrate", "billing", "0002", "--noinput")
        manage(owner_url, "migrate", "forwarding", "--noinput")
        manage(owner_url, "migrate", "finance", "--noinput")
        manage(owner_url, "migrate", "documents", "0002", "--noinput")
        # создание компаний идёт кодом приложения (тариф по умолчанию читается из данных тарифа),
        # поэтому схема тарифов на время посева последняя; затем возврат к состоянию «до этапа»
        manage(owner_url, "migrate", "billing", "--noinput")
        out = manage(owner_url, "shell", stdin=SEED)
        manage(owner_url, "migrate", "billing", "0002", "--noinput")
        ids = json.loads(out.split("IDS=")[1].splitlines()[0])
        initial = {
            ids["A"]["company"]: ids["A"]["modules"],
            ids["B"]["company"]: ids["B"]["modules"],
        }
        before_plans = rows(owner_url, "SELECT code, modules FROM billing_plan ORDER BY id")
        before_docs = legacy_doc_fields(owner_url)
        assert len(before_docs) == 2 * 8, before_docs
        probe_module = load_module(
            BACKEND / "apps" / "finance" / "migrations" / "0005_income_expense_ledger.py", "m0005"
        )
        battery_step("base", owner_url, app_url, battery, ids, probe_module, reports)

        # --- прямой проход пошагово ---
        for app, name, label in STEPS:
            manage(owner_url, "migrate", app, name, "--noinput")
            check_data(label, owner_url, ids, initial)
            battery_step(label, owner_url, app_url, battery, ids, probe_module, reports)
        assert legacy_doc_fields(owner_url) == before_docs, (
            "старые поля выданных документов изменились"
        )

        # --- мутационная проверка: без FORCE RLS батарея обязана упасть ---
        with psycopg.connect(owner_url, autocommit=True) as conn:
            conn.execute("ALTER TABLE core_companymodule NO FORCE ROW LEVEL SECURITY")
        try:
            battery_step("мутация", owner_url, app_url, battery, ids, probe_module, [])
            raise AssertionError("батарея не заметила снятие FORCE RLS")
        except RuntimeError as exc:
            assert "ENABLE+FORCE RLS" in str(exc), exc
        finally:
            with psycopg.connect(owner_url, autocommit=True) as conn:
                conn.execute("ALTER TABLE core_companymodule FORCE ROW LEVEL SECURITY")
        print("OK мутация: при снятии FORCE RLS батарея падает")

        # --- откат всех шагов: данные без потерь ---
        manage(owner_url, "migrate", "documents", "0003", "--noinput")
        assert (
            scalar(
                owner_url,
                "SELECT count(*) FROM documents_issueddocument WHERE subject_type IS NOT NULL",
            )
            == 0
        )
        assert legacy_doc_fields(owner_url) == before_docs
        battery_step("A7-0003", owner_url, app_url, battery, ids, probe_module, reports)
        manage(owner_url, "migrate", "documents", "0002", "--noinput")
        assert "subject_type" not in {
            r[0]
            for r in rows(
                owner_url,
                "SELECT column_name FROM information_schema.columns WHERE table_name='documents_issueddocument'",
            )
        }
        assert legacy_doc_fields(owner_url) == before_docs, "откат documents потерял документы"
        battery_step("A7-откат-0002", owner_url, app_url, battery, ids, probe_module, reports)
        manage(owner_url, "migrate", "billing", "0002", "--noinput")
        assert (
            rows(owner_url, "SELECT code, modules FROM billing_plan ORDER BY id") == before_plans
        ), "откат billing изменил тарифы"
        manage(owner_url, "migrate", "core", "0016", "--noinput")  # откат 0018 (noop) и 0017
        assert scalar(owner_url, "SELECT count(*) FROM core_companymodule") == 0, (
            "откат 0017 оставил строки"
        )
        modules_back = company_modules(owner_url)
        assert modules_back == initial, f"откат 0017 не вернул Company.modules: {modules_back}"
        battery_step(
            "A2-0016-после-отката", owner_url, app_url, battery, ids, probe_module, reports
        )
        manage(owner_url, "migrate", "core", "0014", "--noinput")  # снимает таблицы 0016 и 0015
        assert not rows(
            owner_url,
            "SELECT 1 FROM pg_class WHERE relname IN ('core_companymodule','core_module','core_activityprofile')",
        )
        assert company_modules(owner_url) == initial
        battery_step("base-после-отката", owner_url, app_url, battery, ids, probe_module, reports)

        # --- повторное применение на тех же данных ---
        manage(owner_url, "migrate", "--noinput")
        check_data("final", owner_url, ids, initial)
        assert legacy_doc_fields(owner_url) == before_docs
        battery_step("final", owner_url, app_url, battery, ids, probe_module, reports)
        out = manage(
            owner_url,
            "shell",
            stdin="from apps.core.rls import tables_missing_rls\nprint('MISSING=%r' % tables_missing_rls())",
        )
        assert "MISSING=[]" in out, out
        manage(owner_url, "makemigrations", "--check", "--dry-run")
        print(
            "tables_missing_rls() == [] и makemigrations --check чисто после всех миграций этапа A"
        )
    total = sum(r["checks"] + r["force_probe_checks"] for r in reports)
    print(
        f"OK: этап 1.5-A: RLS под ролью {APP_ROLE} и миграции на данных проверены (шагов {len(reports)}, проверок {total})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
