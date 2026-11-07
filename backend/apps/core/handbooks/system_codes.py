"""Реестр системных кодов справочников и защита от их изменения.

Системным считается значение, чей код входит в реестр ЕГО справочника. Такой код читает
бизнес-логика (completed_at заказа, завершение рейса), поэтому его нельзя менять, удалять
и деактивировать, нельзя менять признак is_final; название, порядок и прочие неключевые поля
правятся свободно. Код из реестра нельзя присвоить несистемному значению того же справочника
(даже если системного значения сейчас нет). Правила проверяются в API, в модели
(save/delete) и в queryset-методах delete/update, а не только в интерфейсе.

Единственный способ назначить системный код существующему значению без кода -
system_code_assignment() (используется командой assign_system_status_code).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from rest_framework.exceptions import ValidationError

# handbook_code -> коды, зарезервированные системой. Расширяется добавлением записи.
SYSTEM_CODES: dict[str, frozenset[str]] = {
    "order_status": frozenset({"completed", "cancelled"}),
    "trip_status": frozenset(
        {"PLANNED", "ASSIGNED", "IN_PROGRESS", "UNLOADING", "COMPLETED", "CANCELLED"}
    ),
}

# Поля, изменение которых у системного значения запрещено
PROTECTED_FIELDS = ("code", "is_active", "is_final", "is_initial")
# поля, при записи которых проверяется защита (включая перенос в другой справочник)
GUARDED_FIELDS = frozenset({*PROTECTED_FIELDS, "handbook", "handbook_id"})

MSG_CODE = "Системный код нельзя изменять"
MSG_DELETE = "Системное значение справочника нельзя удалить"
MSG_DEACTIVATE = "Системное значение справочника нельзя деактивировать"
MSG_FINAL = "Признак «финальный» у системного значения нельзя изменять"
MSG_INITIAL = "Признак «начальный» у системного значения нельзя изменять"
MSG_MAKE_INITIAL = "Начальный статус «{name}» системный: назначить начальным другое значение нельзя"
MSG_UPSERT = "Массовое создание с обновлением (upsert) справочников запрещено"
MSG_MOVE = "Нельзя перенести значение в другой справочник"
MSG_RESERVED = "Код зарезервирован системой и не может быть присвоен другому значению"


class SystemValueProtected(ValidationError):
    """Попытка нарушить защиту системного значения; для API - 400 с текстом на русском."""

    def __init__(self, message: str, field: str = "detail"):
        super().__init__({field: [message]})


_assignment_allowed: ContextVar[bool] = ContextVar("system_code_assignment", default=False)


@contextmanager
def system_code_assignment() -> Iterator[None]:
    """Разрешает присвоить системный код значению (только для сервиса ручного назначения)."""
    token = _assignment_allowed.set(True)
    try:
        yield
    finally:
        _assignment_allowed.reset(token)


_maintenance_allowed: ContextVar[bool] = ContextVar("system_values_maintenance", default=False)


@contextmanager
def system_values_maintenance() -> Iterator[None]:
    """Полный внутренний обход защиты (служебное удаление компании, очистка данных).

    Только для кода сопровождения; из API недостижим. Покрыт тестом."""
    token = _maintenance_allowed.set(True)
    try:
        yield
    finally:
        _maintenance_allowed.reset(token)


def maintenance_allowed() -> bool:
    return _maintenance_allowed.get()


def assignment_allowed() -> bool:
    return _assignment_allowed.get()


def reserved_codes(handbook_code: str) -> frozenset[str]:
    return SYSTEM_CODES.get(handbook_code, frozenset())


def is_system_code(handbook_code: str, code: str) -> bool:
    return bool(code) and code in reserved_codes(handbook_code)


def check_change(old: dict | None, new: dict) -> None:
    """Проверка одного изменения значения; бросает SystemValueProtected.

    old - СТРОКА ИЗ БД до изменения (None при создании), а не атрибуты объекта в памяти;
    new - итоговые значения. Ключи обоих: handbook_id, handbook_code, code, is_active,
    is_final, is_initial.
    """
    if maintenance_allowed():
        return
    new_reserved = reserved_codes(new["handbook_code"])
    if old is not None and is_system_code(old["handbook_code"], old["code"]):
        if new["handbook_id"] != old["handbook_id"] or new["handbook_code"] != old["handbook_code"]:
            raise SystemValueProtected(MSG_MOVE, "handbook")
        if new["code"] != old["code"]:
            raise SystemValueProtected(MSG_CODE, "code")
        if old["is_active"] and not new["is_active"]:
            raise SystemValueProtected(MSG_DEACTIVATE, "is_active")
        if bool(new["is_final"]) != bool(old["is_final"]):
            raise SystemValueProtected(MSG_FINAL, "is_final")
        if bool(new["is_initial"]) != bool(old["is_initial"]):
            raise SystemValueProtected(MSG_INITIAL, "is_initial")
        return
    # создание или несистемное значение: код из реестра присвоить нельзя
    if new["code"] and new["code"] in new_reserved and not assignment_allowed():
        raise SystemValueProtected(MSG_RESERVED, "code")
