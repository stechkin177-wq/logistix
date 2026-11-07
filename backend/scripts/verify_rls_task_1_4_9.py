# ruff: noqa: E501
"""Короткая проверка RLS для П3 (migrate_finance, Shadow-зеркало, reconcile_finance) под РЕАЛЬНОЙ
ролью logistix_app на временной БД (все миграции, deploy/db-init.sql). Код возврата 0 - всё прошло.

Под ролью приложения: перенос и сверка компании A работают и пишут только в A; компания B не
видит строк A, её перенос/сверка/зеркало не затрагивают A, а сервисы не находят чужие заказы;
после ROLLBACK и выхода из контекста строк не видно.
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
    user = User.objects.create_user(email=f"{key.lower()}@rls149.kz", password="s3cret-pass-1")
    out[key] = {"company": create_company_with_defaults(f"Компания {key}", user, ["forwarding"]).id}
print("IDS=" + json.dumps(out))
"""

BATTERY = """
import json, os
from datetime import date
from io import StringIO
from django.core.management import call_command
from django.db import connection, transaction
from apps.core.models import Company
from apps.core.tenancy import tenant_context
from apps.finance import migration, reconcile, shadow
from apps.finance.models import (CompanyFinancialSettings, Expense, ExpenseAllocation, FinanceMigrationIssue,
    FinanceMigrationRun, Income)
from apps.finance.tests.helpers import add_line, make_order
from apps.forwarding.models import Order

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

ok(scalar("SELECT current_user") == "logistix_app", "роль приложения")
ok(not scalar("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user"), "без обхода RLS")
TABLES = ["finance_income", "finance_expense", "finance_expenseallocation", "finance_financemigrationrun", "finance_financemigrationissue"]

def count(model, company):
    with tenant_context(company.id):
        return model.objects.count()

oa = make_order(A)
add_line(A, oa, income=100, expense=30, title="Склад", day=date(2026, 5, 10), category="Прочее")
add_line(A, oa, expense=7, title="Перевозка X-404", day=date(2026, 5, 11), category="Перевозка")
ob = make_order(B)
add_line(B, ob, income=55, title="Услуга B", day=date(2026, 5, 12))

out = StringIO()
call_command("migrate_finance", "--company", str(A.id), "--dry-run", stdout=out)
ok(count(Income, A) == 0 and count(Expense, A) == 0, "dry-run под ролью ничего не пишет")
call_command("migrate_finance", "--company", str(A.id), stdout=out)
a_before = {m: count(m, A) for m in (Income, Expense, ExpenseAllocation, FinanceMigrationIssue)}
ok(a_before[Income] == 1 and a_before[Expense] == 1 and a_before[FinanceMigrationIssue] == 1, f"перенос A: {a_before}")
ok(count(Income, B) == 0 and count(Expense, B) == 0, "перенос A не создал строк в B")
call_command("migrate_finance", "--company", str(A.id), stdout=out)  # повтор
ok({m: count(m, A) for m in a_before} == a_before, "повтор переноса: ноль изменений")

call_command("migrate_finance", "--company", str(B.id), stdout=out)
ok(count(Income, B) == 1, "перенос B")
ok({m: count(m, A) for m in a_before} == a_before, "перенос B не затронул A")

run = reconcile.reconcile(A.id)
ok(run.status == "needs_review", "A: спорная строка -> needs_review")
run_b = reconcile.reconcile(B.id)
ok(run_b.status == "success", "B: согласована")
with tenant_context(B.id):
    ok(FinanceMigrationIssue.objects.count() == 0, "B не видит проблем A")
    ok(FinanceMigrationRun.objects.filter(kind="reconcile").count() == 1, "B видит только свою сверку")
    ok(FinanceMigrationIssue.all_objects.filter(company_id=A.id).count() == 0, "B не видит Issue A (all_objects)")
    ok(Income.all_objects.filter(order_id=oa.pk).count() == 0, "B не видит доходы заказов A")
    for fn, label in ((lambda: migration.migrate_order(oa), "migrate_order"),
                      (lambda: Order.all_objects.get(pk=oa.pk), "get")):
        try:
            fn()
            ok(False, f"B: {label} не должен находить заказ A")
        except Order.DoesNotExist:
            ok(True, "")

# Shadow под ролью: зеркало пишет только в свою компанию
with tenant_context(A.id):
    s = CompanyFinancialSettings.objects.get()
    s.engine = "shadow"
    s.save()
extra = add_line(A, oa, income=9, title="Новая", day=date(2026, 5, 13))
ok(shadow.mirror_order(oa, "rls_check"), "Shadow-зеркало под ролью")
ok(count(Income, A) == 2 and count(Income, B) == 1, "зеркало создало доход только в A")
with tenant_context(A.id):
    ok(Income.objects.filter(legacy_line=extra).exists(), "доход строки зеркалирован")
    migration.detach_line(extra)
    ok(Income.objects.filter(order=oa, status="void").count() == 1, "отвязка зеркала при удалении строки")

# откат и сброс контекста
try:
    with transaction.atomic():
        with tenant_context(B.id):
            add_line(B, ob, income=1, title="откат", day=date(2026, 5, 14))
            migration.migrate_order(Order.all_objects.get(pk=ob.pk))
            ok(Income.objects.count() == 2, "внутри транзакции B видит новый доход")
        raise RuntimeError("rollback")
except RuntimeError:
    pass
ok(count(Income, B) == 1, "после отката перенос B откатился")
for t in TABLES:
    ok(scalar(f"SELECT count(*) FROM {t}") == 0, f"{t}: после выхода из контекста 0 строк")
connection.close()
ok(scalar("SELECT count(*) FROM finance_income") == 0, "новое соединение: контекста нет")
print("RLS149=" + json.dumps({"checks": n}))
"""


def main() -> int:
    base_url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    with TempDatabase(base_url, "logistix_rls149") as db:
        apply_db_init(db.url)
        manage(db.url, "migrate", "--noinput")
        out = manage(db.url, "shell", stdin=SEED)
        ids = json.loads(out.split("IDS=")[1].splitlines()[0])
        app_url = with_user(db.url, APP_ROLE, APP_PASSWORD)
        res = manage(app_url, "shell", stdin=BATTERY, env_extra={"RLS_IDS": json.dumps(ids)})
        report = json.loads(res.split("RLS149=")[1].splitlines()[0])
        print(f"OK: П3 (перенос, Shadow, сверка) под ролью {APP_ROLE}: проверок {report['checks']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
