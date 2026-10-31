from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import Membership
from .tenancy import set_current_company


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
        active = Membership.objects.filter(
            user_id=user.pk,
            company_id=company_id,
            is_active=True,
        ).exists()
        if not active:
            raise AuthenticationFailed("Доступ к компании закрыт")
        set_current_company(company_id)
        return user, token
