"""Платформенный контекст (T5-A): роли и права владельца/администратора платформы.

Платформа и компании независимы: платформенные права не даёт ни членство в компании, ни
is_superuser/is_staff, а платформенный токен (ctx=platform) не даёт доступа к данным компаний.
Роль хранится в User.platform_role и проверяется на КАЖДОМ запросе по БД (снятие роли действует
сразу, без ожидания истечения токена).

Права - простой реестр "право -> роли". Новое право или роль добавляются здесь, без отдельной
системы ролей: схема рассчитана на расширение, но сейчас ролей две.
"""

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import PLATFORM_ADMIN, PLATFORM_OWNER

CTX_PLATFORM = "platform"
CTX_COMPANY = "company"

READ = "platform.read"
SUBSCRIPTIONS = "platform.subscriptions.manage"
PLANS = "platform.plans.manage"
COMPANIES = "platform.companies.manage"  # блокировка/возврат компании

ROLE_PERMISSIONS = {
    PLATFORM_OWNER: {READ, SUBSCRIPTIONS, PLANS, COMPANIES},
    # администратор платформы: просмотр и работа с подписками компаний; без тарифов и блокировок
    PLATFORM_ADMIN: {READ, SUBSCRIPTIONS},
}


class PlatformContextRequired(PermissionDenied):
    default_detail = "Требуется платформенный контекст"
    default_code = "platform_context_required"


class CompanyContextRequired(PermissionDenied):
    default_detail = "Эндпоинт доступен только в контексте компании"
    default_code = "company_context_required"


def requires_totp(user) -> bool:
    """Владельцу платформы второй фактор обязателен; администратору - если он его включил."""
    return user.platform_role == PLATFORM_OWNER or (user.is_platform_admin and user.totp_enabled)


def is_platform_request(request) -> bool:
    return getattr(request, "platform_role", None) is not None


def has_platform_permission(request, permission: str) -> bool:
    role = getattr(request, "platform_role", None)
    return role is not None and permission in ROLE_PERMISSIONS.get(role, ())


class PlatformAccess(BasePermission):
    """Права платформы. Представление задаёт platform_read (для безопасных методов) и
    platform_write (для остальных; по умолчанию как read) или словарь platform_actions по
    имени действия вьюсета. Проверка только по платформенному
    токену и текущей роли пользователя в БД; шлюз подписки компании не применяется."""

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if not is_platform_request(request):
            raise PlatformContextRequired()
        by_action = getattr(view, "platform_actions", {})  # {action: право} для вьюсетов
        need = by_action.get(getattr(view, "action", None))
        if need is None:
            read = getattr(view, "platform_read", READ)
            need = read if request.method in SAFE_METHODS else getattr(view, "platform_write", read)
        return has_platform_permission(request, need)
