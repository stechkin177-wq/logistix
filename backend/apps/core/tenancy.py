"""Текущая компания запроса/задачи. Без импортов Django-моделей."""

from contextvars import ContextVar

_current_company_id: ContextVar[int | None] = ContextVar("current_company_id", default=None)


class NoTenantContext(Exception):
    """Обращение к данным компании без установленного контекста компании."""


def get_current_company_id() -> int | None:
    return _current_company_id.get()


def set_current_company(company_id: int | None) -> None:
    _current_company_id.set(company_id)
