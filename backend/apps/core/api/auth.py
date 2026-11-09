import hashlib

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from apps.billing.models import Subscription
from apps.billing.permissions import SubscriptionBlocked
from apps.billing.services import company_status
from apps.core import audit, platform
from apps.core.models import Membership
from apps.core.phone import normalize_phone
from apps.core.tenancy import get_current_company_id

LOGIN_ERROR = "Неверный логин или пароль"
_DUMMY_HASH = make_password("dummy-password-for-timing")


def memberships_of(user):
    return Membership.objects.filter(user=user, is_active=True).select_related("company")


def issue_tokens(user, company_id=None):
    """Токены контекста компании (company_id) или платформы (company_id=None, ctx=platform)."""
    refresh = RefreshToken.for_user(user)
    if company_id is None:
        refresh["ctx"] = platform.CTX_PLATFORM
    else:
        refresh["company_id"] = company_id
        refresh["ctx"] = platform.CTX_COMPANY
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


class LoginThrottle(SimpleRateThrottle):
    """Лимит попыток входа на ОДИН логин (не на IP: за прокси/на serverless IP общий).

    Ключ - sha256 нормализованного логина (email в нижнем регистре / телефон по normalize_phone;
    при ошибке нормализации - сырая строка). Считаются и неудачные, и успешные попытки.
    Пароль в ключ не входит, исходный логин в кэше не хранится.
    """

    scope = "login"

    def get_cache_key(self, request, view):
        raw = request.data.get("login") if hasattr(request.data, "get") else None
        if not isinstance(raw, str):
            return None  # без логина запрос всё равно закончится 400 до проверки пароля
        value = raw.strip()
        if "@" in value:
            value = value.lower()
        else:
            try:
                value = normalize_phone(value)
            except ValueError:
                pass
        ident = hashlib.sha256(value.encode()).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": ident}


class LoginView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

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
            if user.is_platform_admin:
                # исключение откатило бы транзакцию запроса вместе с записью в журнал,
                # поэтому отказ возвращается ответом (формат тот же, что у обработчика ошибок)
                _platform_auth_event(request, user, "login_failed")
                body = {"detail": LOGIN_ERROR, "code": "authentication_failed"}
                return Response(body, status=401)
            raise AuthenticationFailed(LOGIN_ERROR)
        memberships = list(memberships_of(user).order_by("id"))
        if user.is_platform_admin:
            # платформенный аккаунт входит в Центр управления, даже без членства в компаниях;
            # в компанию - переключением контекста (членство и подписка проверяются там)
            _platform_auth_event(request, user, "login")
            return Response(
                {
                    **issue_tokens(user),
                    "context": platform.CTX_PLATFORM,
                    "platform_role": user.platform_role,
                    "companies": companies_payload(memberships),
                }
            )
        if not memberships:
            raise PermissionDenied("Нет доступа ни к одной компании")
        # токен выдаётся на первую компанию, чья подписка не заблокирована
        usable = [m for m in memberships if company_status(m.company_id) != Subscription.BLOCKED]
        if not usable:
            raise SubscriptionBlocked()
        audit.log_login(request, user, usable[0].company_id)
        return Response(
            {
                **issue_tokens(user, usable[0].company_id),
                "context": platform.CTX_COMPANY,
                "companies": companies_payload(memberships),
            }
        )


def _platform_auth_event(request, user, action, extra=None):
    """Запись о входе/смене контекста платформенного аккаунта в платформенный журнал."""
    from apps.billing import events
    from apps.billing.models import BillingEvent

    events.record(
        BillingEvent.AUTH,
        user.pk,
        action,
        {"ip": audit.client_ip(request), "role": user.platform_role, **(extra or {})},
        user=user,
    )


class SwitchCompanySerializer(serializers.Serializer):
    company_id = serializers.IntegerField(required=False)
    context = serializers.ChoiceField(choices=[platform.CTX_PLATFORM], required=False)

    def validate(self, attrs):
        if ("company_id" in attrs) == ("context" in attrs):
            raise serializers.ValidationError("Укажите company_id или context=platform")
        return attrs


class SwitchCompanyView(APIView):
    # без шлюза подписки: из заблокированной/readonly компании нужно уметь выйти в другую
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = SwitchCompanySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        memberships = list(memberships_of(request.user).order_by("id"))
        if ser.validated_data.get("context") == platform.CTX_PLATFORM:
            # роль проверяется по БД: токен компании не даёт права на переключение сам по себе
            if not request.user.is_platform_admin:
                raise PermissionDenied("Нет платформенного доступа")
            _platform_auth_event(request, request.user, "switch_to_platform")
            return Response(
                {
                    **issue_tokens(request.user),
                    "context": platform.CTX_PLATFORM,
                    "platform_role": request.user.platform_role,
                    "companies": companies_payload(memberships),
                }
            )
        company_id = ser.validated_data["company_id"]
        if company_id not in {m.company_id for m in memberships}:
            raise PermissionDenied("Нет доступа к этой компании")
        if company_status(company_id) == Subscription.BLOCKED:
            raise SubscriptionBlocked()
        audit.log_login(request, request.user, company_id, {"switched_to": company_id})
        if request.user.is_platform_admin:
            _platform_auth_event(
                request, request.user, "switch_to_company", {"company_id": company_id}
            )
        return Response(
            {
                **issue_tokens(request.user, company_id),
                "context": platform.CTX_COMPANY,
                "companies": companies_payload(memberships),
            }
        )


class MeView(APIView):
    def get_permissions(self):
        # платформенный токен не имеет подписки компании - шлюз к нему не применим
        auth = getattr(self.request, "auth", None)
        if auth is not None and auth.get("ctx") == platform.CTX_PLATFORM:
            return [IsAuthenticated()]
        return super().get_permissions()

    def get(self, request):
        user = request.user
        return Response(
            {
                "id": user.pk,
                "email": user.email,
                "phone": user.phone,
                "full_name": user.full_name,
                "context": request.auth.get("ctx") or platform.CTX_COMPANY,
                "company_id": request.auth.get("company_id"),
                "context_company_id": get_current_company_id(),
            }
        )


class PasswordChangeThrottle(UserRateThrottle):
    scope = "password_change"


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(trim_whitespace=False, write_only=True)
    new_password = serializers.CharField(trim_whitespace=False, write_only=True)


class PasswordChangeView(APIView):
    """Смена собственного пароля: POST {old_password, new_password} -> 204.

    ВНИМАНИЕ: выданные refresh-токены остаются действительными до истечения срока
    (чёрного списка токенов нет, он запланирован на этап 5). Значения паролей не
    логируются и не попадают в аудит (там только маска).
    """

    permission_classes = [IsAuthenticated]  # доступно и в платформенном контексте
    throttle_classes = [PasswordChangeThrottle]

    def post(self, request):
        ser = PasswordChangeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        old, new = ser.validated_data["old_password"], ser.validated_data["new_password"]
        user = request.user
        if not user.check_password(old):
            raise serializers.ValidationError({"old_password": "Неверный текущий пароль"})
        if old == new:
            raise serializers.ValidationError(
                {"new_password": "Новый пароль должен отличаться от текущего"}
            )
        try:
            validate_password(new, user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)}) from None
        with transaction.atomic():
            user.set_password(new)
            user.save(update_fields=["password"])
            audit.log("update", user, user, {"password": "***"}, ip=audit.client_ip(request))
        return Response(status=204)


class RefreshView(TokenRefreshView):
    """Обновление access; company_id копируется из refresh."""
