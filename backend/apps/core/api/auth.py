from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from apps.billing.models import Subscription
from apps.billing.permissions import SubscriptionBlocked
from apps.billing.services import company_status
from apps.core.models import Membership
from apps.core.phone import normalize_phone
from apps.core.tenancy import get_current_company_id

LOGIN_ERROR = "Неверный логин или пароль"
_DUMMY_HASH = make_password("dummy-password-for-timing")


def memberships_of(user):
    return Membership.objects.filter(user=user, is_active=True).select_related("company")


def issue_tokens(user, company_id):
    refresh = RefreshToken.for_user(user)
    refresh["company_id"] = company_id
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def companies_payload(memberships):
    return [{"id": m.company_id, "name": m.company.name} for m in memberships]


class LoginSerializer(serializers.Serializer):
    login = serializers.CharField()
    password = serializers.CharField(trim_whitespace=False)

    def validate_login(self, value):
        value = value.strip()
        if "@" in value:
            return value.lower()
        try:
            return normalize_phone(value)
        except ValueError:
            raise serializers.ValidationError("Некорректный номер телефона") from None


class LoginView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get_authenticate_header(self, request):
        return "Bearer"  # без этого DRF превратит 401 в 403

    def post(self, request):
        ser = LoginSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        login, password = ser.validated_data["login"], ser.validated_data["password"]
        User = get_user_model()
        field = "email" if "@" in login else "phone"
        user = User.objects.filter(**{field: login}).first()
        if user is None:
            check_password(password, _DUMMY_HASH)  # выравниваем время ответа
            raise AuthenticationFailed(LOGIN_ERROR)
        if not user.check_password(password) or not user.is_active:
            raise AuthenticationFailed(LOGIN_ERROR)
        memberships = list(memberships_of(user).order_by("id"))
        if not memberships:
            raise PermissionDenied("Нет доступа ни к одной компании")
        # токен выдаётся на первую компанию, чья подписка не заблокирована
        usable = [m for m in memberships if company_status(m.company_id) != Subscription.BLOCKED]
        if not usable:
            raise SubscriptionBlocked()
        return Response(
            {
                **issue_tokens(user, usable[0].company_id),
                "companies": companies_payload(memberships),
            }
        )


class SwitchCompanySerializer(serializers.Serializer):
    company_id = serializers.IntegerField()


class SwitchCompanyView(APIView):
    # без шлюза подписки: из заблокированной/readonly компании нужно уметь выйти в другую
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = SwitchCompanySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        company_id = ser.validated_data["company_id"]
        memberships = list(memberships_of(request.user).order_by("id"))
        if company_id not in {m.company_id for m in memberships}:
            raise PermissionDenied("Нет доступа к этой компании")
        if company_status(company_id) == Subscription.BLOCKED:
            raise SubscriptionBlocked()
        return Response(
            {**issue_tokens(request.user, company_id), "companies": companies_payload(memberships)}
        )


class MeView(APIView):
    def get(self, request):
        user = request.user
        return Response(
            {
                "id": user.pk,
                "email": user.email,
                "phone": user.phone,
                "full_name": user.full_name,
                "company_id": request.auth["company_id"],
                "context_company_id": get_current_company_id(),
            }
        )


class RefreshView(TokenRefreshView):
    """Обновление access; company_id копируется из refresh."""
