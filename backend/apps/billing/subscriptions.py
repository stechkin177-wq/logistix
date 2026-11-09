"""Подписки компаний (T4): начало, смена тарифа, продление, анализ последствий.

Правила (решения заказчика):
 - тариф читается как данные: ни названия, ни число, ни цены тарифов в логике не участвуют;
 - смена тарифа НЕ меняет ``CompanyModule``: модули, которые компания отключила вручную, сами не
   включаются, а новые возможности (модули, функции, лимиты) становятся доступны сразу, потому что
   всё читается из тарифа в момент обращения; подключать новые модули владелец выбирает сам;
 - понижение не удаляет данные: сверх нового лимита блокируется только создание новых объектов,
   просмотр, правка и экспорт существующего сохраняются (модули, которых нет в новом тарифе,
   закрываются, данные остаются);
 - цена периода фиксируется в неизменяемой записи ``SubscriptionPeriod`` при его начале:
   изменение цены тарифа записанные периоды не трогает; новая цена применяется при продлении
   (новая запись) или при смене тарифа с новым периодом (``restart``);
 - платёжные интеграции не подключены: продление и «оплаченный» период подтверждает администратор
   платформы вне системы, система лишь хранит период и цену.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import status as http

from apps.core.audit import services as audit
from apps.core.tenancy import tenant_context

from . import features as feature_catalog
from . import limits as limit_catalog
from .models import Plan, Subscription, SubscriptionPeriod
from .plans import PlanError

KEEP = "keep"  # текущий период и его цена сохраняются до его окончания
RESTART = "restart"  # новый период начинается сейчас по цене нового тарифа


def add_months(moment: datetime, months: int) -> datetime:
    """Сдвиг на календарные месяцы с усечением дня (31 января + 1 месяц = 28/29 февраля)."""
    index = moment.month - 1 + months
    year, month = moment.year + index // 12, index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def period_end(plan: Plan, start: datetime) -> datetime | None:
    """Конец периода по виду оплаты тарифа; бессрочный - без конца."""
    if plan.billing_type == Plan.LIFETIME:
        return None
    return add_months(start, 1 if plan.billing_type == Plan.MONTHLY else 12)


def _record(sub: Subscription, plan: Plan, reason: str, start, end, price, *, free=False):
    return SubscriptionPeriod.objects.create(
        subscription=sub, plan_code=plan.code, reason=reason, starts_at=start, ends_at=end,
        price=price, currency=plan.currency, is_free=free,
    )  # fmt: skip


def current_period(sub: Subscription, now: datetime | None = None) -> SubscriptionPeriod | None:
    """Период, действующий сейчас (последний из начавшихся), иначе последний записанный."""
    now = now or timezone.now()
    periods = sub.periods.all()
    return periods.filter(starts_at__lte=now).order_by("-starts_at", "-id").first() or (
        periods.order_by("-starts_at", "-id").first()
    )


def start_subscription(company, plan: Plan, now: datetime | None = None) -> Subscription:
    """Подписка новой компании: бесплатный период тарифа (его срок - данные), иначе первый период.

    Без бесплатного периода первый период начинается сразу по цене тарифа; подтверждение оплаты
    вне системы (интеграции платежей не подключены).
    """
    now = now or timezone.now()
    free = plan.free_period_days > 0
    end = now + timedelta(days=plan.free_period_days) if free else period_end(plan, now)
    sub = Subscription.objects.create(
        company=company, plan=plan, status=Subscription.ACTIVE, is_free_period=free,
        starts_at=now, ends_at=end,
    )  # fmt: skip
    _record(sub, plan, SubscriptionPeriod.START, now, end, 0 if free else plan.price, free=free)
    return sub


def preview_change(company, new_plan: Plan) -> dict:
    """Что изменится у компании при переходе на тариф (без изменений в данных)."""
    from apps.core.module_services import enabled_module_codes

    sub = Subscription.objects.select_related("plan").get(company=company)
    period = current_period(sub)
    enabled = set(enabled_module_codes(company.pk))
    old_modules, new_modules = set(sub.plan.modules or []), set(new_plan.modules or [])
    lost_modules = sorted(enabled & old_modules - new_modules)
    gained_modules = sorted(new_modules - old_modules)
    old_f = feature_catalog.available_features(sub.plan, enabled & old_modules)
    new_f = feature_catalog.available_features(new_plan, enabled & new_modules)
    exceeded, tightened = [], []
    for spec in limit_catalog.LIMITS:
        code = spec["code"]
        new_limit = limit_catalog.plan_limit(new_plan, code)
        used = limit_catalog.usage(company.pk, code)
        old_limit = limit_catalog.plan_limit(sub.plan, code)
        row = {"code": code, "name": spec["name"], "usage": used, "old_limit": old_limit,
               "new_limit": new_limit}  # fmt: skip
        if new_limit is not None and used is not None and used > new_limit:
            exceeded.append(row)  # данные остаются, блокируется только создание нового
        elif new_limit is not None and (old_limit is None or new_limit < old_limit):
            tightened.append(row)
    return {
        "from_plan": sub.plan.code,
        "to_plan": new_plan.code,
        "price": {"current_period": str(period.price) if period else None,
                  "new": str(new_plan.price), "currency": new_plan.currency},  # fmt: skip
        "lost_modules": lost_modules,  # закрываются, данные сохраняются
        "gained_modules": gained_modules,  # доступны, но сами не включаются
        "lost_features": sorted(set(old_f) - set(new_f)),
        "gained_features": sorted(set(new_f) - set(old_f)),
        "limits_exceeded": exceeded,
        "limits_tightened": tightened,
    }


@transaction.atomic
def change_plan(company, new_plan: Plan, *, period: str = KEEP, user=None) -> Subscription:
    """Смена тарифа компании. ``CompanyModule`` не затрагивается.

    keep - действующий период, его срок и цена не меняются (новая цена вступит при продлении);
    restart - новый период с этого момента по цене нового тарифа (без бесплатного периода).
    """
    if period not in (KEEP, RESTART):
        raise PlanError("period_invalid", "period: keep или restart", http.HTTP_400_BAD_REQUEST)
    if new_plan.archived_at is not None:
        raise PlanError("plan_archived", "Нельзя перевести компанию на архивный тариф")
    sub = Subscription.objects.select_for_update().select_related("plan").get(company=company)
    if sub.plan_id == new_plan.pk and period == KEEP:
        return sub
    impact = preview_change(company, new_plan)
    before = {"plan": sub.plan.code, "ends_at": sub.ends_at}
    sub.plan = new_plan
    if period == RESTART:
        now = timezone.now()
        sub.starts_at, sub.ends_at = now, period_end(new_plan, now)
        sub.is_free_period = False
        sub.status = Subscription.ACTIVE
        _record(sub, new_plan, SubscriptionPeriod.PLAN_CHANGE, now, sub.ends_at, new_plan.price)
    sub.save()
    with tenant_context(company.pk):
        audit.log(
            "update", sub, user,
            {"plan": [before["plan"], new_plan.code], "period": period,
             "limits_exceeded": [r["code"] for r in impact["limits_exceeded"]],
             "lost_modules": impact["lost_modules"]},
            object_type="billing.subscription", object_id=sub.pk,
        )  # fmt: skip
    return sub


@transaction.atomic
def renew(company, *, periods: int = 1, user=None) -> Subscription:
    """Продление: период продолжается с конца текущего (или с этого момента, если он истёк) по
    ТЕКУЩЕЙ цене тарифа; цена снимается заново. Бессрочная подписка не продлевается."""
    if not isinstance(periods, int) or isinstance(periods, bool) or not 1 <= periods <= 24:
        raise PlanError("periods_invalid", "periods: от 1 до 24", http.HTTP_400_BAD_REQUEST)
    sub = Subscription.objects.select_for_update().select_related("plan").get(company=company)
    if sub.plan.billing_type == Plan.LIFETIME:
        raise PlanError("lifetime_not_renewable", "Бессрочная подписка не продлевается")
    now = timezone.now()
    start = max(sub.ends_at, now) if sub.ends_at else now
    end = start
    for _ in range(periods):
        end = period_end(sub.plan, end)
    before = {"ends_at": sub.ends_at}
    sub.ends_at, sub.is_free_period, sub.status = end, False, Subscription.ACTIVE
    sub.save()
    # новая запись по ТЕКУЩЕЙ цене тарифа; ранее записанные периоды остаются как были
    _record(sub, sub.plan, SubscriptionPeriod.RENEWAL, start, end, sub.plan.price * periods)
    with tenant_context(company.pk):
        audit.log(
            "update", sub, user,
            {"ends_at": [str(before["ends_at"]), str(end)], "periods": periods,
             "price": str(sub.plan.price * periods)},
            object_type="billing.subscription", object_id=sub.pk,
        )  # fmt: skip
    return sub
