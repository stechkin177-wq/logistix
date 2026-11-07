"""Закрытые финансовые периоды и запрет обратного датирования.

Две проверки НЕЗАВИСИМЫ и обе должны пройти (решение заказчика A):
- закрытый месяц (assert_period_open): без права finance.adjust_closed - 409 period_closed;
  с правом, но без причины - 400 period_reason_required; с правом и причиной операция
  допускается как корректировка закрытого периода (вызывающий пишет её в аудит);
- обратное датирование (assert_backdating_ok): при allow_backdating=False дата, введённая
  пользователем, не может быть раньше сегодняшней даты КОМПАНИИ (в её часовом поясе), если нет
  права finance.backdate. finance.adjust_closed это правило не отменяет.

Защита закрытого месяца действует при любом engine (legacy, shadow, new). Системные события
(признание дохода, перенос) обратное датирование не проверяют, только закрытый период.
"""

import calendar
from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.core.audit import services as audit
from apps.core.tenancy import get_current_company_id, tenant_context
from apps.forwarding.finance_lines.models import company_today

from .errors import FinanceError
from .models import CompanyFinancialSettings, FinancialPeriod, FinancialPeriodEvent

ADJUST_PERMISSION = "finance.adjust_closed"
BACKDATE_PERMISSION = "finance.backdate"


def _cid(company) -> int:
    return company if isinstance(company, int) else company.pk


def request_perms(request) -> frozenset:
    """Права текущего членства запроса (пусто, если членства нет)."""
    membership = getattr(request, "membership", None)
    role = membership.role if membership is not None else None
    return frozenset(role.permissions) if role is not None else frozenset()


def request_adjust_reason(request) -> str | None:
    data = getattr(request, "data", None)
    value = data.get("adjust_reason") if hasattr(data, "get") else None
    return value if isinstance(value, str) else None


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


@transaction.atomic
def close_period(company, year: int, month: int, user, comment: str = "") -> FinancialPeriod:
    """Закрывает полностью прошедший месяц; повторное закрытие закрытого - без нового события."""
    cid = _cid(company)
    if not (isinstance(year, int) and isinstance(month, int) and 1 <= month <= 12 and year >= 1):
        raise FinanceError("period_invalid", "Некорректный месяц")
    with tenant_context(cid):
        if _month_end(year, month) >= company_today(cid):
            raise FinanceError(
                "period_not_finished",
                "Закрыть можно только полностью прошедший месяц",
                status_code=409,
            )
        FinancialPeriod.objects.get_or_create(company_id=cid, year=year, month=month)
        period = FinancialPeriod.objects.select_for_update().get(year=year, month=month)
        if period.status == "closed":
            return period
        period.status = "closed"
        period.closed_at = timezone.now()
        period.closed_by = user if getattr(user, "pk", None) else None
        period.comment = comment or ""
        period.save()
        FinancialPeriodEvent.objects.create(
            company_id=cid,
            period=period,
            action="close",
            user=period.closed_by,
            reason=comment or "",
        )
        audit.log("update", period, user, {"status": ["open", "closed"], "comment": comment or ""})
        return period


@transaction.atomic
def reopen_period(period: FinancialPeriod, user, reason: str) -> FinancialPeriod:
    """Повторно открывает закрытый период; история событий сохраняется."""
    reason = (reason or "").strip()
    if not reason:
        raise FinanceError("reason_required", "Укажите причину повторного открытия периода")
    # контекст запроса не подменяется компанией объекта: чужой период не найдётся (DoesNotExist)
    with tenant_context(get_current_company_id() or period.company_id):
        locked = FinancialPeriod.objects.select_for_update().get(pk=period.pk)
        if locked.status != "closed":
            raise FinanceError("period_not_closed", "Период не закрыт", status_code=409)
        locked.status = "open"
        locked.closed_at = None
        locked.closed_by = None
        locked.save()
        FinancialPeriodEvent.objects.create(
            company_id=locked.company_id,
            period=locked,
            action="reopen",
            user=user if getattr(user, "pk", None) else None,
            reason=reason,
        )
        audit.log("update", locked, user, {"status": ["closed", "open"], "reason": reason})
        return locked


def is_period_closed(company, on_date: date) -> bool:
    cid = _cid(company)
    with tenant_context(cid):
        return FinancialPeriod.objects.filter(
            year=on_date.year, month=on_date.month, status="closed"
        ).exists()


def assert_period_open(
    company, on_date: date, *, can_adjust: bool = False, reason: str | None = None
) -> bool:
    """False - период открыт; True - закрыт, но допущена корректировка (есть право и причина)."""
    if not is_period_closed(company, on_date):
        return False
    if not can_adjust:
        raise FinanceError(
            "period_closed",
            f"Период {on_date.year}-{on_date.month:02d} закрыт: изменение запрещено",
            status_code=409,
        )
    if not (reason or "").strip():
        raise FinanceError(
            "period_reason_required",
            "Для корректировки закрытого периода укажите причину",
        )
    return True


def assert_backdating_ok(
    company, on_date: date, *, can_backdate: bool = False, today: date | None = None
) -> None:
    cid = _cid(company)
    with tenant_context(cid):
        allow = (
            CompanyFinancialSettings.objects.filter(company_id=cid)
            .values_list("allow_backdating", flat=True)
            .first()
        )
        if allow is None or allow or can_backdate:
            return
        today = today or company_today(cid)
    if on_date < today:
        raise FinanceError(
            "backdating_forbidden",
            "Ввод операций задним числом запрещён настройками компании",
            status_code=409,
        )


def check_user_date(company, on_date: date, perms, reason: str | None = None) -> bool:
    """Обе проверки для даты, введённой пользователем. True - корректировка закрытого периода."""
    adjusted = assert_period_open(
        company, on_date, can_adjust=ADJUST_PERMISSION in perms, reason=reason
    )
    assert_backdating_ok(company, on_date, can_backdate=BACKDATE_PERMISSION in perms)
    return adjusted


def check_system_date(company, on_date: date, perms=(), reason: str | None = None) -> bool:
    """Только закрытый период (без обратного датирования): дата не вводилась пользователем."""
    return assert_period_open(
        company, on_date, can_adjust=ADJUST_PERMISSION in perms, reason=reason
    )


def adjustment_changes(reason: str, old, new) -> dict:
    """Запись аудита о корректировке закрытого периода: старое/новое значение и причина."""
    return {"closed_period_adjustment": {"reason": reason.strip(), "old": old, "new": new}}


def log_adjustment(obj, user, reason: str, old, new, action: str = "update") -> None:
    audit.log(action, obj, user, adjustment_changes(reason, old, new))
