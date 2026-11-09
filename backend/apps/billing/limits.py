"""Количественные лимиты тарифов (T3).

Значения лимитов - данные тарифа (``Plan.limits``: {код: целое >= 0 | null}); администратор
платформы меняет их без изменения кода. Отсутствие ключа и ``null`` означают «без ограничений».
В коде лишь каталог измеряемых величин: что считается (модель, фильтр, всего или за календарный
месяц). Новый тип ограничения - одна запись каталога; вся остальная система не меняется.

Серверная проверка: при СОЗДАНИИ записи отслеживаемой модели (сигнал ``pre_save``) сверяется
использование компании с лимитом её тарифа. Существующие данные никогда не удаляются: если после
понижения тарифа использование выше нового лимита, блокируется только создание новых объектов;
после повышения тарифа ограничение снимается само (лимит читается из тарифа в момент проверки).
Нет подписки - проверка пропускается (доступ закрывает шлюз подписки). Массовые вставки
``bulk_create`` сигналов не вызывают и лимитом не проверяются.
"""

from __future__ import annotations

from django.apps import apps as django_apps
from django.db import connection
from django.db.models.signals import pre_save
from django.utils import timezone

TOTAL = "total"
MONTH = "month"

# enforced=False: тип объявлен (можно задать значение в тарифе), но измерять пока нечего
# (модуль появится позже), поэтому лимит не применяется.
LIMITS = [
    {"code": "max_users", "name": "Сотрудники", "unit": "чел.", "model": "core.Membership",
     "filter": {"is_active": True}, "scope": TOTAL},
    {"code": "max_vehicles", "name": "Техника", "unit": "ед.", "model": "fleet.Vehicle",
     "scope": TOTAL},
    {"code": "max_drivers", "name": "Водители", "unit": "чел.", "model": "drivers.Driver",
     "scope": TOTAL},
    {"code": "max_clients", "name": "Клиенты", "unit": "шт.", "model": "forwarding.Client",
     "scope": TOTAL},
    {"code": "max_carriers", "name": "Перевозчики", "unit": "шт.", "model": "forwarding.Carrier",
     "scope": TOTAL},
    {"code": "max_orders_per_month", "name": "Заказы в месяц", "unit": "шт.",
     "model": "forwarding.Order", "scope": MONTH, "date_field": "created_at"},
    {"code": "max_trips_per_month", "name": "Рейсы в месяц", "unit": "шт.",
     "model": "forwarding.Trip", "scope": MONTH, "date_field": "created_at"},
    {"code": "max_documents_per_month", "name": "Документы в месяц", "unit": "шт.",
     "model": "documents.IssuedDocument", "scope": MONTH, "date_field": "created_at"},
    {"code": "max_ocr_per_month", "name": "Распознавания документов в месяц", "unit": "шт.",
     "enforced": False},
]  # fmt: skip

BY_CODE = {spec["code"]: spec for spec in LIMITS}


class LimitError(ValueError):
    """Недопустимое значение лимита тарифа."""


def normalize(limits) -> dict:
    """Проверяет ``Plan.limits``: известные коды, значения - целые >= 0 или None (без лимита)."""
    if not isinstance(limits, dict):
        raise LimitError("limits: ожидается объект {код: число | null}")
    out = {}
    for code, value in limits.items():
        if code not in BY_CODE:
            raise LimitError(f"{code}: неизвестный лимит")
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10**9
        ):
            raise LimitError(f"{code}: целое число от 0 до 1000000000 или null (без ограничений)")
        out[code] = value
    return out


def plan_limit(plan, code: str) -> int | None:
    """Лимит тарифа по параметру; None - без ограничений (нет ключа или null)."""
    if code not in BY_CODE:
        raise ValueError(f"Неизвестный лимит: {code!r}")
    return (plan.limits or {}).get(code)


def _month_start(company_id: int):
    from zoneinfo import ZoneInfo

    from apps.core.models import Company

    tz = ZoneInfo(Company.objects.values_list("timezone", flat=True).get(pk=company_id))
    now = timezone.now().astimezone(tz)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def usage(company_id: int, code: str) -> int | None:
    """Текущее использование компанией (None - величина пока не измеряется)."""
    from apps.core.tenancy import tenant_context

    spec = BY_CODE[code]
    if spec.get("enforced", True) is False:
        return None
    model = django_apps.get_model(spec["model"])
    with tenant_context(company_id):
        qs = model._base_manager.filter(company_id=company_id, **spec.get("filter", {}))
        if any(f.name == "deleted_at" for f in model._meta.get_fields()):
            qs = qs.filter(deleted_at__isnull=True)  # удалённое в корзину в счёт не идёт
        if spec["scope"] == MONTH:
            qs = qs.filter(**{f"{spec['date_field']}__gte": _month_start(company_id)})
        return qs.count()


def check(company_id: int, code: str, adding: int = 1) -> None:
    """Бросает LimitExceeded, если создание ``adding`` объектов превысит лимит тарифа компании.

    Лимит не задан (None) - без проверки. Нет подписки - проверка пропускается. Внутри транзакции
    строка компании блокируется, поэтому два одновременных запроса не пройдут оба.
    """
    from apps.core.models import Company

    from .services import LimitExceeded, get_subscription

    spec = BY_CODE.get(code)
    if spec is None:
        raise ValueError(f"Неизвестный лимит: {code!r}")
    if spec.get("enforced", True) is False:
        return
    sub = get_subscription(company_id)
    if sub is None:
        return
    limit = plan_limit(sub.plan, code)
    if limit is None:
        return
    if connection.in_atomic_block:
        Company.objects.select_for_update().filter(pk=company_id).first()
    used = usage(company_id, code)
    if used + adding > limit:
        raise LimitExceeded(
            {
                "detail": f"Достигнут лимит тарифа: {spec['name'].lower()} - {limit}",
                "code": "limit_exceeded",
                "limit_code": code,
                "limit": limit,
                "usage": used,
            }
        )


def company_usage(company_id: int) -> list[dict]:
    """Использование и лимиты компании по всем типам (для интерфейса и предупреждений)."""
    from .services import get_subscription

    sub = get_subscription(company_id)
    rows = []
    for spec in LIMITS:
        limit = plan_limit(sub.plan, spec["code"]) if sub else None
        used = usage(company_id, spec["code"])
        rows.append(
            {
                "code": spec["code"],
                "name": spec["name"],
                "unit": spec["unit"],
                "scope": spec.get("scope", TOTAL),
                "limit": limit,
                "usage": used,
                "enforced": spec.get("enforced", True),
                "exceeded": limit is not None and used is not None and used > limit,
            }
        )
    return rows


def _handler(code: str, match: dict):
    def on_pre_save(sender, instance, raw=False, **kwargs):
        if raw or not instance._state.adding or getattr(instance, "company_id", None) is None:
            return
        if any(getattr(instance, key, None) != value for key, value in match.items()):
            return
        check(instance.company_id, code)

    return on_pre_save


def connect_signals() -> None:
    """Подключает серверную проверку создания к моделям каталога (идемпотентно)."""
    for spec in LIMITS:
        if spec.get("enforced", True) is False:
            continue
        model = django_apps.get_model(spec["model"])
        pre_save.connect(
            _handler(spec["code"], spec.get("filter", {})),
            sender=model,
            weak=False,
            dispatch_uid=f"limit:{spec['code']}",
        )

