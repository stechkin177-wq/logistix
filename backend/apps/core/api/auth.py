import hashlib

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from apps.billing.models import Subscription
from apps.billing.permissions import SubscriptionBlocked
from apps.billing.services import company_status
from apps.core import audit, password_setup, platform, totp
from apps.core.models import Membership, token_clock
from apps.core.phone import normalize_phone
from apps.core.tenancy import get_current_company_id

LOGIN_ERROR = "Неверный логин или пароль"
_DUMMY_HASH = make_password("dummy-password-for-timing")


def memberships_of(user):
    return Membership.objects.filter(user=user, is_active=True).select_related("company")


def issue_tokens(user, company_id=None, mfa=False):
    """Токены контекста компании (company_id) или платформы (company_id=None, ctx=platform).

    mfa=True - вход подтверждён вторым фактором (TOTP); метка переходит в токены компании,
    выданные при переключении контекста, и нужна для платформенного токена владельца."""
    refresh = RefreshToken.for_user(user)
    if mfa:
        refresh["mfa"] = True
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
            if platform.requires_totp(user):
                # пароль верен, но токены выдаются только после кода TOTP (или его подключения)
                _platform_auth_event(request, user, "password_ok")
                return Response(
                    {
                        "totp_required": user.totp_enabled,
                        "totp_setup_required": not user.totp_enabled,
                        "challenge": _challenge(user),
                    }
                )
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
    code = serializers.CharField(required=False, allow_blank=True)  # TOTP при переходе в платформу

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
            mfa = bool(request.auth.get("mfa"))
            if platform.requires_totp(request.user):
                # из компании в платформу - только с подтверждением: свежий код TOTP (ступенчатая
                # проверка), иначе токен компании открывал бы платформенные права
                if not mfa:
                    raise PermissionDenied("Войдите заново и подтвердите TOTP")
                code = str(request.data.get("code") or "")
                if not code:
                    raise PermissionDenied("Введите код TOTP", "totp_required")
                step = totp.verify(request.user.totp_secret, code, request.user.totp_last_step)
                if step is None:
                    _platform_auth_event(request, request.user, "totp_failed", {"at": "switch"})
                    # 400, а не 401: у клиента 401 означает «сессия истекла» и запускает выход
                    return Response({"detail": "Неверный код", "code": "totp_invalid"}, status=400)
                request.user.totp_last_step = step
                request.user.save(update_fields=["totp_last_step"])
            _platform_auth_event(request, request.user, "switch_to_platform")
            return Response(
                {
                    **issue_tokens(request.user, mfa=mfa),
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
                **issue_tokens(request.user, company_id, mfa=bool(request.auth.get("mfa"))),
                "context": platform.CTX_COMPANY,
                "companies": companies_payload(memberships),
            }
        )


class PlatformAwareGate:
    """Шлюз подписки для токена компании; платформенному токену (нет подписки) - только вход."""

    def get_permissions(self):
        # платформенный токен не имеет подписки компании - шлюз к нему не применим
        auth = getattr(self.request, "auth", None)
        if auth is not None and auth.get("ctx") == platform.CTX_PLATFORM:
            return [IsAuthenticated()]
        return super().get_permissions()


class MeView(PlatformAwareGate, APIView):
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


class PasswordChangeView(PlatformAwareGate, APIView):
    """Смена собственного пароля: POST {old_password, new_password} -> 200 с новыми токенами.

    Все ранее выданные токены (в том числе других устройств) отзываются; текущая сессия
    продолжается на новых токенах того же контекста. Значения паролей не логируются и не
    попадают в аудит (там только маска)."""

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
            user.tokens_valid_after = token_clock()  # прежние токены (и других устройств) отозваны
            user.save(update_fields=["password", "tokens_valid_after"])
            audit.log("update", user, user, {"password": "***"}, ip=audit.client_ip(request))
        # текущая сессия продолжается на новых токенах того же контекста
        mfa = bool(request.auth.get("mfa"))
        if request.auth.get("ctx") == platform.CTX_PLATFORM:
            return Response(issue_tokens(user, mfa=mfa))
        return Response(issue_tokens(user, request.auth.get("company_id"), mfa=mfa))


class RevocationAwareRefreshSerializer(TokenRefreshSerializer):
    """Refresh отклоняется, если выход или смена пароля отозвали токены пользователя."""

    def validate(self, attrs):
        try:
            refresh = RefreshToken(attrs["refresh"])
        except TokenError as exc:
            raise InvalidToken(exc.args[0]) from None
        user = get_user_model().objects.filter(pk=refresh.get("user_id")).first()
        if user is None or not user.is_active or user.tokens_revoked(refresh):
            raise InvalidToken("Сессия завершена: войдите снова")
        return super().validate(attrs)


class RefreshView(TokenRefreshView):
    """Обновление access; company_id, ctx и mfa копируются из refresh."""

    serializer_class = RevocationAwareRefreshSerializer


class LogoutView(APIView):
    """Выход: все ранее выданные токены пользователя (access и refresh, на всех устройствах)
    перестают действовать. Работает и при заблокированной подписке (шлюз не нужен)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        user.tokens_valid_after = token_clock()
        user.save(update_fields=["tokens_valid_after"])
        if user.is_platform_admin:
            _platform_auth_event(request, user, "logout")
        return Response(status=204)


# --- второй фактор (TOTP) для платформенных аккаунтов -------------------------------------------

CHALLENGE_SALT = "platform-totp"
CHALLENGE_MAX_AGE = 300


def _challenge(user) -> str:
    """Подписанный короткоживущий талон «пароль подтверждён»; токенов он не даёт."""
    return signing.dumps({"uid": user.pk}, salt=CHALLENGE_SALT)


def _user_of_challenge(raw):
    try:
        uid = signing.loads(raw, salt=CHALLENGE_SALT, max_age=CHALLENGE_MAX_AGE)["uid"]
    except (signing.BadSignature, KeyError, TypeError):
        raise AuthenticationFailed("Талон входа недействителен или истёк: войдите заново") from None
    user = get_user_model().objects.filter(pk=uid, is_active=True).first()
    if user is None or not platform.requires_totp(user):
        raise AuthenticationFailed("Талон входа недействителен или истёк: войдите заново")
    return user


class TotpThrottle(SimpleRateThrottle):
    """Лимит попыток кода на одного пользователя (по талону), чтобы код нельзя было подобрать."""

    scope = "totp"

    def get_cache_key(self, request, view):
        raw = request.data.get("challenge") if hasattr(request.data, "get") else None
        try:
            uid = signing.loads(raw, salt=CHALLENGE_SALT, max_age=CHALLENGE_MAX_AGE)["uid"]
        except Exception:  # noqa: BLE001 - неверный талон отклонит сам эндпоинт
            return None
        return self.cache_format % {"scope": self.scope, "ident": str(uid)}


class TotpSetupView(APIView):
    """Первое подключение TOTP: выдаёт ключ (его вносят в приложение-аутентификатор)."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [TotpThrottle]

    def get_authenticate_header(self, request):
        return "Bearer"

    def post(self, request):
        user = _user_of_challenge(request.data.get("challenge"))
        if user.totp_enabled:
            raise PermissionDenied("TOTP уже подключён; сброс выполняет администратор сервера")
        user.totp_secret = totp.new_secret()
        user.save(update_fields=["totp_secret"])
        account = user.email or user.phone or str(user.pk)
        return Response(
            {"secret": user.totp_secret, "otpauth_uri": totp.otpauth_uri(user.totp_secret, account)}
        )


class TotpView(APIView):
    """Второй шаг входа: код TOTP -> токены платформенного контекста. Первый верный код при
    подключении включает TOTP."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [TotpThrottle]

    def get_authenticate_header(self, request):
        return "Bearer"

    def post(self, request):
        user = _user_of_challenge(request.data.get("challenge"))
        if not user.totp_secret:
            raise serializers.ValidationError({"code": "Сначала получите ключ подключения"})
        code = str(request.data.get("code") or "")
        step = totp.verify(user.totp_secret, code, user.totp_last_step)
        if step is None:
            # ответом, а не исключением: иначе транзакция запроса откатит запись в журнал
            _platform_auth_event(request, user, "totp_failed")
            body = {"detail": "Неверный код", "code": "totp_invalid"}
            return Response(body, status=401)
        user.totp_last_step = step
        first = not user.totp_enabled
        user.totp_enabled = True
        user.save(update_fields=["totp_last_step", "totp_enabled"])
        if first:
            _platform_auth_event(request, user, "totp_enabled")
        _platform_auth_event(request, user, "login")
        return Response(
            {
                **issue_tokens(user, mfa=True),
                "context": platform.CTX_PLATFORM,
                "platform_role": user.platform_role,
                "companies": companies_payload(memberships_of(user).order_by("id")),
            }
        )


class PasswordSetupThrottle(SimpleRateThrottle):
    scope = "password_setup"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class PasswordSetupSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(trim_whitespace=False)


class PasswordSetupView(APIView):
    """Установка пароля по одноразовой ссылке (выдаёт администратор сервера командой
    create_platform_owner / issue_password_link). Ссылка работает один раз и ограниченное время;
    все прежние токены пользователя отзываются. Токенов вход не выдаёт: дальше обычный вход
    (для владельца платформы - с подключением TOTP)."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [PasswordSetupThrottle]

    def get_authenticate_header(self, request):
        return "Bearer"

    def post(self, request):
        ser = PasswordSetupSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = password_setup.user_for(ser.validated_data["uid"], ser.validated_data["token"])
        if user is None:
            raise serializers.ValidationError({"token": "Ссылка недействительна или устарела"})
        new = ser.validated_data["new_password"]
        try:
            validate_password(new, user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)}) from None
        user.set_password(new)
        user.save(update_fields=["password", "tokens_valid_after"])
        if user.is_platform_admin:
            _platform_auth_event(request, user, "password_set")
        return Response(status=204)
