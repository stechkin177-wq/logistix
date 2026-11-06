"""GET /api/session/: всё, что нужно интерфейсу после входа, одним запросом.

Проходит шлюз подписки как любой эндпоинт компании: readonly/grace - 200 (фронтенд показывает
баннер), blocked - 403 subscription_blocked. Подписка и статус берутся из billing.services.
"""

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.permissions import subscription_state
from apps.billing.services import days_left, grace_days_left
from apps.core import branding as branding_rules
from apps.core.models import CompanyBranding

from .auth import companies_payload, memberships_of


def effective_modules(company, plan) -> list[str]:
    """Модули компании, разрешённые тарифом (порядок как в компании)."""
    allowed = set(plan.modules or [])
    return [m for m in (company.modules or []) if m in allowed]


class SessionView(APIView):
    def get(self, request):
        membership = request.membership
        user, company, role = request.user, membership.company, membership.role
        sub, state = subscription_state(request)
        now = timezone.now()
        # оформление без права company.view (его нет у большинства ролей); строку не создаём
        branding = CompanyBranding.objects.filter(company_id=company.pk).first()
        return Response(
            {
                "user": {
                    "id": user.pk,
                    "email": user.email,
                    "phone": user.phone,
                    "full_name": user.full_name,
                },
                "company": {
                    "id": company.pk,
                    "name": company.name,
                    "timezone": company.timezone,
                    "language": company.language,
                },
                "companies": companies_payload(memberships_of(user).order_by("id")),
                "role": {"id": role.pk, "name": role.name} if role else None,
                "modules": effective_modules(company, sub.plan),
                "permissions": list(role.permissions) if role else [],
                "branding": branding_rules.branding_payload(branding or CompanyBranding(), request),
                "subscription": {
                    "status": state,
                    "plan_code": sub.plan.code,
                    "days_left": days_left(sub, now),
                    "grace_days_left": grace_days_left(sub, now),
                    "is_free_period": sub.is_free_period,
                },
            }
        )
