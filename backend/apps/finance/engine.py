"""Определение режима учёта компании и общие помощники новых финансовых сервисов.

Сервисы (income, expenses, invoice_links) engine НЕ проверяют: это делают только хуки
(hooks.py) в существующем коде. Хуки активны при engine == 'new'; пока ни одна компания не
переключена, в рабочей среде они ничего не делают.
"""

from datetime import date, datetime

from apps.core.tenancy import get_current_company_id, tenant_context
from apps.forwarding.finance_lines.models import company_zone

from .errors import FinanceError
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


def use_new_engine(company) -> bool:
    """Единая точка выбора источника чтения: True только при engine == 'new'.

    company - объект компании, id или None (тогда компания контекста запроса). Без контекста
    компании возвращает False (прежнее чтение), чтобы служебные вызовы вне запроса не менялись.
    """
    cid = getattr(company, "pk", company) if company is not None else get_current_company_id()
    return bool(cid) and company_engine(cid) == "new"


LEGACY_LINES_MESSAGE = (
    "Строки заказа (прежний учёт) доступны только для чтения: компания работает в новом "
    "финансовом учёте. Доходы и расходы заказа ведутся в разделах «Доходы» и «Расходы»."
)


def assert_legacy_lines_writable(company_id: int | None = None) -> None:
    """engine == 'new': запись в OrderService (API, ставка, расход рейса) запрещена -> 409."""
    if use_new_engine(company_id):
        raise FinanceError("legacy_lines_readonly", LEGACY_LINES_MESSAGE, status_code=409)


def local_date(moment: datetime, company_id: int) -> date:
    """Дата момента в часовом поясе компании."""
    return moment.astimezone(company_zone(company_id)).date()
