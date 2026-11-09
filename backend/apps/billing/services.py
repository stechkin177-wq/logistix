import math
from datetime import datetime, timedelta

from django.utils import timezone
from rest_framework import status as http
from rest_framework.exceptions import APIException

from .models import Plan, Subscription

GRACE_DAYS = 14
READONLY_DAYS = 30



class LimitExceeded(APIException):
    status_code = http.HTTP_402_PAYMENT_REQUIRED
    default_detail = "Достигнут лимит тарифа"
    default_code = "limit_exceeded"

    def __init__(self, payload: dict | None = None):
        """payload - тело ответа как есть (числа остаются числами): detail, code, limit_code,
        limit, usage."""
        super().__init__(detail=payload["detail"] if payload else None)
        self.payload = payload


def effective_status(sub: Subscription, now: datetime) -> str:
    """Фактический статус: ручная блокировка главнее, иначе считается по датам."""
    if sub.status == Subscription.BLOCKED:
        return Subscription.BLOCKED
    held = Subscription.TRIAL if sub.status == Subscription.TRIAL else Subscription.ACTIVE
    if sub.plan.billing_type == Plan.LIFETIME or sub.ends_at is None:
        return held
    if now <= sub.ends_at:
        return held
    grace_end = sub.ends_at + timedelta(days=GRACE_DAYS)
    if now <= grace_end:
        return Subscription.GRACE
    if now <= grace_end + timedelta(days=READONLY_DAYS):
        return Subscription.READONLY
    return Subscription.BLOCKED


def days_left(sub: Subscription, now: datetime) -> int | None:
    """Дней до окончания подписки (неполные сутки считаются за день); None - бессрочно."""
    if sub.ends_at is None:
        return None
    return max(0, math.ceil((sub.ends_at - now).total_seconds() / 86400))


def grace_days_left(sub: Subscription, now: datetime) -> int | None:
    """Дней льготного периода до перехода в «только чтение» (только в статусе grace, иначе None)."""
    if effective_status(sub, now) != Subscription.GRACE:
        return None
    grace_end = sub.ends_at + timedelta(days=GRACE_DAYS)
    return max(0, math.ceil((grace_end - now).total_seconds() / 86400))


def get_subscription(company_id) -> Subscription | None:
    return Subscription.objects.select_related("plan").filter(company_id=company_id).first()


def company_status(company_id, now: datetime | None = None) -> str:
    """Фактический статус компании; нет подписки = blocked."""
    sub = get_subscription(company_id)
    if sub is None:
        return Subscription.BLOCKED
    return effective_status(sub, now or timezone.now())


def check_limit(company, key: str, current: int) -> None:
    """Бросает LimitExceeded, если лимит задан и current >= лимита.

    Нет подписки = как blocked (отказ). null в лимите = без ограничений.
    """
    from .limits import BY_CODE

    if key not in BY_CODE:
        raise ValueError(f"Неизвестный лимит: {key!r}")
    sub = get_subscription(company.pk)
    if sub is None:
        raise LimitExceeded()
    limit = sub.plan.limits.get(key)
    if limit is not None and current >= limit:
        raise LimitExceeded()
