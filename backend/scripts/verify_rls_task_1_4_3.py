# ruff: noqa: E501
"""Короткая проверка RLS для операций 1.4.3 (периоды, настройки, смена базовой валюты, оплата
в закрытом периоде) под РЕАЛЬНОЙ ролью logistix_app на временной БД (схема - все миграции).

Основная и демо-БД не затрагиваются. Код возврата 0 - всё прошло.
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
    user = User.objects.create_user_schema_agnostic(email=f"{key.lower()}@rls143.kz", password="s3cret-pass-1")
    out[key] = {"company": create_company_with_defaults(f"Компания {key}", user, ["forwarding"]).id, "user": user.id}
print("IDS=" + json.dumps(out))
"""

BATTERY = """
import json, os
from django.db import connection, transaction
from apps.core.models import Company, User
from apps.core.tenancy import tenant_context
from apps.finance import periods, settings_service, fx
from apps.finance.errors import FinanceError
from apps.finance.models import CompanyFinancialSettings, FinancialPeriod, FinancialPeriodEvent
from apps.core.audit.models import AuditLog

IDS = json.loads(os.environ["RLS_IDS"])
A, B = Company.objects.get(pk=IDS["A"]["company"]), Company.objects.get(pk=IDS["B"]["company"])
ua, ub = User.objects.get(pk=IDS["A"]["user"]), User.objects.get(pk=IDS["B"]["user"])
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
# без контекста
ok(scalar("SELECT count(*) FROM finance_financialperiod") == 0, "без контекста периодов нет")
# компания A: закрытие, настройки, смена базовой валюты
pa = periods.close_period(A, 2020, 1, ua, "закрыли")
ok(periods.is_period_closed(A, __import__("datetime").date(2020, 1, 15)), "A: период закрыт")
settings_service.update_settings(A, {"fiscal_year_start_month": 4, "allow_backdating": False}, ua)
usd = None
with tenant_context(A.id):
    from apps.core.handbooks.models import HandbookValue
    usd = HandbookValue.objects.get(handbook__code="currency", code="USD")
fx.change_base_currency(A, usd, ua, "проверка RLS")
with tenant_context(A.id):
    s = CompanyFinancialSettings.objects.get()
    ok((s.fiscal_year_start_month, s.allow_backdating, s.base_currency.code) == (4, False, "USD"), "A: настройки записаны")
    ok(FinancialPeriodEvent.objects.count() == 1, "A: событие периода")
    ok(AuditLog.objects.filter(object_type="finance.companyfinancialsettings").count() == 2, "A: аудит настроек")
# компания B ничего не видит и не меняет у A
with tenant_context(B.id):
    ok(not periods.is_period_closed(B, __import__("datetime").date(2020, 1, 15)), "B: период A не виден")
    ok(FinancialPeriod.all_objects.filter(pk=pa.pk).count() == 0, "B: строка периода A скрыта")
    ok(FinancialPeriod.all_objects.filter(pk=pa.pk).update(comment="взлом") == 0, "B не меняет период A")
    try:
        periods.reopen_period(pa, ub, "чужой период")
        ok(False, "B не должна переоткрыть период A")
    except FinanceError:
        ok(False, "ожидалась ошибка поиска, а не FinanceError")
    except Exception as exc:
        ok(exc.__class__.__name__ in ("DoesNotExist", "NoTenantContext", "TenantMismatch"), repr(exc))
    sb = CompanyFinancialSettings.objects.get()
    ok(sb.fiscal_year_start_month == 1 and sb.base_currency.code == "KZT", "B: настройки B не тронуты")
    ok(AuditLog.objects.filter(object_type="finance.companyfinancialsettings").count() == 0, "B: аудит A не виден")
# откат: ничего не остаётся, контекст не «подвешен»
try:
    with transaction.atomic():
        periods.close_period(B, 2020, 2, ub, "")
        ok(periods.is_period_closed(B, __import__("datetime").date(2020, 2, 1)), "B: закрыт внутри транзакции")
        raise RuntimeError("rollback")
except RuntimeError:
    pass
ok(scalar("SELECT count(*) FROM finance_financialperiod") == 0, "после отката и вне контекста строк нет")
ok(not periods.is_period_closed(B, __import__("datetime").date(2020, 2, 1)), "B: закрытие откатилось")
ok(periods.is_period_closed(A, __import__("datetime").date(2020, 1, 15)), "A: закрытие сохранилось")
connection.close()
ok(scalar("SELECT count(*) FROM finance_companyfinancialsettings") == 0, "новое соединение: контекста нет")
print("RLS143=" + json.dumps({"checks": n}))
"""


def main() -> int:
    base_url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    with TempDatabase(base_url, "logistix_rls143") as db:
        apply_db_init(db.url)
        manage(db.url, "migrate", "--noinput")
        out = manage(db.url, "shell", stdin=SEED)
        ids = json.loads(out.split("IDS=")[1].splitlines()[0])
        app_url = with_user(db.url, APP_ROLE, APP_PASSWORD)
        res = manage(app_url, "shell", stdin=BATTERY, env_extra={"RLS_IDS": json.dumps(ids)})
        report = json.loads(res.split("RLS143=")[1].splitlines()[0])
        print(f"OK: операции 1.4.3 под ролью {APP_ROLE}: проверок {report['checks']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
