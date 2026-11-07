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
PROTECTED_FIELDS = ("code", "is_active", "is_final")

MSG_CODE = "Системный код нельзя изменять"
MSG_DELETE = "Системное значение справочника нельзя удалить"
MSG_DEACTIVATE = "Системное значение справочника нельзя деактивировать"
MSG_FINAL = "Признак «финальный» у системного значения нельзя изменять"
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


def assignment_allowed() -> bool:
    return _assignment_allowed.get()


def reserved_codes(handbook_code: str) -> frozenset[str]:
    return SYSTEM_CODES.get(handbook_code, frozenset())


def is_system_code(handbook_code: str, code: str) -> bool:
    return bool(code) and code in reserved_codes(handbook_code)


def check_change(
    handbook_code: str,
    *,
    old: dict | None,
    new: dict,
    fields: set[str] | None = None,
) -> None:
    """Проверка одного изменения значения; бросает SystemValueProtected.

    old - прежние code/is_active/is_final/handbook_code (None при создании); new - итоговые
    значения тех же ключей; fields - какие поля реально пишутся (None = все).
    """

    def touched(name):
        return fields is None or name in fields

    reserved = reserved_codes(handbook_code)
    new_code = new.get("code", "")
    if old is None:
        if new_code in reserved and new_code and not assignment_allowed():
            raise SystemValueProtected(MSG_RESERVED, "code")
        return
    old_system = is_system_code(old["handbook_code"], old["code"])
    if old_system:
        if touched("handbook") and old["handbook_code"] != handbook_code:
            raise SystemValueProtected(MSG_MOVE, "handbook")
        if touched("code") and new_code != old["code"]:
            raise SystemValueProtected(MSG_CODE, "code")
        if touched("is_active") and old["is_active"] and not new.get("is_active", True):
            raise SystemValueProtected(MSG_DEACTIVATE, "is_active")
        if touched("is_final") and new.get("is_final", False) != old["is_final"]:
            raise SystemValueProtected(MSG_FINAL, "is_final")
        return
    if touched("code") and new_code and new_code in reserved and not assignment_allowed():
        raise SystemValueProtected(MSG_RESERVED, "code")
