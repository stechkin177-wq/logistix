from datetime import datetime, timedelta

from django.utils import timezone
from rest_framework import status as http
from rest_framework.exceptions import APIException

from .models import Plan, Subscription

GRACE_DAYS = 14
READONLY_DAYS = 30

LIMIT_KEYS = ("max_users", "max_vehicles", "max_orders_per_month", "max_ocr_per_month")


class LimitExceeded(APIException):
    status_code = http.HTTP_402_PAYMENT_REQUIRED
    default_detail = "Достигнут лимит тарифа"
    default_code = "limit_exceeded"


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
    if key not in LIMIT_KEYS:
        raise ValueError(f"Неизвестный лимит: {key!r}")
    sub = get_subscription(company.pk)
    if sub is None:
        raise LimitExceeded()
    limit = sub.plan.limits.get(key)
    if limit is not None and current >= limit:
        raise LimitExceeded()
