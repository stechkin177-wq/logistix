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

from ..consignments.models import Consignment, ConsignmentPoint
from ..consignments.services import initial_status
from ..models import Carrier, Order
from ..orders.services import _default_currency
from . import legs as leg_rules
from . import resources
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


def _specs_from_input(legs: list[dict], consignments: dict[int, Consignment]) -> dict:
    """Явные участки из запроса -> {id груза: [LegSpec]}. Остановки ищутся среди остановок
    компании (чужие/несуществующие id - ValidationError). Участок без остановок - весь маршрут."""
    stop_ids = {sid for item in legs for sid in (item.get("from_stop"), item.get("to_stop")) if sid}
    stops = {p.pk: p for p in ConsignmentPoint.objects.filter(pk__in=stop_ids)}
    result: dict[int, list] = {}
    for item in legs:
        consignment = consignments[item["consignment"]]
        from_id, to_id = item.get("from_stop"), item.get("to_stop")
        if (from_id is None) != (to_id is None):
            raise ValidationError({"legs": "Укажите обе остановки участка или ни одной"})
        if from_id is None:
            whole = leg_rules.whole_spec(consignment)
            first, last = whole.from_stop, whole.to_stop
        else:
            first, last = stops.get(from_id), stops.get(to_id)
            if first is None or last is None:
                raise ValidationError({"legs": "Остановка участка не найдена"})
        shares = item.get("shares") or {}
        result.setdefault(consignment.pk, []).append(
            leg_rules.LegSpec(
                consignment,
                first,
                last,
                shares.get("weight_kg"),
                shares.get("volume_m3"),
                shares.get("pallets"),
            )
        )
    return result


def _leg_ordinals(specs: list) -> list:
    """Участки груза в рейсе по порядку маршрута (для leg_seq)."""
    return sorted(
        specs,
        key=lambda s: (s.from_stop.seq if s.from_stop else 0, s.to_stop.seq if s.to_stop else 0),
    )


def _new_links(trip: Trip, specs: list, status: str) -> list[TripConsignment]:
    return [
        TripConsignment(
            company_id=trip.company_id,
            trip=trip,
            consignment=spec.consignment,
            from_stop=spec.from_stop,
            to_stop=spec.to_stop,
            leg_seq=n,
            status=status,
            weight_kg=spec.weight_kg,
            volume_m3=spec.volume_m3,
            pallets=spec.pallets,
        )
        for n, spec in enumerate(_leg_ordinals(specs), start=1)
    ]


def _repr(value):
    return None if value is None else str(value)


def _leg_repr(consignment_id, from_id, to_id, weight, volume, pallets) -> list:
    """Участок в аудите: [груз, от остановки, до остановки, вес, объём, паллеты]."""
    return [consignment_id, from_id, to_id, _repr(weight), _repr(volume), pallets]


def _spec_repr(spec) -> list:
    return _leg_repr(
        spec.consignment.pk,
        spec.from_stop.pk if spec.from_stop else None,
        spec.to_stop.pk if spec.to_stop else None,
        spec.weight_kg,
        spec.volume_m3,
        spec.pallets,
    )


def _link_repr(link: TripConsignment) -> list:
    return _leg_repr(
        link.consignment_id,
        link.from_stop_id,
        link.to_stop_id,
        link.weight_kg,
        link.volume_m3,
        link.pallets,
    )


def _plan_specs(
    consignments: list[Consignment], consignment_ids, legs: list[dict]
) -> tuple[dict, set]:
    """Участки по грузам: явные из ``legs``, для остальных грузов из ``consignment_ids`` -
    весь маршрут. Возвращает ({id груза: [LegSpec]}, {id грузов с явными участками})."""
    by_id = {c.pk: c for c in consignments}
    explicit = _specs_from_input(legs, by_id) if legs else {}
    specs = {}
    for c in consignments:
        specs[c.pk] = explicit.get(c.pk) or [leg_rules.whole_spec(c)]
    return specs, set(explicit)


def refresh_tracking(consignment_ids) -> None:
    """Пересчёт местонахождения грузов после изменения их участков (рейс создан/изменён/отменён)."""
    from ..tracking.services import recompute_location

    for consignment in Consignment.objects.filter(pk__in=sorted(set(consignment_ids))).order_by(
        "pk"
    ):
        recompute_location(consignment)


@transaction.atomic
def create_trip(
    consignment_ids: list[int],
    carrier_id: int | None,
    data: dict,
    user,
    *,
    legs: list[dict] | None = None,
    ip: str | None = None,
) -> Trip:
    """Создаёт рейс на грузы (не менее одного) в одной транзакции.

    consignment_ids - грузы на весь маршрут (участок от первой погрузки до последней выгрузки);
    legs (необязательно) - явные участки [{consignment, from_stop, to_stop, shares}]: грузы
    участков добавляются к consignment_ids, для грузов с явными участками «весь маршрут» не
    создаётся. Участки проверяются правилами legs (остановки груза, доли, пересечения с другими
    рейсами).

    Все грузы должны быть грузами текущей компании, не удалены, заказ не удалён; иначе
    ValidationError с id. Грузы одного заказа: номер {order}-{n} и is_consolidated=False;
    грузы нескольких заказов: сборный номер (C{index}) и is_consolidated=True. Статус -
    начальный trip_status, валюта по умолчанию KZT. data - проверенные поля
    vehicle_plate, driver_name, carrier_price (или устаревший алиас price), currency (остальные
    игнорируются). Пишет аудит create.
    """
    legs = legs or []
    all_ids = _unique([*(consignment_ids or []), *(item["consignment"] for item in legs)])
    consignments = _load_consignments(all_ids, lock_single_order=True)
    specs, explicit = _plan_specs(consignments, consignment_ids, legs)
    for c in consignments:
        leg_rules.check_consignment_legs(c, specs[c.pk])
    carrier = _carrier(carrier_id)
    fields = {
        k: data[k]
        for k in ("vehicle_plate", "driver_name", "currency", "vehicle", "trailer", "driver")
        if k in data
    }
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
    status = leg_rules.leg_status_for(trip.status.code)
    TripConsignment.objects.bulk_create(
        [link for c in consignments for link in _new_links(trip, specs[c.pk], status)]
    )
    changes = audit.diff({}, audit.snapshot(trip), audit.masked_fields(trip))
    changes["consignments"] = [[], sorted(c.pk for c in consignments)]
    if explicit:
        changes["legs"] = [
            [],
            sorted((_spec_repr(s) for c in consignments for s in specs[c.pk]), key=repr),
        ]
    audit.log("create", trip, user, changes, ip=ip)
    refresh_tracking(c.pk for c in consignments)
    from apps.finance import hooks  # новый рейс меняет условия признания (только engine=new)

    hooks.after_trip_changed(trip, user)
    return trip


def _locked_trip(trip: Trip) -> Trip:
    locked = Trip.objects.select_for_update().filter(pk=trip.pk).first()
    if locked is None:  # удалён параллельно
        raise NotFound()
    return locked


@transaction.atomic
def reassign(
    trip: Trip,
    consignment_ids: list[int],
    user,
    *,
    legs: list[dict] | None = None,
    ip: str | None = None,
) -> Trip:
    """Заменяет набор грузов рейса (не менее одного; требования к грузам как при создании).

    consignment_ids - грузы (для новых - участок на весь маршрут, у прежних участки сохраняются);
    legs (необязательно) - явные участки: для грузов с явными участками участки рейса заменяются
    на указанные (сужение/расширение/передача), грузы участков добавляются к набору.
    is_consolidated пересчитывается (грузов больше чем одного заказа). Номер рейса НИКОГДА
    не меняется: он уже мог попасть в документы, даже если рейс стал сборным или наоборот.
    Пишет аудит update {"consignments": [было, стало]} (списки id) и {"legs": [...]}, если
    набор грузов/участков изменился.
    """
    locked = _locked_trip(trip)
    legs = legs or []
    all_ids = _unique([*(consignment_ids or []), *(item["consignment"] for item in legs)])
    consignments = _load_consignments(all_ids)
    new_ids = [c.pk for c in consignments]
    old_order_ids = set(locked.consignments.values_list("order_id", flat=True))
    current = list(
        TripConsignment.objects.filter(trip=locked).select_related("from_stop", "to_stop")
    )
    old_ids = sorted({link.consignment_id for link in current})
    by_consignment: dict[int, list] = {}
    for link in current:
        by_consignment.setdefault(link.consignment_id, []).append(link)
    explicit_specs = _specs_from_input(legs, {c.pk: c for c in consignments}) if legs else {}
    status = leg_rules.leg_status_for(locked.status.code)
    active = status != TripConsignment.CANCELLED
    legs_before, legs_after = [], []
    changed_legs = False
    # 1) грузы, которых больше нет в рейсе
    removed = [link.pk for link in current if link.consignment_id not in set(new_ids)]
    if removed:
        legs_before += [_link_repr(link) for link in current if link.pk in set(removed)]
        TripConsignment.objects.filter(pk__in=removed).delete()
        changed_legs = True
    # 2) участки оставшихся и новых грузов
    for c in consignments:
        kept = by_consignment.get(c.pk, [])
        if c.pk in explicit_specs:
            desired = explicit_specs[c.pk]
        elif kept:
            legs_before += [_link_repr(link) for link in kept]
            legs_after += [_link_repr(link) for link in kept]
            continue  # участки груза не трогаем
        else:
            desired = [leg_rules.whole_spec(c)]
        if active:
            leg_rules.check_consignment_legs(c, desired, exclude_trip_id=locked.pk)
        want = {spec.key: spec for spec in desired}
        legs_before += [_link_repr(link) for link in kept]
        legs_after += [_spec_repr(spec) for spec in desired]
        gone = [
            link.pk
            for link in kept
            if (link.consignment_id, link.from_stop_id, link.to_stop_id) not in want
        ]
        if gone:
            TripConsignment.objects.filter(pk__in=gone).delete()
            changed_legs = True
        have = {
            (link.consignment_id, link.from_stop_id, link.to_stop_id): link
            for link in kept
            if link.pk not in gone
        }
        ordered = _leg_ordinals(desired)
        for n, spec in enumerate(ordered, start=1):
            link = have.get(spec.key)
            if link is None:
                new_link = _new_links(locked, [spec], status)[0]
                new_link.leg_seq = n
                new_link.save()
                changed_legs = True
                continue
            fields = {}
            for field in (*leg_rules.DIMENSIONS, "leg_seq"):
                value = n if field == "leg_seq" else getattr(spec, field)
                if getattr(link, field) != value:
                    fields[field] = value
            if fields:
                TripConsignment.objects.filter(pk=link.pk).update(**fields)
                changed_legs = True
    changes = {}
    if old_ids != sorted(new_ids):
        changes["consignments"] = [old_ids, sorted(new_ids)]
    if legs and changed_legs:
        changes["legs"] = [sorted(legs_before, key=repr), sorted(legs_after, key=repr)]
    if changes:
        audit.log("update", locked, user, changes, ip=ip)
    consolidated = len({c.order_id for c in consignments}) > 1
    if consolidated != locked.is_consolidated:
        locked.is_consolidated = consolidated
        locked.save(update_fields=["is_consolidated", "updated_at"])
    refresh_tracking([*new_ids, *old_ids])
    from apps.finance import hooks  # пересчёт признания по прежним и новым заказам

    hooks.after_trip_changed(locked, user, extra_order_ids=old_order_ids)
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
    perms=(),
    adjust_reason: str | None = None,
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
    if status.code in resources.BUSY_CODES:  # ресурсы рейса не заняты другим рейсом в работе
        resources.assert_free(locked)
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
    leg_rules.sync_leg_statuses(locked)  # статусы участков следуют за статусом рейса
    refresh_tracking(
        TripConsignment.objects.filter(trip=locked).values_list("consignment_id", flat=True)
    )
    from apps.finance import hooks  # признание дохода (только engine=new; ошибка откатывает)

    hooks.after_trip_changed(locked, user, perms=perms, reason=adjust_reason or reason)
    return locked
