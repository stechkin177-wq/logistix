# ruff: noqa: E501
"""Короткая проверка RLS для сервисов П2 (доходы, расходы и доли, связи со счетами) под РЕАЛЬНОЙ
ролью logistix_app на временной БД (все миграции, deploy/db-init.sql).

Сценарий компании A под ролью приложения: engine=new, заказ и рейс, завершение рейса (признание
дохода), расход перевозчика с долями, входящий счёт и связь с расходом, отмена счёта, корректировка
цены рейса. Компания B не видит, не меняет и не удаляет эти строки, её сервисы не находят чужие
объекты; после ROLLBACK и выхода из контекста строк не видно. Код возврата 0 - всё прошло.
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
    user = User.objects.create_user_schema_agnostic(email=f"{key.lower()}@rls146.kz", password="s3cret-pass-1")
    out[key] = {"company": create_company_with_defaults(f"Компания {key}", user, ["forwarding"]).id}
print("IDS=" + json.dumps(out))
"""

BATTERY = """
import json, os
from datetime import date
from decimal import Decimal as D
from django.db import connection, transaction
from apps.core.models import Company
from apps.core.tenancy import tenant_context
from apps.finance import expenses as ex, income as inc, invoice_links as links, invoices as inv
from apps.finance.models import (CompanyFinancialSettings, Expense, ExpenseAllocation,
    ExpenseInvoiceAllocation, Income, IncomeTrip, InvoiceItem)
from apps.finance.tests.helpers import first_user, issue_invoice, make_carrier
from apps.forwarding.models import Trip
from apps.forwarding.tests.test_trips import make_cargos, svc_create
from apps.forwarding.trips.services import change_trip_status
from apps.core.handbooks.models import HandbookValue

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
TABLES = ["finance_income", "finance_incometrip", "finance_expense", "finance_expenseallocation", "finance_expenseinvoiceallocation"]
for t in TABLES:
    ok(scalar(f"SELECT count(*) FROM {t}") == 0, f"{t}: без контекста 0 строк")

for company in (A, B):
    with tenant_context(company.id):
        s = CompanyFinancialSettings.objects.get()
        s.engine, s.cutover_date = "new", date(2026, 1, 1)
        s.save()

user = first_user(A)
order, ids = make_cargos(A, 1, client_rate=D("1000"))
trip = svc_create(A, ids, carrier=make_carrier(A), data={"carrier_price": D("100")})
with tenant_context(A.id):
    done = HandbookValue.objects.get(handbook__code="trip_status", code="COMPLETED")
    change_trip_status(Trip.objects.get(pk=trip.pk), done, user)
    income = Income.objects.get(order=order, kind="freight")
    ok(income.status == "recognized" and IncomeTrip.objects.filter(income=income).count() == 1, "A: доход признан")
expense = ex.create_carrier_expense(trip, user=user)
with tenant_context(A.id):
    ok(len(ex.alloc_state(expense)) == 1, "доли созданы")
invoice = issue_invoice(A, order=order, direction="in", carrier=trip.carrier, amount="100", trip=trip)
with tenant_context(A.id):
    item = InvoiceItem.objects.get(invoice=invoice)
link = links.link_expense_to_item(expense, item, "100", user=user)
with tenant_context(A.id):
    Trip.objects.filter(pk=trip.pk).update(carrier_price=D("130"))
with tenant_context(A.id):
    ex.sync_trip_expense(Trip.objects.get(pk=trip.pk), user=user)
with tenant_context(A.id):
    e = Expense.objects.get(pk=expense.pk)
    ok(e.amount == D("130.00") and e.needs_review and e.review_reason == "invoice_variance", "A: расхождение со счётом")
    ok(ExpenseAllocation.objects.filter(expense=e).count() == 1, "A: доля пересчитана")
    inv.cancel(invoice, user=user)
    ok(ExpenseInvoiceAllocation.objects.get(pk=link.pk).released_at is not None, "A: связь освобождена")
a_counts = {}
with tenant_context(A.id):
    for model in (Income, IncomeTrip, Expense, ExpenseAllocation, ExpenseInvoiceAllocation):
        a_counts[model] = model.objects.count()
        ok(a_counts[model] >= 1, f"A видит {model.__name__}")

# компания B: чужое недоступно ни для чтения, ни для изменения, ни для сервисов
with tenant_context(B.id):
    for model, pk in ((Income, income.pk), (Expense, expense.pk), (ExpenseInvoiceAllocation, link.pk)):
        ok(model.all_objects.filter(pk=pk).count() == 0, f"B не видит {model.__name__}")
        ok(model.all_objects.filter(pk=pk)._raw_delete("default") == 0, f"B не удаляет {model.__name__}")
    ok(Expense.all_objects.filter(pk=expense.pk).update(title="взлом") == 0, "B не меняет расход A")
    ok(ExpenseAllocation.all_objects.filter(expense_id=expense.pk).count() == 0, "B не видит доли A")
    for fn, label in (
        (lambda: ex.sync_trip_expense(Trip.all_objects.get(pk=trip.pk), user=user), "sync"),
        (lambda: ex.void_expense(expense, user=user, reason="чужой"), "void"),
        (lambda: ex.set_allocations(expense, [], user=user), "set_allocations"),
        (lambda: inc.void_income(income, "чужой", user), "void_income"),
    ):
        try:
            fn()
            ok(False, f"B: сервис {label} не должен работать с чужим объектом")
        except Exception as exc:
            ok(exc.__class__.__name__ in ("DoesNotExist", "FinanceError"), f"{label}: {exc!r}")
with tenant_context(A.id):
    for model, cnt in a_counts.items():
        ok(model.objects.count() == cnt, f"строки A целы: {model.__name__}")
    ok(Expense.objects.get(pk=expense.pk).title.startswith("Перевозка"), "расход A не изменён")

# откат и сброс контекста
try:
    with transaction.atomic(), tenant_context(A.id):
        ex.void_expense(Expense.objects.get(pk=expense.pk), user=user, reason="откатим")
        raise RuntimeError("rollback")
except RuntimeError:
    pass
with tenant_context(A.id):
    ok(Expense.objects.get(pk=expense.pk).status == "active", "откат вернул расход")
for t in TABLES:
    ok(scalar(f"SELECT count(*) FROM {t}") == 0, f"{t}: после выхода из контекста 0 строк")
connection.close()
ok(scalar("SELECT count(*) FROM finance_expense") == 0, "новое соединение: контекста нет")
print("RLS146=" + json.dumps({"checks": n}))
"""


def main() -> int:
    base_url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    with TempDatabase(base_url, "logistix_rls146") as db:
        apply_db_init(db.url)
        manage(db.url, "migrate", "--noinput")
        out = manage(db.url, "shell", stdin=SEED)
        ids = json.loads(out.split("IDS=")[1].splitlines()[0])
        app_url = with_user(db.url, APP_ROLE, APP_PASSWORD)
        res = manage(app_url, "shell", stdin=BATTERY, env_extra={"RLS_IDS": json.dumps(ids)})
        report = json.loads(res.split("RLS146=")[1].splitlines()[0])
        print(f"OK: сервисы П2 под ролью {APP_ROLE}: проверок {report['checks']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
