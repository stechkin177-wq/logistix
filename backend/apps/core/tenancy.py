"""Текущая компания запроса/задачи. Без импортов Django-моделей."""

from contextlib import contextmanager
from contextvars import ContextVar, Token

_current_company_id: ContextVar[int | None] = ContextVar("current_company_id", default=None)


class NoTenantContext(Exception):
    """Обращение к данным компании без установленного контекста компании."""


class TenantMismatch(Exception):
    """Запись принадлежит другой компании, чем текущий контекст."""


def get_current_company_id() -> int | None:
    return _current_company_id.get()


def set_current_company(company_id: int | None) -> Token:
    """Устанавливает компанию; вернувшийся токен нужно передать в reset_current_company."""
    return _current_company_id.set(company_id)


def reset_current_company(token: Token) -> None:
    _current_company_id.reset(token)


@contextmanager
def tenant_context(company_id: int | None):
    """Контекст компании; при выходе (в том числе по исключению) всегда сбрасывается."""
    token = set_current_company(company_id)
    try:
        yield
    finally:
        reset_current_company(token)
