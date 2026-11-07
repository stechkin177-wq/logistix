"""Сервисы рейсов.

Порядок блокировок строк (select_for_update) единый для всех сервисов, иначе параллельные
вызовы с пересекающимися грузами могут взаимно заблокироваться (deadlock):
1) строка рейса (reassign, change_trip_status);
2) строка заказа (только путь «грузы одного заказа» в create_trip - под ней считается n);
3) строки грузов по возрастанию pk.
Сборный путь заказы не блокирует (счётчик сборных рейсов даёт уникальность).
"""

from decimal import Decimal

from django.db import IntegrityError, OperationalError, transaction
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.exceptions import (
    APIException,
    ErrorDetail,
    NotFound,
    PermissionDenied,
    ValidationError,
)

from apps.core.audit import services as audit
from apps.core.handbooks.models import HandbookValue
from apps.core.numbering.services import next_number, peek_number

from ..consignments.models import Consignment
from ..consignments.services import initial_status
from ..models import Carrier, Order
from ..orders.services import _default_currency
from .models import Trip, TripConsignment

NUMBER_CONSTRAINT = "trip_company_number_uniq"
COMPLETED_CODE = "COMPLETED"  # системный код статуса рейса «Завершён»
REVERT_PERMISSION = "trips.revert_completed"


class TripNumberConflict(APIException):
    status_code = http_status.HTTP_409_CONFLICT
    default_detail = (
        "Номер рейса уже занят: проверьте счётчик нумерации сборных рейсов в настройках компании"
    )
    default_code = "number_conflict"


def _unique(ids) -> list[int]:
    """Без повторов, в порядке запроса."""
    return list(dict.fromkeys(ids))


DEADLOCK_PGCODES = ("40P01", "40001")  # deadlock_detected, serialization_failure


class ConcurrentChange(APIException):
    status_code = http_status.HTTP_409_CONFLICT
    default_detail = "Конфликт одновременных изменений, повторите запрос"
    default_code = "concurrent_change"


def is_concurrency_failure(exc: BaseException) -> bool:
    """Только deadlock и сбой сериализации PostgreSQL (по pgcode), не прочие ошибки БД."""
    if not isinstance(exc, OperationalError):
        return False
    code = getattr(exc.__cause__, "sqlstate", None) or getattr(exc.__cause__, "pgcode", None)
    return code in DEADLOCK_PGCODES


def locked_consignments_qs(ids):
    """Запрос блокировки грузов: всегда по возрастанию pk (единый порядок блокировок)."""
    return (
        Consignment.objects.select_for_update(of=("self",))
        .select_related("order")
        .filter(pk__in=ids, order__deleted_at__isnull=True)
        .order_by("pk")
    )


def _load_consignments(consignment_ids, *, lock_single_order=False) -> list[Consignment]:
    """Грузы текущей компании (не удалённые, заказ не удалён), заблокированные до конца
    транзакции, чтобы их нельзя было удалить параллельно. Иначе 400 с перечнем id."""
    ids = _unique(consignment_ids)
    if not ids:
        raise ValidationError({"consignments": "В рейсе должен быть хотя бы один груз"})
    if lock_single_order:  # шаг 2 порядка блокировок: заказ раньше грузов
        order_ids = set(
            Consignment.objects.filter(pk__in=ids, order__deleted_at__isnull=True).values_list(
                "order_id", flat=True
            )
        )
        if len(order_ids) == 1:
            Order.objects.select_for_update().filter(pk=next(iter(order_ids))).first()
    found = {c.pk: c for c in locked_consignments_qs(ids)}
    missing = [pk for pk in ids if pk not in found]
    if missing:
        raise ValidationError(
            {"consignments": f"Грузы не найдены или удалены: {', '.join(map(str, missing))}"}
        )
    return [found[pk] for pk in ids]


def _carrier(carrier_id) -> Carrier | None:
    if carrier_id is None:
        return None
    carrier = Carrier.objects.filter(pk=carrier_id, status=Carrier.ACTIVE).first()
    if carrier is None:
        raise ValidationError({"carrier": "Нужен активный перевозчик этой компании"})
    return carrier


def _check_price(price) -> None:
    if price is not None and price < 0:
        raise ValidationError({"carrier_price": "Цена не может быть отрицательной"})


def _carrier_price(data: dict):
    """Стоимость перевозчика из data: ключи carrier_price и price (устаревший алиас).

    Оба ключа допустимы; если заданы оба и значения различаются (Decimal) - ValidationError
    на поле price. None, если ни одного нет.
    """
    has_main, has_alias = "carrier_price" in data, "price" in data
    if (
        has_main
        and has_alias
        and Decimal(str(data["carrier_price"])) != Decimal(str(data["price"]))
    ):
        raise ValidationError({"price": "Поля price и carrier_price различаются"})
    if has_main:
        return data["carrier_price"]
    return data["price"] if has_alias else None


def _single_order_number(order: Order) -> str:
    """Номер {order}-{n}: n = 1 + число рейсов (в т.ч. мягко удалённых), везивших груз заказа.

    Строка заказа заблокирована вызывающим (_load_consignments), поэтому параллельные рейсы
    заказа получают разные n. Если груз рейса переназначили в другой заказ, счёт уменьшился,
    а номер остался занятым: n увеличивается, пока номер не окажется свободным.
    """
    n = (
        TripConsignment.all_objects.filter(
            company_id=order.company_id, consignment__order_id=order.pk
        )
        .values("trip_id")
        .distinct()
        .count()
        + 1
    )
    while True:
        # проба без расхода счётчика ({index} в шаблоне); номер выдаём, когда он свободен
        probe = peek_number("trip", order=order.number, n=n)
        if not Trip.all_objects.filter(company_id=order.company_id, number=probe).exists():
            return next_number("trip", order=order.number, n=n)
        n += 1


@transaction.atomic
def create_trip(
    consignment_ids: list[int],
    carrier_id: int | None,
    data: dict,
    user,
    *,
    ip: str | None = None,
) -> Trip:
    """Создаёт рейс на грузы (не менее одного) в одной транзакции.

    Все грузы должны быть грузами текущей компании, не удалены, заказ не удалён; иначе
    ValidationError с id. Грузы одного заказа: номер {order}-{n} и is_consolidated=False;
    грузы нескольких заказов: сборный номер (C{index}) и is_consolidated=True. Статус -
    начальный trip_status, валюта по умолчанию KZT. data - проверенные поля
    vehicle_plate, driver_name, carrier_price (или устаревший алиас price), currency (остальные
    игнорируются). Пишет аудит create.
    """
    consignments = _load_consignments(consignment_ids, lock_single_order=True)
    carrier = _carrier(carrier_id)
    fields = {k: data[k] for k in ("vehicle_plate", "driver_name", "currency") if k in data}
    carrier_price = _carrier_price(data)
    if carrier_price is not None:
        fields["carrier_price"] = carrier_price
    _check_price(fields.get("carrier_price"))
    if fields.get("currency") is None:
        fields["currency"] = _default_currency()
    orders = {c.order_id: c.order for c in consignments}
    consolidated = len(orders) > 1
    if consolidated:
        number = next_number("consolidated_trip")
    else:
        number = _single_order_number(next(iter(orders.values())))
    trip = Trip(
        number=number,
        carrier=carrier,
        status=initial_status("trip_status"),
        is_consolidated=consolidated,
        created_by=user,
        **fields,
    )
    try:
        with transaction.atomic():
            trip.save()
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.__cause__, "diag", None), "constraint_name", "") or ""
        if constraint != NUMBER_CONSTRAINT:
            raise
        raise TripNumberConflict() from None
    TripConsignment.objects.bulk_create(
        [
            TripConsignment(company_id=trip.company_id, trip=trip, consignment=c)
            for c in consignments
        ]
    )
    changes = audit.diff({}, audit.snapshot(trip), audit.masked_fields(trip))
    changes["consignments"] = [[], sorted(c.pk for c in consignments)]
    audit.log("create", trip, user, changes, ip=ip)
    return trip


def _locked_trip(trip: Trip) -> Trip:
    locked = Trip.objects.select_for_update().filter(pk=trip.pk).first()
    if locked is None:  # удалён параллельно
        raise NotFound()
    return locked


@transaction.atomic
def reassign(trip: Trip, consignment_ids: list[int], user, *, ip: str | None = None) -> Trip:
    """Заменяет набор грузов рейса (не менее одного; требования к грузам как при создании).

    is_consolidated пересчитывается (грузов больше чем одного заказа). Номер рейса НИКОГДА
    не меняется: он уже мог попасть в документы, даже если рейс стал сборным или наоборот.
    Пишет аудит update {"consignments": [было, стало]} (списки id), если набор изменился.
    """
    locked = _locked_trip(trip)
    consignments = _load_consignments(consignment_ids)
    new_ids = [c.pk for c in consignments]
    old_ids = sorted(
        TripConsignment.objects.filter(trip=locked).values_list("consignment_id", flat=True)
    )
    if old_ids != sorted(new_ids):
        TripConsignment.objects.filter(trip=locked).exclude(consignment_id__in=new_ids).delete()
        kept = set(old_ids)
        TripConsignment.objects.bulk_create(
            [
                TripConsignment(company_id=locked.company_id, trip=locked, consignment=c)
                for c in consignments
                if c.pk not in kept
            ]
        )
        audit.log("update", locked, user, {"consignments": [old_ids, sorted(new_ids)]}, ip=ip)
    consolidated = len({c.order_id for c in consignments}) > 1
    if consolidated != locked.is_consolidated:
        locked.is_consolidated = consolidated
        locked.save(update_fields=["is_consolidated", "updated_at"])
    return locked


@transaction.atomic
def change_trip_status(
    trip: Trip,
    status: HandbookValue,
    user,
    *,
    ip: str | None = None,
    reason: str | None = None,
    can_revert: bool = False,
) -> Trip:
    """Переводит рейс в активный статус trip_status компании (любой -> любой, кроме того же).

    Переход В статус с системным кодом COMPLETED ставит completed_at = now() (если ещё пусто).
    Выход ИЗ COMPLETED требует права trips.revert_completed (can_revert; иначе 403) и
    обязательной причины reason (иначе 400); completed_at обнуляется, а в аудит пишутся статус
    (было, стало), completed_at (было, стало) и reason. Остальные переходы - без новых требований.
    """
    locked = _locked_trip(trip)
    if (
        status.handbook.code != "trip_status"
        or status.company_id != locked.company_id
        or not status.is_active
    ):
        raise ValidationError({"status": "Нужен активный статус рейса этой компании"})
    if status.pk == locked.status_id:
        raise ValidationError({"status": "Рейс уже в этом статусе"})
    leaving = locked.status.code == COMPLETED_CODE
    reason = (reason or "").strip()
    if leaving:
        if not can_revert:
            raise PermissionDenied("Недостаточно прав для выхода рейса из статуса «Завершён»")
        if not reason:
            raise ValidationError(
                {"reason": ErrorDetail("Укажите причину выхода из статуса «Завершён»", "required")}
            )
    before = audit.snapshot(locked)
    locked.status = status
    update_fields = ["status", "updated_at"]
    if leaving:
        locked.completed_at = None
        update_fields.append("completed_at")
    elif status.code == COMPLETED_CODE and locked.completed_at is None:
        locked.completed_at = timezone.now()  # один раз; повторное завершение не перезаписывает
        update_fields.append("completed_at")
    locked.save(update_fields=update_fields)
    changes = audit.diff(before, audit.snapshot(locked))
    if leaving:
        changes["completed_at"] = [before["completed_at"], None]
        changes["reason"] = reason
    audit.log("update", locked, user, changes, ip=ip)
    return locked
