"""Сводка для главной страницы Центра управления: компании, подписки, выручка по периодам, тарифы,
пользователи и последние действия. Только платформенные данные (без таблиц компаний и без RLS)."""

from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.core.models import Company, Membership, User

from .models import BillingEvent, Plan, Subscription, SubscriptionPeriod
from .services import effective_status

EXPIRING_DAYS = 30
DAILY_MAX_DAYS = 62  # до двух месяцев - график по дням, дальше - по месяцам
LIST_LIMIT = 8


def _current_month(now):
    """Текущий календарный месяц как (первый день, последний день) - период по умолчанию."""
    today = timezone.localdate(now)
    first = today.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first, nxt - timedelta(days=1)


def _monthly_price(plan: Plan) -> Decimal:
    """Ежемесячный эквивалент цены тарифа (бессрочный - 0: регулярной оплаты нет)."""
    if plan.billing_type == Plan.MONTHLY:
        return plan.price
    if plan.billing_type == Plan.YEARLY:
        return plan.price / 12
    return Decimal(0)


def platform_dashboard(now=None, period=None) -> dict:
    now = now or timezone.now()
    subs = list(Subscription.objects.select_related("company", "plan"))
    status_counts: Counter = Counter()
    expiring, problem = [], []
    plan_counts: Counter = Counter()
    mrr = Decimal(0)
    free = 0
    for s in subs:
        st = effective_status(s, now)
        status_counts[st] += 1
        plan_counts[s.plan_id] += 1
        row = {
            "id": s.company_id, "name": s.company.name, "plan_name": s.plan.name,
            "status": st, "ends_at": s.ends_at,
        }  # fmt: skip
        if s.is_free_period:
            free += 1
        elif st in (Subscription.ACTIVE, Subscription.TRIAL) and s.plan.currency == "KZT":
            mrr += _monthly_price(s.plan)
        if st in (Subscription.ACTIVE, Subscription.TRIAL):
            if s.ends_at and now <= s.ends_at <= now + timedelta(days=EXPIRING_DAYS):
                expiring.append(row)
        elif st != Subscription.BLOCKED or s.ends_at:
            problem.append(row)
    expiring.sort(key=lambda r: r["ends_at"])
    problem.sort(key=lambda r: r["ends_at"] or now)

    plans = [
        {
            "code": p.code, "name": p.name, "status": p.status,
            "subscriptions": plan_counts.get(p.pk, 0),
            "price": p.price, "currency": p.currency, "billing_type": p.billing_type,
        }
        for p in Plan.objects.order_by("sort_order", "id")
    ]  # fmt: skip

    first, last = period or _current_month(now)
    days = (last - first).days + 1
    daily = days <= DAILY_MAX_DAYS
    paid_rows = list(
        SubscriptionPeriod.objects.filter(
            starts_at__date__gte=first, starts_at__date__lte=last, is_free=False, currency="KZT"
        ).values_list("starts_at", "price")
    )
    created_rows = list(
        Company.objects.filter(created_at__date__gte=first, created_at__date__lte=last).values_list(
            "created_at", flat=True
        )
    )
    tz = timezone.get_current_timezone()
    bucket_of = (
        (lambda dt: timezone.localtime(dt, tz).date().isoformat())
        if daily
        else (lambda dt: timezone.localtime(dt, tz).strftime("%Y-%m"))
    )
    revenue_by: dict[str, Decimal] = {}
    new_by: Counter = Counter()
    for starts_at, price in paid_rows:
        revenue_by[bucket_of(starts_at)] = revenue_by.get(bucket_of(starts_at), Decimal(0)) + price
    for created in created_rows:
        new_by[bucket_of(created)] += 1
    buckets, cursor = [], first
    while cursor <= last:
        key = cursor.isoformat() if daily else cursor.strftime("%Y-%m")
        if not buckets or buckets[-1]["bucket"] != key:
            buckets.append(
                {
                    "bucket": key,
                    "revenue": revenue_by.get(key, Decimal(0)),
                    "new": new_by.get(key, 0),
                }
            )
        cursor += timedelta(days=1)
    period_revenue = sum(revenue_by.values(), Decimal(0))

    companies_total = Company.objects.count()
    week = now - timedelta(days=7)
    recent = BillingEvent.objects.order_by("-id")[:LIST_LIMIT]
    return {
        "generated_at": now,
        "period": {"from": first, "to": last, "granularity": "day" if daily else "month"},
        "companies": {
            "total": companies_total,
            "with_bin": Company.objects.exclude(bin="").count(),
            "new_period": len(created_rows),
        },
        "subscriptions": {
            "total": len(subs),
            "by_status": {k: status_counts.get(k, 0) for k, _ in Subscription.STATUSES},
            "free_period": free,
            "expiring": expiring[:LIST_LIMIT],
            "expiring_count": len(expiring),
            "problem": problem[:LIST_LIMIT],
            "problem_count": len(problem),
        },
        "revenue": {
            "currency": "KZT",
            "mrr": mrr,
            "period": period_revenue,
            "by_bucket": buckets,
        },
        "plans": plans,
        "users": {
            "total": User.objects.filter(is_active=True).count(),
            "platform": User.objects.exclude(platform_role="").count(),
            "memberships": Membership.objects.filter(is_active=True).count(),
            "per_company_avg": round(
                Membership.objects.filter(is_active=True).count() / companies_total, 1
            )
            if companies_total
            else 0,
        },
        "activity": {
            "logins_7d": BillingEvent.objects.filter(
                kind=BillingEvent.AUTH, action="login", created_at__gte=week
            ).count(),
            "changes_7d": BillingEvent.objects.exclude(kind=BillingEvent.AUTH)
            .filter(created_at__gte=week)
            .count(),
            "recent": [
                {
                    "id": e.pk,
                    "kind": e.kind,
                    "key": e.key,
                    "action": e.action,
                    "actor": e.actor,
                    "created_at": e.created_at,
                }
                for e in recent
            ],
        },
    }
