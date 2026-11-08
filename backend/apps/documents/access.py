"""Доступность видов документов по модулям (A7): эффективные модули компании и проверка вида.

Эффективный доступ = модуль есть в тарифе И включён в CompanyModule (как в ModuleRequired).
Файл не импортирует модели других приложений.
"""

from apps.billing.services import get_subscription
from apps.core.module_services import effective_module_codes
from apps.core.tenancy import get_current_company_id

from .errors import DocumentError


def effective_modules() -> list[str]:
    """Эффективные модули текущей компании (тариф ∩ CompanyModule)."""
    company_id = get_current_company_id()
    sub = get_subscription(company_id)
    return effective_module_codes(company_id, sub.plan.modules if sub is not None else [])


def require_module(module_code: str) -> None:
    """Вид документа доступен, только если включён модуль его поставщика."""
    if module_code not in effective_modules():
        raise DocumentError(
            "module_disabled",
            "Этот вид документа недоступен: модуль, которому он принадлежит, не подключён.",
            status_code=403,
        )
