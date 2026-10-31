from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.billing.models import Plan, Subscription

from .handbooks.services import seed_handbooks
from .models import Company, LegalEntity, Membership, Role
from .numbering.services import seed_numbering
from .permissions_catalog import ADMIN_ROLE_NAME, SYSTEM_ROLES
from .tenancy import tenant_context

VALID_MODULES = {"forwarding", "fleet"}
FREE_PERIOD_DAYS = 365


@transaction.atomic
def create_company_with_defaults(name: str, owner, modules: list[str]) -> Company:
    """Компания + системные роли + юрлицо по умолчанию + членство владельца (Администратор).

    Контекст компании после возврата не остаётся: записи создаются с явным company_id
    при сброшенном контексте, внешний контекст восстанавливается.
    """
    modules = list(modules)
    if not modules or not set(modules) <= VALID_MODULES:
        raise ValueError(f"modules должен быть непустым подмножеством {sorted(VALID_MODULES)}")
    company = Company.objects.create(name=name, modules=modules)
    with tenant_context(None):
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
    seed_numbering(company)
    now = timezone.now()
    Subscription.objects.create(
        company=company,
        plan=Plan.objects.get(code="start"),
        status=Subscription.ACTIVE,
        is_free_period=True,
        starts_at=now,
        ends_at=now + timedelta(days=FREE_PERIOD_DAYS),
    )
    return company
