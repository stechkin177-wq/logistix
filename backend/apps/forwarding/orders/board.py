"""Канбан заказов: GET /api/orders/board/.

Колонка на каждое значение справочника order_status (по порядку справочника, пустые тоже;
неактивные - только если в них есть подходящие заказы). Фильтры те же, что у списка заказов.
count - точное число подходящих не удалённых заказов статуса; orders - не более limit карточек
колонки по -created_at; has_more - есть ли ещё. Запросов к БД фиксированное число (11 вместе
со входом и подпиской, не зависит от числа заказов и колонок): статусы, счётчики, карточки одним
запросом с оконной нумерацией по колонкам, грузы с точками, перевозчики.
"""

from collections import defaultdict

from django.db.models import Count, Exists, F, Prefetch, Q, Window
from django.db.models.functions import RowNumber
from rest_framework.exceptions import ValidationError

from apps.core.handbooks.models import HandbookValue

from ..models import Consignment, Order, TripConsignment
from .filters import apply_filters, loading_at_subquery
from .serializers import order_route
from .services import carried_with_carrier

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def limit_param(params) -> int:
    raw = params.get("limit")
    if raw in (None, ""):
        return DEFAULT_LIMIT
    if not raw.isascii() or not raw.isdigit() or not 1 <= int(raw) <= MAX_LIMIT:
        raise ValidationError({"limit": f"Ожидается целое число от 1 до {MAX_LIMIT}"})
    return int(raw)


def carrier_names(order_ids) -> dict[int, list[str]]:
    """{id заказа: отсортированные уникальные названия перевозчиков его не удалённых рейсов}."""
    rows = (
        TripConsignment.objects.filter(
            consignment__order_id__in=order_ids,
            consignment__deleted_at__isnull=True,
            trip__deleted_at__isnull=True,
            trip__carrier__isnull=False,
        )
        .order_by("trip__carrier__name")
        .values_list("consignment__order_id", "trip__carrier__name")
        .distinct()
    )
    names = defaultdict(list)
    for order_id, name in rows:
        names[order_id].append(name)
    return names


def routed(qs):
    """Грузы заказов с точками - для маршрута без запроса на заказ."""
    return qs.prefetch_related(
        Prefetch(
            "consignments",
            queryset=Consignment.objects.order_by("id").prefetch_related("points"),
        )
    )


def money(value) -> str:
    return format(value, "f")


def card(order, carriers, zone) -> dict:
    loading = order.loading_at
    return {
        "id": order.pk,
        "number": order.number,
        "client": order.client.name,
        "route": order_route(order),
        "carriers": carriers.get(order.pk, []),
        "rate": money(order.client_rate),
        "currency": order.currency.code,
        "loading_at": loading.astimezone(zone).isoformat() if loading else None,
        "has_carrier": order.has_carrier,
    }


def build_board(params, zone, limit: int) -> list[dict]:
    matching = apply_filters(Order.objects.all(), params, zone)
    counts = dict(matching.order_by().values_list("status_id").annotate(n=Count("pk")))
    statuses = HandbookValue.objects.filter(handbook__code="order_status").filter(
        Q(is_active=True) | Q(pk__in=[pk for pk, n in counts.items() if n])
    )
    ranked = (
        matching.annotate(
            rank=Window(
                RowNumber(),
                partition_by=F("status_id"),
                order_by=[F("created_at").desc(), F("id").desc()],
            ),
            loading_at=loading_at_subquery(),
            has_carrier=Exists(carried_with_carrier()),
        )
        .filter(rank__lte=limit)
        .select_related("client", "currency")
        .order_by("-created_at", "-id")
    )
    orders = list(routed(ranked))
    carriers = carrier_names([o.pk for o in orders])
    by_status = defaultdict(list)
    for order in orders:
        by_status[order.status_id].append(card(order, carriers, zone))
    board = []
    for status in statuses:
        cards = by_status.get(status.pk, [])
        count = counts.get(status.pk, 0)
        board.append(
            {
                "status": {"id": status.pk, "name": status.name},
                "count": count,
                "orders": cards,
                "has_more": count > len(cards),
            }
        )
    return board
