from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.core.services import VALID_MODULES

from .models import Subscription
from .services import effective_status, get_subscription


class SubscriptionBlocked(PermissionDenied):
    default_detail = "Подписка компании заблокирована"
    default_code = "subscription_blocked"


class SubscriptionReadonly(PermissionDenied):
    default_detail = "Подписка истекла: доступно только чтение"
    default_code = "subscription_readonly"


class ModuleDisabled(PermissionDenied):
    default_detail = "Модуль не подключён"
    default_code = "module_disabled"


def _company_id(request):
    membership = getattr(request, "membership", None)
    return membership.company_id if membership is not None else None


def subscription_state(request):
    """(subscription, effective_status) компании запроса; кэшируется на запросе."""
    raw = getattr(request, "_request", request)
    cached = getattr(raw, "_billing_state", None)
    if cached is None:
        sub = get_subscription(_company_id(request))
        state = Subscription.BLOCKED if sub is None else effective_status(sub, timezone.now())
        cached = (sub, state)
        raw._billing_state = cached
    return cached


def enforce_subscription(request):
    """Бросает отказ по подписке. Неаутентифицированные запросы не трогает.

    Аутентифицированный запрос без членства (контекста компании) - отказ (fail closed):
    у него нет подписки, по которой можно решить. Эндпоинты без компании намеренно
    не используют шлюз (вход, обновление токена, health - AllowAny; switch-company).
    """
    user = request.user
    if not (user and user.is_authenticated):
        return
    if _company_id(request) is None:
        raise SubscriptionBlocked()
    _, state = subscription_state(request)
    if state == Subscription.BLOCKED:
        raise SubscriptionBlocked()
    if state == Subscription.READONLY and request.method not in SAFE_METHODS:
        raise SubscriptionReadonly()


class SubscriptionGate(BasePermission):
    """Глобальный шлюз подписки (в DEFAULT_PERMISSION_CLASSES и в permission_required).

    readonly: только безопасные методы; blocked: всё запрещено. Платформенные
    администраторы не освобождены. Нет подписки = blocked.
    """

    def has_permission(self, request, view):
        enforce_subscription(request)
        return True


def ModuleRequired(module: str) -> type[BasePermission]:  # noqa: N802 - фабрика, стиль permission_required
    """Фабрика DRF-права: модуль должен быть и у компании, и в тарифе подписки."""
    if module not in VALID_MODULES:
        raise ValueError(f"Неизвестный модуль: {module!r}")

    class _ModuleRequired(BasePermission):
        required_module = module

        def has_permission(self, request, view):
            user = request.user
            if not (user and user.is_authenticated):
                return False
            enforce_subscription(request)
            membership = getattr(request, "membership", None)
            sub, _ = subscription_state(request)
            if membership is None or sub is None:
                return False
            if module not in (membership.company.modules or []):
                raise ModuleDisabled()
            if module not in (sub.plan.modules or []):
                raise ModuleDisabled()
            return True

    _ModuleRequired.__name__ = f"ModuleRequired[{module}]"
    return _ModuleRequired
