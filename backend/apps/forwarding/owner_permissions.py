"""Права для объектов, принадлежащих стороне (счета, договоры): по разделу владельца.

Чтение - <раздел>.view, изменение - <раздел>.update: клиент -> clients, перевозчик -> carriers,
юрлицо компании -> company. Владелец - по параметру запроса (список, создание) или по объекту.
"""

from rest_framework.permissions import BasePermission

from apps.core.api_permissions import permission_required

SECTIONS = {"client": "clients", "carrier": "carriers", "legal_entity": "company"}


def _has(request, view, code) -> bool:
    return permission_required(code)().has_permission(request, view)


class OwnerSectionPermission(BasePermission):
    """sections: поле владельца -> раздел прав (по умолчанию все три; вьюсет может сузить)."""

    def _sections(self, view):
        allowed = getattr(view, "owner_fields", tuple(SECTIONS))
        return {f: SECTIONS[f] for f in allowed}

    def has_permission(self, request, view):
        action = getattr(view, "action", None)
        sections = self._sections(view)
        if action in ("list", "create"):
            source = request.query_params if action == "list" else getattr(request, "data", {})
            getter = getattr(source, "get", lambda _k: None)
            kind = next((f for f in sections if getter(f) not in (None, "")), None)
            if kind is None:
                return True  # без владельца вью отвечает 400 (данных не раскрывает)
            return _has(
                request, view, f"{sections[kind]}.{'view' if action == 'list' else 'update'}"
            )
        return True  # объектные действия проверяются в has_object_permission

    def has_object_permission(self, request, view, obj):
        sections = self._sections(view)
        kind = next((f for f in sections if getattr(obj, f"{f}_id", None) is not None), None)
        if kind is None:
            return False
        need = "view" if getattr(view, "action", None) == "retrieve" else "update"
        return _has(request, view, f"{sections[kind]}.{need}")
