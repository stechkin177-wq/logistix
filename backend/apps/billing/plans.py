"""Управление тарифами платформы (T1): создание, правка, публикация, архив, удаление, порядок.

Тарифы - данные: названия, число, цены, валюты, периоды и порядок задаёт администратор платформы.
Действующие подписки не ломаются: правка тарифа не меняет подписки, архивный тариф продолжает
работать у уже подключённых компаний, удалить можно только тариф без подписок.
"""

import re

from django.db import transaction
from django.db.models import Count, Max
from django.utils import timezone
from rest_framework import status as http
from rest_framework.exceptions import APIException

from apps.core import module_catalog

from . import features as feature_catalog
from . import limits as limit_catalog
from .models import Plan

CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,49}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
EDITABLE = (
    "name", "description", "billing_type", "price", "currency", "sort_order",
    "free_period_days", "limit_warn_percent",
)  # fmt: skip
CONTENT = ("modules", "features", "limits")  # состав тарифа: модули, функции (T2), лимиты (T3)
ORDER_STEP = 10


class PlanError(APIException):
    """Нарушение правил управления тарифами: {"detail", "code"}."""

    status_code = http.HTTP_409_CONFLICT

    def __init__(self, code: str, detail: str, status_code: int | None = None):
        super().__init__(detail={"detail": detail, "code": code}, code=code)
        if status_code is not None:
            self.status_code = status_code


def _bad(field: str, detail: str) -> PlanError:
    return PlanError("plan_invalid", f"{field}: {detail}", http.HTTP_400_BAD_REQUEST)


def _clean(data: dict) -> dict:
    out = dict(data)
    if "name" in out:
        out["name"] = str(out["name"]).strip()
        if not out["name"] or len(out["name"]) > 100:
            raise _bad("name", "укажите название (до 100 символов)")
    if "billing_type" in out and out["billing_type"] not in dict(Plan.BILLING_TYPES):
        raise _bad("billing_type", "допустимо: monthly, yearly, lifetime")
    if "currency" in out:
        out["currency"] = str(out["currency"]).strip().upper()
        if not CURRENCY_RE.match(out["currency"]):
            raise _bad("currency", "трёхбуквенный код валюты, например KZT")
    if "price" in out:
        try:
            from decimal import Decimal, InvalidOperation

            price = Decimal(str(out["price"]))
        except InvalidOperation:
            raise _bad("price", "ожидается число") from None
        if price < 0 or price != price.quantize(Decimal("0.01")) or price >= 10**12:
            raise _bad("price", "неотрицательное число не более чем с двумя знаками после запятой")
        out["price"] = price
    if "sort_order" in out:
        value = out["sort_order"]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1_000_000:
            raise _bad("sort_order", "целое число от 0 до 1000000")
    for key, top in (("free_period_days", 3650), ("limit_warn_percent", 100)):
        if key in out:
            value = out[key]
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= top:
                raise _bad(key, f"целое число от 0 до {top}")
    if "description" in out:
        out["description"] = str(out["description"]).strip()
    return out


def clean_modules(modules) -> list[str]:
    """Модули тарифа: известные не-core коды без повторов; жёсткие зависимости обязаны входить в
    тариф (иначе модуль включить нельзя). Профиль компании здесь не участвует."""
    if not isinstance(modules, list) or not all(isinstance(m, str) for m in modules):
        raise _bad("modules", "ожидается список кодов модулей")
    known = {m["code"]: m for m in module_catalog.MODULES if not m["is_core"]}
    unknown = sorted(set(modules) - set(known))
    if unknown:
        raise _bad("modules", f"неизвестные модули: {', '.join(unknown)}")
    result = list(dict.fromkeys(modules))
    missing = sorted(
        {
            f"{code} -> {dep}"
            for code in result
            for dep in known[code]["requires"]
            if dep != module_catalog.CORE and dep not in result
        }
    )
    if missing:
        raise PlanError(
            "plan_modules_incomplete",
            f"В тариф нужно добавить зависимости: {', '.join(missing)}",
            http.HTTP_400_BAD_REQUEST,
        )
    return result


def clean_limits(limits) -> dict:
    try:
        return limit_catalog.normalize(limits)
    except limit_catalog.LimitError as exc:
        raise _bad("limits", str(exc)) from None


def clean_features(features, modules) -> dict:
    try:
        return feature_catalog.normalize(features, modules)
    except feature_catalog.FeatureError as exc:
        raise _bad("features", str(exc)) from None


@transaction.atomic
def create_plan(*, code: str, **data) -> Plan:
    """Новый тариф: черновик (не предлагается, пока его не опубликуют); порядок - в конец."""
    code = str(code).strip().lower()
    if not CODE_RE.match(code):
        raise _bad("code", "латиница, цифры, «-» и «_», до 50 символов")
    if Plan.objects.filter(code=code).exists():
        raise PlanError("plan_code_taken", "Тариф с таким кодом уже есть")
    content = {k: data.pop(k) for k in CONTENT if k in data}
    data = _clean({"billing_type": Plan.MONTHLY, "currency": "KZT", "price": 0, **data})
    if "name" not in data:
        raise _bad("name", "укажите название")
    if "sort_order" not in data:
        last = Plan.objects.aggregate(m=Max("sort_order"))["m"]
        data["sort_order"] = (last or 0) + ORDER_STEP
    unknown = set(data) - set(EDITABLE)
    if unknown:
        raise _bad("fields", f"неизвестные поля: {', '.join(sorted(unknown))}")
    modules = clean_modules(content.get("modules", []))
    features = clean_features(content.get("features", {}), modules)
    limits = clean_limits(content.get("limits", {}))
    return Plan.objects.create(
        code=code, is_active=False, modules=modules, features=features, limits=limits, **data
    )


@transaction.atomic
def update_plan(plan: Plan, **data) -> Plan:
    """Правка содержимого тарифа; код не меняется. Действующие подписки не затрагиваются."""
    unknown = set(data) - set(EDITABLE) - set(CONTENT)
    if unknown:
        raise _bad("fields", f"нельзя менять: {', '.join(sorted(unknown))}")
    locked = Plan.objects.select_for_update().get(pk=plan.pk)
    content = {k: data[k] for k in CONTENT if k in data}
    for key, value in _clean({k: v for k, v in data.items() if k in EDITABLE}).items():
        setattr(locked, key, value)
    if "limits" in content:
        locked.limits = clean_limits(content["limits"])  # новые лимиты действуют сразу и без
        # удаления данных: сверх лимита блокируется только создание новых объектов
    if "modules" in content:
        locked.modules = clean_modules(content["modules"])
    if "modules" in content or "features" in content:
        # функции проверяются по итоговому набору модулей; убранный модуль убирает свои функции
        raw = content.get("features", locked.features)
        if "features" not in content:
            raw = {
                k: v
                for k, v in (locked.features or {}).items()
                if feature_catalog.BY_CODE[k]["module"] in ("core", *locked.modules)
            }
        locked.features = clean_features(raw, locked.modules)
    locked.save()
    return locked


@transaction.atomic
def publish(plan: Plan) -> Plan:
    locked = Plan.objects.select_for_update().get(pk=plan.pk)
    if locked.archived_at is not None:
        raise PlanError("plan_archived", "Архивный тариф сначала верните из архива")
    locked.is_active = True
    locked.save(update_fields=["is_active"])
    return locked


@transaction.atomic
def unpublish(plan: Plan) -> Plan:
    """Снять с предложения (в черновик). Тариф по умолчанию снять нельзя."""
    locked = Plan.objects.select_for_update().get(pk=plan.pk)
    if locked.is_default:
        raise PlanError("plan_is_default", "Сначала назначьте тарифом по умолчанию другой тариф")
    locked.is_active = False
    locked.save(update_fields=["is_active"])
    return locked


@transaction.atomic
def archive(plan: Plan) -> Plan:
    """В архив: не предлагается новым компаниям; действующие подписки продолжают работать."""
    locked = Plan.objects.select_for_update().get(pk=plan.pk)
    if locked.is_default:
        raise PlanError("plan_is_default", "Сначала назначьте тарифом по умолчанию другой тариф")
    locked.is_active = False
    locked.archived_at = locked.archived_at or timezone.now()
    locked.save(update_fields=["is_active", "archived_at"])
    return locked


@transaction.atomic
def restore(plan: Plan) -> Plan:
    """Из архива в черновик (публикуется отдельным действием)."""
    locked = Plan.objects.select_for_update().get(pk=plan.pk)
    locked.archived_at = None
    locked.save(update_fields=["archived_at"])
    return locked


@transaction.atomic
def set_default(plan: Plan) -> Plan:
    """Тариф для новых компаний: только опубликованный и не архивный; прежний снимается."""
    locked = Plan.objects.select_for_update().get(pk=plan.pk)
    if locked.archived_at is not None or not locked.is_active:
        raise PlanError("plan_not_published", "Тариф по умолчанию должен быть опубликованным")
    Plan.objects.exclude(pk=locked.pk).filter(is_default=True).update(is_default=False)
    locked.is_default = True
    locked.save(update_fields=["is_default"])
    return locked


@transaction.atomic
def delete_plan(plan: Plan) -> None:
    """Удаление возможно, только если нет подписок и тариф не по умолчанию; иначе - в архив."""
    locked = Plan.objects.select_for_update().get(pk=plan.pk)
    if locked.is_default:
        raise PlanError("plan_is_default", "Нельзя удалить тариф по умолчанию")
    if locked.subscriptions.exists():
        raise PlanError(
            "plan_has_subscriptions",
            "У тарифа есть подписки: отправьте его в архив, он останется у подключённых компаний",
        )
    locked.delete()


@transaction.atomic
def reorder(codes: list[str]) -> list[Plan]:
    """Порядок показа: тарифы списка получают 10, 20, ... по порядку, остальные идут после них."""
    plans = {p.code: p for p in Plan.objects.select_for_update()}
    if len(set(codes)) != len(codes) or not set(codes) <= set(plans):
        raise _bad("codes", "список должен содержать существующие коды без повторов")
    ordered = [plans[c] for c in codes] + [p for c, p in plans.items() if c not in codes]
    for index, plan in enumerate(ordered, start=1):
        plan.sort_order = index * ORDER_STEP
    Plan.objects.bulk_update(ordered, ["sort_order"])
    return ordered


def with_subscription_counts():
    # порядок задаётся явно: аннотация с группировкой сбрасывает Meta.ordering
    return Plan.objects.annotate(subscriptions_count=Count("subscriptions")).order_by(
        "sort_order", "id"
    )


def default_plan() -> Plan:
    """Тариф для новых компаний - опубликованный тариф с признаком is_default (данные, не код)."""
    plan = Plan.objects.filter(is_default=True, is_active=True, archived_at__isnull=True).first()
    if plan is None:
        raise PlanError(
            "no_default_plan",
            "Не назначен тариф по умолчанию для новых компаний",
            http.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return plan
