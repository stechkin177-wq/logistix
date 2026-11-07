"""Определение режима учёта компании и общие помощники новых финансовых сервисов.

Сервисы (income, expenses, invoice_links) engine НЕ проверяют: это делают только хуки
(hooks.py) в существующем коде. Хуки активны при engine == 'new'; пока ни одна компания не
переключена, в рабочей среде они ничего не делают.
"""

from datetime import date, datetime

from apps.core.tenancy import get_current_company_id, tenant_context
from apps.forwarding.finance_lines.models import company_zone

from .models import CompanyFinancialSettings


def current_cid(obj_company_id: int) -> int:
    """Компания контекста запроса, а при его отсутствии - компания объекта."""
    return get_current_company_id() or obj_company_id


def company_engine(company_id: int) -> str:
    with tenant_context(company_id):
        return (
            CompanyFinancialSettings.objects.filter(company_id=company_id)
            .values_list("engine", flat=True)
            .first()
            or "legacy"
        )


def engine_is_new(company_id: int) -> bool:
    return company_engine(company_id) == "new"


def local_date(moment: datetime, company_id: int) -> date:
    """Дата момента в часовом поясе компании."""
    return moment.astimezone(company_zone(company_id)).date()
