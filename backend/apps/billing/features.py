"""Функции внутри модулей (T2): каталог в коде, значения по тарифам - данные.

Каталог перечисляет функции, которые код умеет проверять (код, модуль-владелец, вид: включено/
выключено или уровень). Какие из них входят в тариф и на каком уровне, задаёт администратор
платформы в ``Plan.features`` без изменения кода. Функция доступна компании, только если модуль-
владелец включён у компании и есть в тарифе (``core`` всегда включён) и функция есть в тарифе.
Профиль компании в этом не участвует: он лишь рекомендует стартовый набор модулей.

Серверная проверка: ``has_feature`` / ``FeatureRequired``. Подключать их к конкретным операциям
нужно по мере появления самих функций (аналитика, интеграции, автоматизация и т.д.).
"""

from __future__ import annotations

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

BOOL = "bool"
LEVEL = "level"

# kind=bool: значение True/False; kind=level: один из levels по возрастанию (чем правее - тем шире).
FEATURES = [
    {"code": "white_label", "module": "core", "kind": BOOL, "name": "Собственный брендинг",
     "description": "Своё название, логотип и цвета"},
    {"code": "custom_domain", "module": "core", "kind": BOOL, "name": "Собственный домен",
     "description": "Вход по домену компании"},
    {"code": "analytics_level", "module": "analytics", "kind": LEVEL,
     "levels": ["basic", "extended", "full"], "name": "Аналитика",
     "description": "Глубина отчётов и дашбордов"},
    {"code": "api_access", "module": "core", "kind": LEVEL, "levels": ["limited", "extended"],
     "name": "API и интеграции", "description": "Доступ к API и интеграциям"},
    {"code": "automation", "module": "core", "kind": LEVEL,
     "levels": ["basic", "advanced", "full"], "name": "Автоматизация",
     "description": "Правила и автоматические действия"},
    {"code": "history_reports", "module": "core", "kind": LEVEL,
     "levels": ["limited", "extended", "full"], "name": "История и отчёты",
     "description": "Глубина хранения истории и отчётов"},
    {"code": "multi_branch", "module": "core", "kind": BOOL, "name": "Несколько филиалов",
     "description": "Работа с несколькими филиалами"},
    {"code": "priority_support", "module": "core", "kind": BOOL, "name": "Приоритетная поддержка",
     "description": "Приоритет в поддержке"},
]  # fmt: skip

BY_CODE = {f["code"]: f for f in FEATURES}


class FeatureError(ValueError):
    """Недопустимое значение функции тарифа."""


def normalize(features: dict, plan_modules) -> dict:
    """Проверяет и нормализует ``Plan.features``: известные коды, допустимые значения, модуль-
    владелец входит в тариф. Выключенные функции (False) не хранятся."""
    if not isinstance(features, dict):
        raise FeatureError("features: ожидается объект {код: значение}")
    modules = set(plan_modules or [])
    out: dict = {}
    for code, value in features.items():
        spec = BY_CODE.get(code)
        if spec is None:
            raise FeatureError(f"{code}: неизвестная функция")
        if spec["kind"] == BOOL:
            if not isinstance(value, bool):
                raise FeatureError(f"{code}: допустимо true или false")
            enabled = value
        else:
            if value in (None, False):
                continue
            if value not in spec["levels"]:
                raise FeatureError(f"{code}: допустимо {', '.join(spec['levels'])} или выключено")
            enabled = True
        if enabled and spec["module"] != "core" and spec["module"] not in modules:
            raise FeatureError(f"{code}: модуль «{spec['module']}» не входит в тариф")
        if enabled:
            out[code] = value
    return out


def plan_feature_value(plan, code: str):
    """Значение функции в тарифе (True / уровень) или None, если её нет или модуль не в тарифе."""
    spec = BY_CODE.get(code)
    if spec is None:
        raise ValueError(f"Неизвестная функция: {code!r}")
    value = (plan.features or {}).get(code)
    if not value:
        return None
    if spec["module"] != "core" and spec["module"] not in (plan.modules or []):
        return None
    return value


def company_feature_value(company_id: int, code: str):
    """Значение функции для компании: тариф И включённый у компании модуль-владелец.

    Профиль на доступ не влияет. Нет подписки - функция недоступна.
    """
    from apps.core.module_services import enabled_module_codes

    from .services import get_subscription

    sub = get_subscription(company_id)
    if sub is None:
        return None
    value = plan_feature_value(sub.plan, code)
    if value is None:
        return None
    module = BY_CODE[code]["module"]
    if module != "core" and module not in enabled_module_codes(company_id):
        return None
    return value


def level_reaches(code: str, value, minimum: str) -> bool:
    spec = BY_CODE[code]
    if spec["kind"] != LEVEL or minimum not in spec["levels"]:
        raise ValueError(f"{code}: уровень {minimum!r} не определён")
    return value in spec["levels"] and spec["levels"].index(value) >= spec["levels"].index(minimum)


def has_feature(company_id: int, code: str, minimum: str | None = None) -> bool:
    value = company_feature_value(company_id, code)
    if value is None:
        return False
    return level_reaches(code, value, minimum) if minimum else True


def available_features(plan, effective_modules) -> dict:
    """Доступные функции {код: True | уровень} по тарифу и уже известным эффективным модулям
    компании (без запросов к БД)."""
    modules = set(effective_modules)
    result = {}
    for spec in FEATURES:
        value = plan_feature_value(plan, spec["code"])
        if value is not None and (spec["module"] == "core" or spec["module"] in modules):
            result[spec["code"]] = value
    return result


def company_features(company_id: int) -> dict:
    """Все доступные компании функции (для интерфейса и проверок)."""
    from apps.core.module_services import enabled_module_codes

    from .services import get_subscription

    sub = get_subscription(company_id)
    if sub is None:
        return {}
    return available_features(sub.plan, enabled_module_codes(company_id))


class FeatureUnavailable(PermissionDenied):
    default_detail = "Функция недоступна на вашем тарифе"
    default_code = "feature_unavailable"


def FeatureRequired(code: str, minimum: str | None = None) -> type[BasePermission]:  # noqa: N802
    """Фабрика DRF-права: функция есть в тарифе компании (не ниже уровня ``minimum``)."""
    if code not in BY_CODE:
        raise ValueError(f"Неизвестная функция: {code!r}")

    class _FeatureRequired(BasePermission):
        def has_permission(self, request, view):
            membership = getattr(request, "membership", None)
            if membership is None:
                return False
            if not has_feature(membership.company_id, code, minimum):
                raise FeatureUnavailable()
            return True

    _FeatureRequired.__name__ = f"FeatureRequired[{code}]"
    return _FeatureRequired
