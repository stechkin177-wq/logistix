"""Фильтры списка заказов (список, канбан и Excel используют одни и те же).

Параметры: q (номер, клиент, название груза), client (id), status (несколько id: через запятую
и/или повторением параметра), carrier (id; заказ с не удалённым рейсом этого перевозчика,
везущим любой не удалённый груз заказа), loading_from/loading_to (дата самой ранней точки
погрузки заказа), created_from/created_to, completed_from/completed_to, unassigned=1 (заказы
без перевозчика). Даты - YYYY-MM-DD, сравниваются как локальные даты в часовом поясе компании,
границы включительно; from > to допустимо (пустой результат). Фильтры соединяются по И; всё
сделано через Exists/подзапросы, поэтому строки заказов не дублируются и N+1 нет. Неверное
значение - 400 с именем параметра, никогда не 500.
"""

from datetime import date, datetime, time, timedelta

from django.db.models import Exists, OuterRef, Q, Subquery
from django.utils.dateparse import parse_date
from rest_framework.exceptions import ValidationError

from apps.core.tenancy import get_current_company_id

from ..finance_lines.models import company_zone
from ..models import Consignment, ConsignmentPoint
from .services import carried_with_carrier

ORDERING_FIELDS = ("created_at", "number")
DEFAULT_ORDERING = "-created_at"
MAX_ID = 2**63 - 1  # BigAutoField: больше - заведомо несуществующий id, но не ошибка БД


def _one_id(name: str, raw: str) -> int:
    if not raw.isascii() or not raw.isdigit():
        raise ValidationError({name: "Ожидается числовой id"})
    value = int(raw)
    if value > MAX_ID:
        raise ValidationError({name: "Слишком большой id"})
    return value


def int_param(params, name):
    value = params.get(name)
    if value in (None, ""):
        return None
    return _one_id(name, value)


def int_list_param(params, name) -> list[int]:
    """Несколько id: ?name=1,2&name=3 -> [1, 2, 3] (пустые части пропускаются)."""
    result = []
    for raw in params.getlist(name):
        for part in raw.split(","):
            if part.strip():
                result.append(_one_id(name, part.strip()))
    return result


def flag_param(params, name) -> bool:
    value = (params.get(name) or "").strip().lower()
    if value in ("", "0", "false"):
        return False
    if value in ("1", "true"):
        return True
    raise ValidationError({name: "Допустимо: 1 или 0"})


def date_param(params, name) -> date | None:
    """Дата YYYY-MM-DD; невозможная или произвольный текст - 400 (в т.ч. OverflowError)."""
    raw = (params.get(name) or "").strip()
    if not raw:
        return None
    bad = ValidationError({name: "Ожидается корректная дата в формате ГГГГ-ММ-ДД"})
    if len(raw) != 10:
        raise bad
    try:
        day = parse_date(raw)
    except (ValueError, OverflowError):
        raise bad from None
    if day is None:
        raise bad
    return day


def _local_midnight(day: date, zone) -> datetime:
    return datetime.combine(day, time.min, tzinfo=zone)


def filter_local_dates(qs, field: str, params, prefix: str, zone):
    """<prefix>_from/<prefix>_to по полю datetime: локальные даты компании, включительно."""
    first = date_param(params, f"{prefix}_from")
    last = date_param(params, f"{prefix}_to")
    if first is not None:
        qs = qs.filter(**{f"{field}__gte": _local_midnight(first, zone)})
    if last is not None and last < date.max:
        qs = qs.filter(**{f"{field}__lt": _local_midnight(last + timedelta(days=1), zone)})
    return qs


def loading_at_subquery():
    """Самая ранняя ПЕРВАЯ погрузка заказа: window_from первой (по seq) остановки погрузки
    каждого из его не удалённых грузов."""
    first_load_seq = (
        ConsignmentPoint.objects.filter(
            consignment=OuterRef("consignment"), kind=ConsignmentPoint.LOAD
        )
        .order_by("seq")
        .values("seq")[:1]
    )
    return Subquery(
        ConsignmentPoint.objects.filter(
            consignment__order=OuterRef("pk"),
            consignment__deleted_at__isnull=True,
            kind=ConsignmentPoint.LOAD,
            seq=Subquery(first_load_seq),
        )
        .order_by("window_from")
        .values("window_from")[:1]
    )


def apply_filters(qs, params, zone=None):
    """Все фильтры списка, кроме сортировки. zone - пояс компании (по умолчанию - текущей)."""
    if zone is None:
        zone = company_zone(get_current_company_id())
    if (client := int_param(params, "client")) is not None:
        qs = qs.filter(client_id=client)
    if statuses := int_list_param(params, "status"):
        qs = qs.filter(status_id__in=statuses)
    if (carrier := int_param(params, "carrier")) is not None:
        qs = qs.filter(Exists(carried_with_carrier().filter(trip__carrier_id=carrier)))
    if flag_param(params, "unassigned"):
        qs = qs.filter(~Exists(carried_with_carrier()))
    if q := (params.get("q") or "").strip():
        by_cargo = Exists(Consignment.objects.filter(order=OuterRef("pk"), name__icontains=q))
        qs = qs.filter(Q(number__icontains=q) | Q(client__name__icontains=q) | by_cargo)
    if any(params.get(f"loading_{side}") for side in ("from", "to")):
        qs = filter_local_dates(
            qs.alias(loading_at_filter=loading_at_subquery()),
            "loading_at_filter",
            params,
            "loading",
            zone,
        )
    qs = filter_local_dates(qs, "created_at", params, "created", zone)
    qs = filter_local_dates(qs, "completed_at", params, "completed", zone)
    return qs


def apply_ordering(qs, params):
    ordering = params.get("ordering") or DEFAULT_ORDERING
    allowed = {*ORDERING_FIELDS, *(f"-{f}" for f in ORDERING_FIELDS)}
    if ordering not in allowed:
        raise ValidationError({"ordering": f"Допустимо: {', '.join(sorted(allowed))}"})
    return qs.order_by(ordering, "-id" if ordering.startswith("-") else "id")


def filter_orders(qs, params, zone=None):
    """Все фильтры и сортировка списка заказов."""
    return apply_ordering(apply_filters(qs, params, zone), params)
