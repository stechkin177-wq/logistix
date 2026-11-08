# ruff: noqa: E501
"""Проверка RLS под РЕАЛЬНОЙ ролью logistix_app; выполняется внутри `manage.py shell`.

Подключение приложения (DATABASE_URL) - роль logistix_app (не суперпользователь, без BYPASSRLS).
Владелец таблиц - OWNER_URL (только для сравнения «сколько строк существует на самом деле»).
Параметры берутся из окружения: RLS_STEP (имя шага), RLS_IDS (JSON), OWNER_URL.
Результат - одна строка `RLS_REPORT={json}`; любое нарушение - исключение (код возврата не 0).
"""

import copy
import json
import os
from datetime import date

import psycopg
from django.db import DatabaseError, connection, transaction

from apps.core.handbooks.models import HandbookValue
from apps.core.tenancy import tenant_context

STEP = os.environ["RLS_STEP"]
IDS = json.loads(os.environ["RLS_IDS"])  # {"A": {...}, "B": {...}}
OWNER_URL = os.environ["OWNER_URL"]
APP_URL = os.environ["DATABASE_URL"]
A, B = IDS["A"]["company"], IDS["B"]["company"]
REPORT = {"step": STEP, "checks": 0}
NEW_TABLES = json.loads(os.environ.get("RLS_NEW_TABLES", "[]"))


def ok(cond, message):
    REPORT["checks"] += 1
    if not cond:
        raise AssertionError(f"[{STEP}] {message}")


def raw(url):
    return psycopg.connect(url, autocommit=False)


def inventory(conn):
    """Все таблицы схемы public со столбцом company_id (кроме служебных Django)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
            "JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid "
            "WHERE n.nspname='public' AND c.relkind='r' AND a.attname='company_id' "
            "AND NOT a.attisdropped ORDER BY 1"
        )
        rows = cur.fetchall()
        cur.execute(
            "SELECT tablename, policyname, cmd, qual, with_check FROM pg_policies "
            "WHERE schemaname='public' AND policyname='tenant_isolation'"
        )
        policies = {r[0]: r for r in cur.fetchall()}
    conn.rollback()
    return rows, policies


def guc(cur):
    cur.execute("SELECT current_setting('app.company_id', true)")
    return cur.fetchone()[0]


# --- 0. роль и покрытие -------------------------------------------------------------------

app = raw(APP_URL)
owner = raw(OWNER_URL)
with app.cursor() as cur:
    cur.execute(
        "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
    )
    who = cur.fetchone()
app.rollback()
ok(who == ("logistix_app", False, False), f"роль приложения {who}")
REPORT["role"] = list(who)

from apps.core.rls import tenant_tables  # noqa: E402

# Не TenantModel (принятый пробел, см. apps/core/rls.py): таблицы со столбцом company_id без RLS
KNOWN_NON_TENANT = {"billing_subscription", "core_membership", "core_companybranding"}
all_info, policies = inventory(owner)
expected = set(tenant_tables())
present = {t[0] for t in all_info}
ok(
    present - expected <= KNOWN_NON_TENANT,
    f"таблицы с company_id вне TenantModel: {present - expected}",
)
tables_info = [t for t in all_info if t[0] in expected]
tables = [t[0] for t in tables_info]
if STEP == "M6":
    # таблицы finance.0010 (1.4.14) и core.0016 (этап 1.5-A: CompanyModule) появляются позже
    # шагов этого скрипта: до M6 их в БД нет
    LATER_TABLES = {
        "finance_fxrevaluation",
        "finance_fxrevaluationline",
        "core_companymodule",
        "drivers_driver",  # этап 2.1
        "drivers_driverdocument",
        "fleet_vehicle",  # этап 2.2
        "fleet_vehicledocument",
        "fleet_insurance",
        "fleet_mileagereading",  # этап 2.4
        "fleet_servicerecord",
        "fleet_fuelfill",
    }
    ok(
        expected - LATER_TABLES <= present,
        f"таблицы TenantModel отсутствуют в БД: {expected - LATER_TABLES - present}",
    )
ok(len(tables) >= 20, f"найдено таблиц компаний: {len(tables)}")
for name, enabled, forced in tables_info:
    ok(enabled and forced, f"{name}: ENABLE+FORCE RLS ({enabled}, {forced})")
    pol = policies.get(name)
    ok(pol is not None and pol[2] == "ALL", f"{name}: политика tenant_isolation")
    ok("app.company_id" in pol[3] and "app.company_id" in pol[4], f"{name}: USING и WITH CHECK")
for t in NEW_TABLES:
    ok(t in tables, f"новая таблица {t} существует и имеет company_id")
REPORT["tables"] = len(tables)

# --- 1. (а) без контекста: 0 строк / ошибка ---------------------------------------------------

meaningful = []
for t in tables:
    with owner.cursor() as cur:
        cur.execute(f'SELECT count(*) FROM "{t}"')
        total = cur.fetchone()[0]
    owner.rollback()
    with app.cursor() as cur:
        ok(guc(cur) in (None, ""), "на новом соединении контекст пуст")
        cur.execute(f'SELECT count(*) FROM "{t}"')
        ok(cur.fetchone()[0] == 0, f"{t}: без контекста видно строк != 0")
        cur.execute("SELECT set_config('app.company_id', '', false)")
        cur.execute(f'SELECT count(*) FROM "{t}"')
        ok(cur.fetchone()[0] == 0, f"{t}: с пустым контекстом видно строк != 0")
    app.rollback()
    if total:
        meaningful.append(t)
REPORT["tables_with_data_hidden_without_context"] = len(meaningful)
ok(len(meaningful) >= 10, "проверка без контекста должна касаться таблиц с данными")

# без контекста нельзя записать в таблицу компаний (fail closed на запись)
try:
    with app.cursor() as cur:
        cur.execute("INSERT INTO core_department (company_id, name) VALUES (%s, 'x')", [A])
    ok(False, "запись без контекста должна быть отклонена")
except psycopg.errors.InsufficientPrivilege as exc:
    ok("row-level security" in str(exc), f"ожидалась ошибка RLS: {exc}")
finally:
    app.rollback()

# --- 2. (б)/(в) на ORM под ролью приложения: создание цепочек своих строк ---------------------

from apps.finance import models as F  # noqa: E402


def trim_models_to_db_schema():
    """Батарея идёт по промежуточным шагам миграций, а модели описывают последнюю схему: столбцы,
    которых на этом шаге ещё нет (finance.0008..0010), убираются из _meta модели приложения finance,
    чтобы ORM не обращался к ним (процесс одноразовый, на данные и проверки RLS это не влияет)."""
    from django.apps import apps as django_apps

    with owner.cursor() as cur:
        cur.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name LIKE 'finance\\_%'"
        )
        present = {}
        for table_name, column_name in cur.fetchall():
            present.setdefault(table_name, set()).add(column_name)
    owner.rollback()
    for model in django_apps.get_app_config("finance").get_models():
        cols = present.get(model._meta.db_table)
        if cols is None:
            continue
        for field in list(model._meta.local_fields):
            if field.column not in cols:
                model._meta.local_fields.remove(field)
        model._meta._expire_cache()


trim_models_to_db_schema()


def exists(table):
    with owner.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", [table])
        res = cur.fetchone()[0] is not None
    owner.rollback()
    return res


def category(company):
    with tenant_context(company):
        v = HandbookValue.objects.filter(handbook__code="expense_category", code="OTHER").first()
    return v.pk if v else None


def chains(company, ids):
    """Создаёт строки всех существующих на этом шаге новых таблиц компании; возвращает объекты."""
    made = []

    def add(obj):
        obj.save()
        made.append(obj)
        return obj

    with tenant_context(company):
        if exists("finance_companyfinancialsettings"):
            if not F.CompanyFinancialSettings.objects.exists():
                add(F.CompanyFinancialSettings(company_id=company))
        if exists("finance_financialperiod"):
            period = add(F.FinancialPeriod(company_id=company, year=2026, month=5))
            add(F.FinancialPeriodEvent(company_id=company, period=period, action="close"))
            add(
                F.FinancialPeriodEvent(
                    company_id=company, period=period, action="reopen", reason="проверка"
                )
            )
        if exists("finance_income"):
            income = add(
                F.Income(
                    company_id=company, order_id=ids["order"], kind="service", title="Услуга",
                    amount=10, currency_id=ids["currency"],
                )
            )  # fmt: skip
            add(F.IncomeTrip(company_id=company, income=income, trip_id=ids["trip"]))
            cat = category(company)
            ok(cat is not None, "справочник категорий расходов доступен под ролью")
            expense = add(
                F.Expense(
                    company_id=company, kind="other", title="Расход", category_id=cat,
                    amount=5, currency_id=ids["currency"], expense_date=date(2026, 6, 1),
                    source="manual",
                )
            )  # fmt: skip
            add(
                F.ExpenseAllocation(
                    company_id=company, expense=expense, order_id=ids["order"], amount=5
                )
            )
            add(
                F.ExpenseInvoiceAllocation(
                    company_id=company, expense=expense, invoice_item_id=ids["item"], amount=1
                )
            )
            run = add(F.FinanceMigrationRun(company_id=company, kind="reconcile", mode="dry_run"))
            add(F.FinanceMigrationIssue(company_id=company, run=run, issue_type="t", message="m"))
            add(F.FinanceMigrationIssue(company_id=company, issue_type="orphan", message="m"))
    return made


def cleanup(company, made):
    with tenant_context(company):
        for obj in reversed(made):
            # _raw_delete: без сбора связанных (промежуточные схемы не содержат всех столбцов ORM)
            type(obj).all_objects.filter(pk=obj.pk)._raw_delete("default")


made = {A: chains(A, IDS["A"]), B: chains(B, IDS["B"])}
new_models = sorted({type(o) for objs in made.values() for o in objs}, key=lambda m: m.__name__)
REPORT["new_tables_with_rows"] = sorted(m._meta.db_table for m in new_models)
for model in new_models:
    table = model._meta.db_table
    with tenant_context(A):  # (б) своя компания: чтение, изменение
        mine = list(model.objects.all())
        ok(mine and all(o.company_id == A for o in mine), f"{table}: компания A видит свои строки")
        ok(model.objects.filter(pk__in=[o.pk for o in made[B] if type(o) is model]).count() == 0,
           f"{table}: компания A не видит строк B")  # fmt: skip
    with tenant_context(B):  # (в) чужая компания
        others = [o for o in made[A] if type(o) is model]
        pks = [o.pk for o in others]
        ok(
            model.objects.count() == len([o for o in made[B] if type(o) is model]),
            f"{table}: B видит только своё",
        )
        ok(
            model.all_objects.filter(pk__in=pks).count() == 0,
            f"{table}: B не видит строк A (all_objects)",
        )
        ok(
            model.all_objects.filter(pk__in=pks).update(company_id=B) == 0,
            f"{table}: B не меняет строки A",
        )
        ok(
            model.all_objects.filter(pk__in=pks)._raw_delete("default") == 0,
            f"{table}: B не удаляет строки A",
        )
        mine_b = next(o for o in made[B] if type(o) is model)
        clone = copy.copy(mine_b)
        clone.pk = None
        clone._state.adding = True
        clone.company_id = A  # вставка строки чужой компании в контексте B
        try:
            with transaction.atomic():
                model.all_objects.bulk_create([clone])
            ok(False, f"{table}: вставка строки A в контексте B должна быть отклонена")
        except DatabaseError as exc:
            ok("row-level security" in str(exc), f"{table}: ожидалась ошибка RLS: {exc}")
        try:  # перенос своей строки в чужую компанию
            with transaction.atomic():
                model.all_objects.filter(pk=mine_b.pk).update(company_id=A)
            ok(False, f"{table}: перенос строки B в A должен быть отклонён")
        except DatabaseError as exc:
            ok("row-level security" in str(exc), f"{table}: перенос в чужую компанию: {exc}")
    with tenant_context(A):  # строки A на месте
        ok(model.objects.filter(pk__in=pks).count() == len(pks), f"{table}: строки A не пострадали")

if exists("finance_financialperiod"):
    with tenant_context(A):  # (б) запись своих строк: изменение и повторное чтение
        period = F.FinancialPeriod.objects.get(year=2026, month=5)
        F.FinancialPeriod.objects.filter(pk=period.pk).update(comment="правка A")
        ok(
            F.FinancialPeriod.objects.get(pk=period.pk).comment == "правка A",
            "A меняет свои строки",
        )
    with tenant_context(B):
        ok(not F.FinancialPeriod.objects.filter(comment="правка A").exists(), "правка A невидима B")

# --- 3. (в) для всех таблиц: чужие строки недоступны на уровне SQL --------------------------------

with app.cursor() as cur:
    for t in tables:
        cur.execute("SELECT set_config('app.company_id', %s, false)", [str(B)])
        cur.execute(f'SELECT count(*) FROM "{t}" WHERE company_id=%s', [A])
        ok(cur.fetchone()[0] == 0, f"{t}: B видит строки A")
        cur.execute(f'SELECT count(DISTINCT company_id) FROM "{t}"')
        ok(cur.fetchone()[0] <= 1, f"{t}: B видит строки нескольких компаний")
        cur.execute(f'UPDATE "{t}" SET company_id=company_id WHERE company_id=%s', [A])
        ok(cur.rowcount == 0, f"{t}: B изменил строки A")
        cur.execute(f'DELETE FROM "{t}" WHERE company_id=%s', [A])
        ok(cur.rowcount == 0, f"{t}: B удалил строки A")
        app.rollback()  # ничего не сохраняем
        cur.execute("SELECT set_config('app.company_id', %s, false)", [str(A)])
        cur.execute(f'SELECT count(DISTINCT company_id) FROM "{t}"')
        ok(cur.fetchone()[0] <= 1, f"{t}: A видит строки нескольких компаний")
        app.rollback()
app.rollback()

# владелец видит строки обеих компаний (данные на месте после попыток B)
for t in ("core_role", "core_handbookvalue"):
    with owner.cursor() as cur:
        cur.execute(f'SELECT count(DISTINCT company_id) FROM "{t}"')
        ok(cur.fetchone()[0] >= 2, f"{t}: данные обеих компаний на месте")
    owner.rollback()

# --- 4. (г) сброс контекста ------------------------------------------------------------------

with app.cursor() as cur:  # откат транзакции отменяет set_config
    cur.execute("SELECT set_config('app.company_id', %s, false)", [str(A)])
    ok(guc(cur) == str(A), "контекст установлен внутри транзакции")
    app.rollback()
    ok(guc(cur) in (None, ""), "после ROLLBACK контекст не «подвешен»")
    cur.execute("SELECT count(*) FROM core_role")
    ok(cur.fetchone()[0] == 0, "после ROLLBACK строки компании не видны")
    app.rollback()
with app.cursor() as cur:  # откат до точки сохранения
    cur.execute("SELECT set_config('app.company_id', %s, false)", [str(A)])
    app.commit()
    cur.execute("SAVEPOINT s1")
    cur.execute("SELECT set_config('app.company_id', %s, false)", [str(B)])
    cur.execute("ROLLBACK TO SAVEPOINT s1")
    ok(guc(cur) == str(A), "после ROLLBACK TO SAVEPOINT вернулся контекст A (не B)")
    app.rollback()
    cur.execute("SELECT set_config('app.company_id', '', false)")
    app.commit()
app.close()


def django_scalar(sql):
    with connection.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


ROLES = "SELECT count(*) FROM core_role"
ok(django_scalar("SELECT current_user") == "logistix_app", "Django подключён ролью приложения")
ok(django_scalar(ROLES) == 0, "Django без контекста: 0 строк")
with tenant_context(A):
    ok(django_scalar(ROLES) >= 7, "Django в контексте A видит роли A")
ok(django_scalar(ROLES) == 0, "после выхода из контекста тот же коннект снова видит 0 строк")
with tenant_context(B):
    ok(
        django_scalar("SELECT count(*) FROM core_role WHERE company_id=%d" % A) == 0,
        "B не видит роли A",
    )
ok(
    django_scalar("SELECT current_setting('app.company_id', true)") in (None, ""),
    "контекст после B сброшен",
)


class Boom(Exception):
    pass


try:  # откат транзакции внутри контекста
    with tenant_context(A), transaction.atomic():
        ok(django_scalar(ROLES) >= 7, "в транзакции контекст A действует")
        raise Boom
except Boom:
    pass
ok(django_scalar(ROLES) == 0, "после ROLLBACK транзакции и выхода из контекста: 0 строк")
ok(
    django_scalar("SELECT current_setting('app.company_id', true)") in (None, ""),
    "ROLLBACK: контекст пуст",
)
with tenant_context(A):  # откат до точки сохранения при действующем контексте
    with transaction.atomic():
        try:
            with transaction.atomic():
                django_scalar(ROLES)
                raise Boom
        except Boom:
            pass
        ok(django_scalar(ROLES) >= 7, "после отката точки сохранения контекст A сохраняется")
        ok(django_scalar("SELECT current_setting('app.company_id', true)") == str(A), "GUC = A")
ok(django_scalar(ROLES) == 0, "после всех откатов подвешенного контекста нет")
# новая сессия того же процесса: закрыть и открыть соединение
connection.close()
ok(django_scalar(ROLES) == 0, "новое соединение: контекста нет")

# --- 5. шаговые проверки ---------------------------------------------------------------------

if STEP == "M2":
    with tenant_context(A):
        n = HandbookValue.objects.filter(handbook__code="expense_category").count()
    ok(n == 11, f"A видит 11 категорий расходов, а не {n}")
    with tenant_context(B):
        got = HandbookValue.objects.filter(handbook__code="expense_category").values_list(
            "company_id", flat=True
        )
        ok(set(got) == {B} and len(got) == 11, "B видит только свои категории")
if STEP in ("M4", "M5", "M6"):
    with tenant_context(A):
        rate = F.ExchangeRate.objects.create(
            company_id=A, currency_id=IDS["A"]["usd"], quote_currency_id=IDS["A"]["eur"],
            date=date(2026, 6, 1), rate=1.1,
        )  # fmt: skip
        ok(
            F.ExchangeRate.objects.filter(quote_currency__isnull=False).count() == 1,
            "A пишет курс пары",
        )
    with tenant_context(B):
        ok(F.ExchangeRate.all_objects.filter(pk=rate.pk).count() == 0, "B не видит курс пары A")
        ok(F.ExchangeRate.all_objects.filter(pk=rate.pk).update(rate=9) == 0, "B не меняет курс A")
    with tenant_context(A):
        F.InvoiceItem.objects.filter(pk=IDS["A"]["item"]).update(income=None)
        F.ExchangeRate.objects.filter(pk=rate.pk).delete()
if STEP in ("M5", "M6"):
    with tenant_context(A):
        rows = list(F.CompanyFinancialSettings.objects.all())
        ok(
            len(rows) == 1 and rows[0].engine == "legacy" and rows[0].completed_status_id,
            "A: строка M5",
        )
    with tenant_context(B):
        rows = list(F.CompanyFinancialSettings.objects.all())
        ok(len(rows) == 1 and rows[0].company_id == B, "B: своя строка M5")
if STEP == "M6":
    from apps.core.models import Role

    with tenant_context(A):
        admin = Role.objects.get(name="Администратор")
        ok("finance.manage_settings" in admin.permissions, "A: Администратор получил права M6")
        ok(Role.objects.filter(company_id=B).count() == 0, "A не видит роли B")

for company, objs in made.items():
    cleanup(company, objs)
connection.close()
owner.close()
print("RLS_REPORT=" + json.dumps(REPORT, ensure_ascii=False))
