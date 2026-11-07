"""Начальные финансовые настройки компании (одно правило для миграции 0007 и новых компаний).

Значения совместимы с прежним поведением: engine='legacy', allow_backdating=True, расход по
перевозке вручную. base_currency - значение справочника currency с кодом KZT (нет или
неоднозначно - пусто). completed_status - значение trip_status с кодом COMPLETED, только если оно
ровно одно и активно; иначе пусто и автоматически не назначается (компания остаётся
заблокированной для переключения на engine=new до ручного сопоставления).
"""

from apps.core.handbooks.models import HandbookValue
from apps.core.tenancy import tenant_context

from .models import CompanyFinancialSettings

BASE_CURRENCY_CODE = "KZT"
COMPLETED_CODE = "COMPLETED"


def _single(handbook_code: str, code: str, only_active: bool = False) -> int | None:
    rows = HandbookValue.objects.filter(handbook__code=handbook_code, code=code)
    if only_active:
        rows = rows.filter(is_active=True)
    ids = list(rows.values_list("id", flat=True)[:2])
    return ids[0] if len(ids) == 1 else None


def ensure_company_financial_settings(company) -> CompanyFinancialSettings:
    """Создаёт настройки компании, если их нет (идемпотентно, существующие не меняет)."""
    with tenant_context(company.id):
        existing = CompanyFinancialSettings.objects.filter(company=company).first()
        if existing is not None:
            return existing
        return CompanyFinancialSettings.objects.create(
            company=company,
            base_currency_id=_single("currency", BASE_CURRENCY_CODE),
            completed_status_id=_single("trip_status", COMPLETED_CODE, only_active=True),
        )


def on_company_created(sender, company, **kwargs):
    """Обработчик сигнала core.company_created (core не импортирует finance)."""
    ensure_company_financial_settings(company)
