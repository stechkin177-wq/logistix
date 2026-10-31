from collections.abc import Iterable

from rest_framework.exceptions import PermissionDenied


def ensure_can_grant(actor_membership, permissions: Iterable[str]) -> None:
    """Набор прав можно выдать (назначить роль, создать/изменить роль) только если он
    целиком входит в права самого действующего сотрудника. Иначе 403."""
    role = actor_membership.role if actor_membership is not None else None
    own = set(role.permissions) if role is not None else set()
    missing = sorted(set(permissions) - own)
    if missing:
        raise PermissionDenied(
            "Нельзя выдать права, которых нет у вас самих: " + ", ".join(missing)
        )
