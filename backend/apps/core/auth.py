from django.contrib.postgres.expressions import ArraySubquery
from django.db.models import OuterRef
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import CompanyModule, Membership
from .tenancy import set_current_company, tenant_context


class CompanyJWTAuthentication(JWTAuthentication):
    """JWT с company_id. Каждый запрос заново проверяет активное членство и
    устанавливает текущую компанию. Сброс контекста делает TenantContextMiddleware."""

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        company_id = token.get("company_id")
        if company_id is None:
            raise AuthenticationFailed("В токене нет компании")
        # Membership без RLS, но присоединённая роль (Role - TenantModel) под RLS видна
        # только в контексте её компании; контекст запроса ставится лишь после проверки.
        with tenant_context(company_id):
            # включённые модули компании читаются тем же запросом (без лишнего обращения к БД)
            enabled_modules = ArraySubquery(
                CompanyModule.all_objects.filter(company_id=OuterRef("company_id"), enabled=True)
                .order_by("id")
                .values("module_code")
            )
            membership = (
                Membership.objects.select_related("role", "company")
                .annotate(enabled_module_codes=enabled_modules)
                .filter(user_id=user.pk, company_id=company_id, is_active=True)
                .first()
            )
        if membership is None:
            raise AuthenticationFailed("Доступ к компании закрыт")
        request.membership = membership
        set_current_company(company_id)
        return user, token
