# ruff: noqa: E501
"""Короткая проверка RLS для 1.4.11 (switch_finance_engine, rollback_finance_engine, freeze_finance, чтение new) под РЕАЛЬНОЙ
ролью logistix_app на временной БД (все миграции, deploy/db-init.sql). Код возврата 0 - всё прошло.

Под ролью приложения: переключение, откат и заморозка компании A меняют только настройки A;
компания B (другой engine) не затронута, не видит и не меняет настройки A; заморозка A не мешает
записи B; чтение в режиме new включается только для A; после выхода из контекста строк не видно.
"""

import json
import os
import sys

from task_1_4_1_common import (
    APP_PASSWORD,
    APP_ROLE,
    DEFAULT_URL,
    TempDatabase,
    apply_db_init,
    manage,
    with_user,
)

SEED = """
import json
from apps.core.models import User
from apps.core.services import create_company_with_defaults
out = {}
for key in ("A", "B"):
    user = User.objects.create_user(email=f"{key.lower()}@rls1411.kz", password="s3cret-pass-1")
    out[key] = {"company": create_company_with_defaults(f"Компания {key}", user, ["forwarding"]).id}
print("IDS=" + json.dumps(out))
"""

BATTERY = """
import json, os
from datetime import date
from decimal import Decimal
from io import StringIO
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from apps.core.models import Company
from apps.core.tenancy import tenant_context
from apps.finance import income, periods, switching
from apps.finance.engine import use_new_engine
from apps.finance.errors import FinanceError
from apps.finance.models import CompanyFinancialSettings, Income
from apps.finance.tests.helpers import add_line, make_order
from apps.finance.reports_new import order_totals_new
from apps.forwarding.finance_lines.services import order_totals

IDS = json.loads(os.environ["RLS_IDS"])
A, B = Company.objects.get(pk=IDS["A"]["company"]), Company.objects.get(pk=IDS["B"]["company"])
n = 0
def ok(cond, msg):
    global n
    n += 1
    if not cond:
        raise AssertionError(msg)

def scalar(sql):
    with connection.cursor() as c:
        c.execute(sql)
        return c.fetchone()[0]

def settings_of(company):
    with tenant_context(company.id):
        return CompanyFinancialSettings.objects.get()

ok(scalar("SELECT current_user") == "logistix_app", "роль приложения")
ok(not scalar("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user"), "без обхода RLS")

oa = make_order(A)
add_line(A, oa, income=100, expense=30, title="Склад", day=date(2026, 5, 10), category="Прочее")
ob = make_order(B)
add_line(B, ob, income=55, title="Услуга B", day=date(2026, 5, 12))
out = StringIO()
for c in (A, B):
    call_command("migrate_finance", "--company", str(c.id), stdout=out)
ok(settings_of(A).engine == "legacy" and settings_of(B).engine == "legacy", "оба legacy")

REF = "Письмо заказчика RLS"
call_command("switch_finance_engine", "--company", str(A.id), "--to", "shadow", "--approval-ref", REF, stdout=out)
ok(settings_of(A).engine == "shadow" and settings_of(B).engine == "legacy", "A -> shadow, B не тронута")

# B не может перейти на new, и её отказ не затрагивает A
try:
    call_command("switch_finance_engine", "--company", str(B.id), "--to", "new", "--cutover", "2026-07-01", "--approval-ref", REF, stdout=out)
    ok(False, "B (legacy) на new перейти не должна")
except CommandError as exc:
    ok("engine_not_shadow" in str(exc), "отказ B с перечнем причин")
ok(settings_of(B).engine == "legacy" and settings_of(A).engine == "shadow", "после отказа B состояния прежние")

# пробный запуск A ничего не пишет
call_command("switch_finance_engine", "--company", str(A.id), "--to", "new", "--cutover", "2026-07-01", "--approval-ref", REF, "--dry-run", stdout=out)
ok(settings_of(A).engine == "shadow", "dry-run: engine прежний")
with tenant_context(A.id):
    ok(Income.objects.filter(legacy_line__isnull=False).count() == 1, "dry-run: доходы прежние")

call_command("switch_finance_engine", "--company", str(A.id), "--to", "new", "--cutover", "2026-07-01", "--approval-ref", REF, stdout=out)
sa, sb = settings_of(A), settings_of(B)
ok(sa.engine == "new" and sa.cutover_date == date(2026, 7, 1) and sa.engine_switched_at is not None, "A переключена")
ok(sb.engine == "legacy" and sb.cutover_date is None and sb.engine_switched_at is None, "B не затронута")
ok(use_new_engine(A) is True and use_new_engine(B) is False and use_new_engine(A.id) is True, "чтение new только у A")
with tenant_context(A.id):
    ok(order_totals(oa) == order_totals_new(oa), "A: итоги заказа из новой модели")
with tenant_context(B.id):
    ok(order_totals(ob)["revenue"] == Decimal("55.00"), "B: итоги из прежнего учёта")
    ok(CompanyFinancialSettings.objects.filter(company_id=A.id).count() == 0, "B не видит настройки A")
    ok(CompanyFinancialSettings.all_objects.filter(company_id=A.id).count() == 0, "B не видит настройки A (all_objects)")
    ok(CompanyFinancialSettings.objects.update(financial_writes_frozen=True) == 1, "B меняет только свою строку")
with tenant_context(B.id):
    CompanyFinancialSettings.objects.update(financial_writes_frozen=False)
ok(settings_of(A).financial_writes_frozen is False, "A не затронута обновлением B")

# заморозка A не мешает B
call_command("freeze_finance", "--company", str(A.id), "--on", "--reason", "RLS проверка", stdout=out)
ok(settings_of(A).financial_writes_frozen and not settings_of(B).financial_writes_frozen, "заморожена только A")
try:
    with tenant_context(A.id):
        income.plan_service(oa, "x", "", Decimal("1"), None)
    ok(False, "запись в замороженной A")
except FinanceError as exc:
    ok(exc.status_code == 423 and exc.detail.code == "finance_frozen", "A: 423")
periods.assert_finance_writable(B)
ok(True, "B пишет")
call_command("freeze_finance", "--company", str(A.id), "--off", "--reason", "снято", stdout=out)
ok(not settings_of(A).financial_writes_frozen, "A разморожена")

# откат A: engine возвращается, данные остаются
call_command("rollback_finance_engine", "--company", str(A.id), "--to", "shadow", "--approval-ref", REF, stdout=out)
ok(settings_of(A).engine == "shadow" and settings_of(B).engine == "legacy", "откат A, B не тронута")
with tenant_context(A.id):
    ok(Income.objects.count() == 1, "данные после отката остались")
ok(use_new_engine(A) is False, "после отката чтение прежнее")

for t in ("finance_companyfinancialsettings", "finance_income", "finance_financemigrationrun"):
    ok(scalar(f"SELECT count(*) FROM {t}") == 0, f"{t}: после выхода из контекста 0 строк")
connection.close()
ok(scalar("SELECT count(*) FROM finance_companyfinancialsettings") == 0, "новое соединение: контекста нет")
print("RLS1411=" + json.dumps({"checks": n}))
"""


def main() -> int:
    base_url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    with TempDatabase(base_url, "logistix_rls1411") as db:
        apply_db_init(db.url)
        manage(db.url, "migrate", "--noinput")
        out = manage(db.url, "shell", stdin=SEED)
        ids = json.loads(out.split("IDS=")[1].splitlines()[0])
        app_url = with_user(db.url, APP_ROLE, APP_PASSWORD)
        res = manage(app_url, "shell", stdin=BATTERY, env_extra={"RLS_IDS": json.dumps(ids)})
        report = json.loads(res.split("RLS1411=")[1].splitlines()[0])
        print(
            f"OK: 1.4.11 (переключение, откат, заморозка) под ролью {APP_ROLE}: проверок {report['checks']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
