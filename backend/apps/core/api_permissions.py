from rest_framework.permissions import BasePermission

from apps.billing.permissions import enforce_subscription

from .permissions_catalog import ALL_PERMISSIONS


def permission_required(code: str) -> type[BasePermission]:
    """Фабрика DRF-права: код должен быть в роли текущего членства (из токена).

    Неизвестный код - ошибка при импорте (защита от опечаток).
    """
    if code not in ALL_PERMISSIONS:
        raise ValueError(f"Неизвестное право: {code!r}")

    class _PermissionRequired(BasePermission):
        required_code = code

        def has_permission(self, request, view):
            user = request.user
            if not (user and user.is_authenticated):
                return False
            enforce_subscription(request)  # шлюз подписки нельзя обойти переопределением прав
            membership = getattr(request, "membership", None)
            role = membership.role if membership is not None else None
            if role is None:
                return False
            return code in role.permissions

    _PermissionRequired.__name__ = f"PermissionRequired[{code}]"
    return _PermissionRequired


class SectionPermissionMixin:
    """Права по действию вьюсета: <permission_section>.<view|create|update|delete>."""

    permission_section: str
    _action_map = {
        "list": "view",
        "retrieve": "view",
        "create": "create",
        "update": "update",
        "partial_update": "update",
        "destroy": "delete",
    }

    def get_permissions(self):
        action = self._action_map.get(getattr(self, "action", None) or "")
        if action is None:  # неизвестное действие - только IsAuthenticated + запрет
            return [permission_required(f"{self.permission_section}.delete")()]
        return [permission_required(f"{self.permission_section}.{action}")()]
