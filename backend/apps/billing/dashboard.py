"""Сводка для главной страницы Центра управления: компании, подписки, выручка по периодам, тарифы,
пользователи и последние действия. Только платформенные данные (без таблиц компаний и без RLS)."""

from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from apps.core.models import Company, Membership, User

from .models import BillingEvent, Plan, Subscription, SubscriptionPeriod
from .services import effective_status

EXPIRING_DAYS = 30
MONTHS = 12
LIST_LIMIT = 8


def _month_start(dt, back=0):
    """Первое число месяца (на `back` месяцев раньше) в часовом поясе сервера."""
    y, m = dt.year, dt.month - back
    while m <= 0:
        y, m = y - 1, m + 12
    return dt.replace(year=y, month=m, day=1, hour=0, minute=0, second=0, microsecond=0)


def _monthly_price(plan: Plan) -> Decimal:
    """Ежемесячный эквивалент цены тарифа (бессрочный - 0: регулярной оплаты нет)."""
    if plan.billing_type == Plan.MONTHLY:
        return plan.price
    if plan.billing_type == Plan.YEARLY:
        return plan.price / 12
    return Decimal(0)


def platform_dashboard(now=None) -> dict:
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

    first = _month_start(now, MONTHS - 1)
    periods = SubscriptionPeriod.objects.filter(starts_at__gte=first)
    months = []
    for i in range(MONTHS - 1, -1, -1):
        start, end = _month_start(now, i), _month_start(now, i - 1) if i else None
        flt = Q(starts_at__gte=start) & (Q(starts_at__lt=end) if end else Q())
        paid = periods.filter(flt, is_free=False, currency="KZT").aggregate(s=Sum("price"))["s"]
        months.append(
            {
                "month": start.strftime("%Y-%m"),
                "revenue": paid or Decimal(0),
                "new": Company.objects.filter(
                    Q(created_at__gte=start) & (Q(created_at__lt=end) if end else Q())
                ).count(),
            }
        )
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    year_revenue = SubscriptionPeriod.objects.filter(
        starts_at__gte=year_start, is_free=False, currency="KZT"
    ).aggregate(s=Sum("price"))["s"] or Decimal(0)

    companies_total = Company.objects.count()
    week = now - timedelta(days=7)
    recent = BillingEvent.objects.order_by("-id")[:LIST_LIMIT]
    return {
        "generated_at": now,
        "companies": {
            "total": companies_total,
            "with_bin": Company.objects.exclude(bin="").count(),
            "new_30d": Company.objects.filter(created_at__gte=now - timedelta(days=30)).count(),
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
            "month": months[-1]["revenue"],
            "year": year_revenue,
            "by_month": months,
        },  # fmt: skip
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
