"""Журнал изменений тарифов и подписок (T5): запись событий и сравнение состояний."""

from __future__ import annotations

from decimal import Decimal

from .models import BillingEvent, Plan

PLAN_FIELDS = (
    "name", "description", "billing_type", "price", "currency", "sort_order",
    "free_period_days", "limit_warn_percent", "modules", "features", "limits",
)  # fmt: skip


def plan_state(plan: Plan) -> dict:
    """Состояние тарифа для журнала (значения приведены к JSON)."""
    state = {name: getattr(plan, name) for name in PLAN_FIELDS}
    for key, value in state.items():
        if isinstance(value, Decimal):
            state[key] = str(value.quantize(Decimal("0.01")))  # одинаково до и после записи в БД
    state["status"] = plan.status
    state["is_default"] = plan.is_default
    return state


def diff(before: dict, after: dict) -> dict:
    """{поле: [было, стало]} только для изменившихся значений."""
    return {
        key: [before.get(key), after.get(key)]
        for key in {*before, *after}
        if before.get(key) != after.get(key)
    }


def record(kind: str, key, action: str, changes: dict | None = None, user=None) -> BillingEvent:
    user = user if getattr(user, "pk", None) else None
    return BillingEvent.objects.create(
        kind=kind,
        key=str(key),
        action=action,
        changes=changes or {},
        user=user,
        actor=getattr(user, "email", "") or getattr(user, "phone", "") or "",
    )
