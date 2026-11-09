
from django.db import transaction

from apps.billing.plans import default_plan
from apps.billing.subscriptions import start_subscription

from .document_types import seed_document_types
from .handbooks.services import seed_handbooks
from .models import Company, LegalEntity, Membership, Role
from .module_services import (
    VALID_MODULES,
    set_company_modules,
    unmet_requirements,
    with_default_companions,
)
from .numbering.services import seed_numbering
from .permissions_catalog import ADMIN_ROLE_NAME, SYSTEM_ROLES
from .signals import company_created
from .tenancy import tenant_context


@transaction.atomic
def create_company_with_defaults(name: str, owner, modules: list[str]) -> Company:
    """Компания + модули + системные роли + юрлицо + членство владельца (Администратор).

    Контекст компании после возврата не остаётся: записи создаются с явным company_id
    во временном контексте новой компании (иначе их не пропустит RLS), внешний контекст
    восстанавливается.
    """
    modules = list(modules)
    if not modules or not set(modules) <= VALID_MODULES:
        raise ValueError(f"modules должен быть непустым подмножеством {sorted(VALID_MODULES)}")
    start_plan = default_plan()  # тариф по умолчанию задаёт администратор платформы (данные)
    modules = with_default_companions(
        modules, allowed=set(start_plan.modules or [])
    )  # logistics/forwarding включают finance и documents, если они есть в тарифе
    unmet = unmet_requirements(modules)
    if unmet:
        raise ValueError("Не выполнены зависимости модулей: " + "; ".join(unmet))
    company = Company.objects.create(name=name, modules=[])
    set_company_modules(company, modules, audit_changes=False)  # CompanyModule + проекция
    with tenant_context(company.id):  # RLS: строки пишутся в контексте новой компании
        roles = {
            role_name: Role.all_objects.create(
                company=company, name=role_name, is_system=True, permissions=list(perms)
            )
            for role_name, perms in SYSTEM_ROLES.items()
        }
        LegalEntity.all_objects.create(company=company, name=name, is_default=True)
    Membership.objects.create(
        user=owner, company=company, role=roles[ADMIN_ROLE_NAME], is_active=True
    )
    seed_handbooks(company)
    with tenant_context(company.id):
        seed_document_types(company)
    seed_numbering(company)
    start_subscription(company, start_plan)  # срок бесплатного периода и цена - данные тарифа
    company_created.send(sender=Company, company=company)
    return company
