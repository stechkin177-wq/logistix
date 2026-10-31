"""Реестр типов для корзины.

Приложения регистрируют свои SoftDeleteModel в AppConfig.ready():
``register(Client, "clients", "clients.view")``. permission - право, которое нужно, чтобы
видеть ТАКИЕ объекты в корзине и восстанавливать их (в дополнение к trash.view/trash.update).
"""

from apps.core.models import SoftDeleteModel
from apps.core.permissions_catalog import ALL_PERMISSIONS

_registry: dict[str, tuple[type[SoftDeleteModel], str]] = {}


def register(model: type[SoftDeleteModel], code: str, permission: str) -> None:
    if not (isinstance(model, type) and issubclass(model, SoftDeleteModel)):
        raise ValueError(f"{model!r} не SoftDeleteModel")
    if not any(f.name == "company" and f.concrete for f in model._meta.get_fields()):
        raise ValueError(f"{model.__name__}: корзина поддерживает только модели компании")
    if permission not in ALL_PERMISSIONS:
        raise ValueError(f"Неизвестное право: {permission!r}")
    if code in _registry:
        raise ValueError(f"Тип корзины {code!r} уже зарегистрирован")
    _registry[code] = (model, permission)


def get(code: str) -> tuple[type[SoftDeleteModel], str] | None:
    return _registry.get(code)


def registered() -> dict[str, tuple[type[SoftDeleteModel], str]]:
    return dict(_registry)


def clear_registry() -> None:
    """ТОЛЬКО ДЛЯ ТЕСТОВ: очищает реестр (тест должен сам восстановить прежнее содержимое)."""
    _registry.clear()
