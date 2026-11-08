"""Сервисы передач груза и журнала событий (этап 1.5-D).

Порядок блокировок: заказ -> груз (как в финансах: Order -> ...), затем строки передач/событий.
Финансовый хук (пересчёт признания дохода, только engine=new) вызывается внутри транзакции
после изменения состояния груза.
"""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.core.audit import services as audit

from ..consignments.models import Consignment, ConsignmentPoint
from ..models import Carrier, Order, TripConsignment
from .models import DRIVER_APP, MANUAL, CargoTransfer, ConsignmentEvent

CANCELLED_CODE = "CANCELLED"
ARRIVE_TYPES = {"arrived", "loaded", "unloaded", "transferred", "stored"}
SOURCES = (MANUAL, DRIVER_APP)
DIMENSIONS = ("weight_kg", "volume_m3", "pallets")


def lock_consignment(consignment: Consignment) -> Consignment:
    """Заказ, затем груз (select_for_update): общий порядок с финансами и рейсами."""
    Order.all_objects.select_for_update().filter(pk=consignment.order_id).first()
    locked = (
        Consignment.objects.select_for_update(of=("self",))
        .select_related("order")
        .filter(pk=consignment.pk, order__deleted_at__isnull=True)
        .first()
    )
    if locked is None:
        raise NotFound()
    return locked


def stops_of(consignment: Consignment) -> list[ConsignmentPoint]:
    return list(ConsignmentPoint.objects.filter(consignment=consignment).order_by("seq", "id"))


def active_legs(consignment: Consignment, *, trip=None) -> list[TripConsignment]:
    """Неотменённые участки не удалённых рейсов (рейс с кодом CANCELLED не считается)."""
    qs = (
        TripConsignment.objects.filter(consignment=consignment, trip__deleted_at__isnull=True)
        .exclude(status=TripConsignment.CANCELLED)
        .exclude(trip__status__code=CANCELLED_CODE)
        .select_related("trip", "trip__carrier", "from_stop", "to_stop")
    )
    if trip is not None:
        qs = qs.filter(trip=trip)
    return list(qs.order_by("leg_seq", "id"))


def leg_bounds(leg: TripConsignment, stops: list) -> tuple[int, int]:
    """(seq начала, seq конца) участка; пустая пара - весь маршрут."""
    if leg.from_stop_id is None or leg.to_stop_id is None:
        return (stops[0].seq, stops[-1].seq) if stops else (1, 1)
    return leg.from_stop.seq, leg.to_stop.seq


# --- местонахождение -----------------------------------------------------------------------


def confirmed_transfers(consignment: Consignment) -> list[CargoTransfer]:
    """Подтверждённые передачи без сторно, от новых к старым."""
    return list(
        CargoTransfer.objects.filter(
            consignment=consignment, status=CargoTransfer.CONFIRMED, reversals__isnull=True
        )
        .select_related("to_stop")
        .order_by("-transferred_at", "-id")
    )


def derive_location(consignment: Consignment) -> tuple[str, int | None]:
    """(location_status, current_stop_id) по остановкам, участкам и передачам груза.

    delivered - последняя остановка выполнена или завершён участок, заканчивающийся на ней;
    in_storage - последняя подтверждённая передача to_storage на остановку, от которой нет
    назначенного исходящего участка; at_stop - есть остановка «прибыли»; in_transit - есть
    выполненная остановка или участок в пути/завершён; иначе planned.
    """
    stops = stops_of(consignment)
    legs = active_legs(consignment)
    if not stops:
        if any(leg.status == TripConsignment.DONE for leg in legs):
            return Consignment.DELIVERED, None
        in_progress = any(leg.status == TripConsignment.IN_PROGRESS for leg in legs)
        return (Consignment.IN_TRANSIT if in_progress else Consignment.PLANNED), None
    last = stops[-1]
    if last.status == ConsignmentPoint.DONE:
        return Consignment.DELIVERED, None
    for leg in legs:
        if leg.status == TripConsignment.DONE and leg_bounds(leg, stops)[1] == last.seq:
            return Consignment.DELIVERED, None
    transfers = confirmed_transfers(consignment)
    if transfers and transfers[0].transfer_kind == CargoTransfer.TO_STORAGE:
        stop = transfers[0].to_stop
        outgoing = any(
            leg_bounds(leg, stops)[0] <= stop.seq < leg_bounds(leg, stops)[1] for leg in legs
        )
        if not outgoing:
            return Consignment.IN_STORAGE, stop.pk
    arrived = [s for s in stops if s.status == ConsignmentPoint.ARRIVED]
    if arrived:
        return Consignment.AT_STOP, arrived[-1].pk
    if any(s.status == ConsignmentPoint.DONE for s in stops) or any(
        leg.status in (TripConsignment.IN_PROGRESS, TripConsignment.DONE) for leg in legs
    ):
        return Consignment.IN_TRANSIT, None
    return Consignment.PLANNED, None


def recompute_location(consignment: Consignment) -> tuple[str, int | None]:
    """Пересчитывает производные поля груза (единственное место их записи)."""
    status, stop_id = derive_location(consignment)
    if (consignment.location_status, consignment.current_stop_id) != (status, stop_id):
        Consignment.objects.filter(pk=consignment.pk).update(
            location_status=status, current_stop_id=stop_id
        )
        consignment.location_status, consignment.current_stop_id = status, stop_id
    return status, stop_id


def _finance_hook(consignment: Consignment, user) -> None:
    from apps.finance import hooks  # пересчёт признания дохода (только engine=new)

    hooks.after_consignment_changed(consignment, user)


# --- события -------------------------------------------------------------------------------


def _apply_to_stop(stop: ConsignmentPoint, event_type: str, at) -> None:
    fields = []
    if event_type in ARRIVE_TYPES:
        if stop.status in (ConsignmentPoint.PLANNED, ConsignmentPoint.SKIPPED):
            stop.status = ConsignmentPoint.ARRIVED
            fields.append("status")
        if stop.arrived_at is None:
            stop.arrived_at = at
            fields.append("arrived_at")
    elif event_type in ("departed", "delivered"):
        if stop.status != ConsignmentPoint.DONE:
            stop.status = ConsignmentPoint.DONE
            fields.append("status")
        if stop.done_at is None:
            stop.done_at = at
            fields.append("done_at")
        if stop.arrived_at is None or stop.arrived_at > stop.done_at:
            stop.arrived_at = min(at, stop.done_at)
            fields.append("arrived_at")
    elif event_type == "skipped":
        if stop.status == ConsignmentPoint.DONE:
            raise ValidationError({"event_type": "Выполненную остановку нельзя пропустить"})
        stop.status = ConsignmentPoint.SKIPPED
        fields.append("status")
    if fields:
        stop.save(update_fields=sorted(set(fields)))


def _record(consignment, event_type, *, stop, leg, trip, occurred_at, user, source, note, ip):
    """Запись события без пересчёта и хука; возвращает (событие, создано)."""
    existing = ConsignmentEvent.objects.filter(
        consignment=consignment, stop=stop, event_type=event_type, occurred_at=occurred_at
    ).first()
    if existing is not None:
        return existing, False
    event = ConsignmentEvent(
        consignment=consignment,
        stop=stop,
        leg=leg,
        trip=trip,
        event_type=event_type,
        occurred_at=occurred_at,
        recorded_by=user if getattr(user, "pk", None) else None,
        source=source,
        note=note or "",
    )
    event.save()
    _apply_to_stop(stop, event_type, occurred_at)
    audit.log(
        "create",
        event,
        user,
        {
            "event_type": [None, event_type],
            "stop": [None, stop.pk],
            "occurred_at": [None, occurred_at.isoformat()],
            "source": [None, source],
        },
        ip=ip,
    )
    return event, True


def _resolve_event_target(consignment, event_type, stop, leg, trip):
    if leg is not None:
        if leg.consignment_id != consignment.pk:
            raise ValidationError({"leg": "Участок не принадлежит этому грузу"})
        if trip is not None and trip.pk != leg.trip_id:
            raise ValidationError({"trip": "Рейс не совпадает с рейсом участка"})
        trip = leg.trip
        if stop is None:
            stop = leg.from_stop if event_type in ("loaded", "departed") else leg.to_stop
    if stop is None:
        raise ValidationError({"stop": "Укажите остановку события"})
    if stop.consignment_id != consignment.pk:
        raise ValidationError({"stop": "Остановка не принадлежит этому грузу"})
    if event_type == "delivered" and stop.kind != ConsignmentPoint.UNLOAD:
        raise ValidationError({"stop": "Доставка фиксируется на остановке выгрузки"})
    return stop, trip


@transaction.atomic
def record_event(
    consignment: Consignment,
    event_type: str,
    *,
    stop=None,
    leg=None,
    trip=None,
    occurred_at=None,
    user=None,
    source: str = MANUAL,
    note: str = "",
    ip: str | None = None,
):
    """Фиксирует событие груза; возвращает (событие, создано).

    Обновляет статус остановки (arrived_at/done_at/status), пересчитывает местонахождение груза
    и вызывает финансовый хук. Повтор того же события (груз, остановка, тип, время) ничего не
    меняет и возвращает прежнее событие.
    """
    if event_type not in ConsignmentEvent.TYPE_CODES:
        raise ValidationError({"event_type": "Неизвестный вид события"})
    if source not in SOURCES:
        raise ValidationError({"source": "Неизвестный источник"})
    locked = lock_consignment(consignment)
    stop, trip = _resolve_event_target(locked, event_type, stop, leg, trip)
    stop = ConsignmentPoint.objects.select_for_update().get(pk=stop.pk)
    event, created = _record(
        locked,
        event_type,
        stop=stop,
        leg=leg,
        trip=trip,
        occurred_at=occurred_at or timezone.now(),
        user=user,
        source=source,
        note=note,
        ip=ip,
    )
    if created:
        recompute_location(locked)
        _finance_hook(locked, user)
    return event, created


# --- передачи ------------------------------------------------------------------------------


def _carrier(value, field):
    if value is None:
        return None
    pk = getattr(value, "pk", value)
    carrier = Carrier.objects.filter(pk=pk, status=Carrier.ACTIVE).first()
    if carrier is None:
        raise ValidationError({field: "Нужен активный перевозчик этой компании"})
    return carrier


def _validate(consignment: Consignment, f: dict) -> dict:
    """Проверка полей передачи; возвращает значения с выведенными перевозчиками."""
    kind = f.get("transfer_kind")
    if kind not in dict(CargoTransfer.KINDS):
        raise ValidationError({"transfer_kind": "Неизвестный вид передачи"})
    to_stop, from_stop = f.get("to_stop"), f.get("from_stop")
    if to_stop is None:
        raise ValidationError({"to_stop": "Укажите остановку передачи"})
    if to_stop.consignment_id != consignment.pk:
        raise ValidationError({"to_stop": "Остановка не принадлежит этому грузу"})
    if to_stop.kind != ConsignmentPoint.TRANSFER:
        raise ValidationError({"to_stop": "Передача оформляется на остановке вида «передача»"})
    if from_stop is not None:
        if from_stop.consignment_id != consignment.pk:
            raise ValidationError({"from_stop": "Остановка не принадлежит этому грузу"})
        if from_stop.seq > to_stop.seq:
            raise ValidationError({"from_stop": "Остановка отправления позже остановки передачи"})
    from_trip, to_trip = f.get("from_trip"), f.get("to_trip")
    if kind == CargoTransfer.TO_STORAGE and to_trip is not None:
        raise ValidationError({"to_trip": "Передача на склад оформляется без следующего рейса"})
    if kind == CargoTransfer.FROM_STORAGE:
        if from_trip is not None:
            raise ValidationError(
                {"from_trip": "Передача со склада оформляется без прежнего рейса"}
            )
        if to_trip is None:
            raise ValidationError({"to_trip": "Укажите рейс, на который груз берут со склада"})
    if kind == CargoTransfer.BETWEEN_VEHICLES and (from_trip is None or to_trip is None):
        raise ValidationError({"to_trip": "Перегрузка между ТС требует оба рейса"})
    stops = stops_of(consignment)
    if from_trip is not None:
        legs = active_legs(consignment, trip=from_trip)
        if not any(leg_bounds(leg, stops)[1] == to_stop.seq for leg in legs):
            raise ValidationError(
                {"from_trip": "У груза нет участка этого рейса, заканчивающегося на этой остановке"}
            )
    if to_trip is not None:
        legs = active_legs(consignment, trip=to_trip)
        if not any(leg_bounds(leg, stops)[0] == to_stop.seq for leg in legs):
            raise ValidationError(
                {"to_trip": "У груза нет участка этого рейса, начинающегося на этой остановке"}
            )
    from_carrier, to_carrier = f.get("from_carrier"), f.get("to_carrier")
    for trip, carrier, name in (
        (from_trip, from_carrier, "from_carrier"),
        (to_trip, to_carrier, "to_carrier"),
    ):
        if (
            trip is not None
            and carrier is not None
            and trip.carrier_id != getattr(carrier, "pk", carrier)
        ):
            raise ValidationError({name: "Перевозчик выводится из рейса и не совпадает с ним"})
    from_carrier = (
        from_trip.carrier if from_trip is not None else _carrier(from_carrier, "from_carrier")
    )
    to_carrier = to_trip.carrier if to_trip is not None else _carrier(to_carrier, "to_carrier")
    if kind == CargoTransfer.TO_CARRIER and to_carrier is None:
        raise ValidationError({"to_carrier": "Укажите принимающего перевозчика"})
    if f.get("transferred_at") is None:
        raise ValidationError({"transferred_at": "Укажите время передачи"})
    for dim in DIMENSIONS:
        value = f.get(dim)
        if value is None:
            continue
        if value < 0:
            raise ValidationError({dim: "Количество не может быть отрицательным"})
        if value > getattr(consignment, dim):
            raise ValidationError({dim: "Количество больше количества груза"})
    changed = bool(from_carrier and to_carrier and from_carrier.pk != to_carrier.pk)
    return {**f, "from_carrier": from_carrier, "to_carrier": to_carrier, "carrier_changed": changed}


def _state(t: CargoTransfer) -> dict:
    return {
        "status": t.status,
        "transfer_kind": t.transfer_kind,
        "to_stop": t.to_stop_id,
        "from_trip": t.from_trip_id,
        "to_trip": t.to_trip_id,
        "carrier_changed": t.carrier_changed,
    }


@transaction.atomic
def initiate_transfer(
    consignment: Consignment, data: dict, user, *, source: str = MANUAL, ip: str | None = None
) -> CargoTransfer:
    """Инициирует передачу (status=initiated). Права проверяет API-слой."""
    if source not in SOURCES:
        raise ValidationError({"source": "Неизвестный источник"})
    locked = lock_consignment(consignment)
    f = _validate(locked, data)
    transfer = CargoTransfer(
        consignment=locked,
        from_trip=f.get("from_trip"),
        to_trip=f.get("to_trip"),
        from_stop=f.get("from_stop"),
        to_stop=f["to_stop"],
        transfer_kind=f["transfer_kind"],
        from_carrier=f["from_carrier"],
        to_carrier=f["to_carrier"],
        carrier_changed=f["carrier_changed"],
        transferred_at=f["transferred_at"],
        weight_kg=f.get("weight_kg"),
        volume_m3=f.get("volume_m3"),
        pallets=f.get("pallets"),
        status=CargoTransfer.INITIATED,
        initiated_by=user if getattr(user, "pk", None) else None,
        source=source,
        note=f.get("note") or "",
    )
    transfer.save()
    audit.log(
        "create", transfer, user, {"transfer": [None, _state(transfer)], "source": source}, ip=ip
    )
    return transfer


def _locked_transfer(transfer: CargoTransfer) -> tuple[CargoTransfer, Consignment]:
    probe = CargoTransfer.objects.filter(pk=transfer.pk).first()
    if probe is None:
        raise NotFound()
    consignment = lock_consignment(probe.consignment)
    locked = CargoTransfer.objects.select_for_update().select_related("to_stop").get(pk=transfer.pk)
    return locked, consignment


_EVENT_FOR_KIND = {
    CargoTransfer.TO_STORAGE: "stored",
    CargoTransfer.FROM_STORAGE: "loaded",
    CargoTransfer.TO_CARRIER: "transferred",
    CargoTransfer.BETWEEN_VEHICLES: "transferred",
}


@transaction.atomic
def confirm_transfer(transfer: CargoTransfer, user, *, ip: str | None = None) -> CargoTransfer:
    """Подтверждает инициированную передачу (право consignments.transfer проверяет API).

    Повторное подтверждение возвращает ту же запись. Фиксирует событие на остановке передачи,
    пересчитывает местонахождение груза и вызывает финансовый хук."""
    locked, consignment = _locked_transfer(transfer)
    if locked.status == CargoTransfer.CONFIRMED:
        return locked
    if locked.status != CargoTransfer.INITIATED:
        raise ValidationError({"status": "Подтвердить можно только инициированную передачу"})
    if locked.reversals.exists():
        raise ValidationError({"status": "Передача уже отменена сторно"})
    _validate(
        consignment,
        {
            "transfer_kind": locked.transfer_kind,
            "to_stop": locked.to_stop,
            "from_stop": locked.from_stop,
            "from_trip": locked.from_trip,
            "to_trip": locked.to_trip,
            "from_carrier": locked.from_carrier_id,
            "to_carrier": locked.to_carrier_id,
            "transferred_at": locked.transferred_at,
            **{d: getattr(locked, d) for d in DIMENSIONS},
        },
    )
    before = _state(locked)
    locked.status = CargoTransfer.CONFIRMED
    locked.confirmed_by = user if getattr(user, "pk", None) else None
    locked.confirmed_at = timezone.now()
    locked.save()
    stop = ConsignmentPoint.objects.select_for_update().get(pk=locked.to_stop_id)
    _record(
        consignment,
        _EVENT_FOR_KIND[locked.transfer_kind],
        stop=stop,
        leg=None,
        trip=locked.to_trip or locked.from_trip,
        occurred_at=locked.transferred_at,
        user=user,
        source=MANUAL,
        note=f"Передача #{locked.pk}",
        ip=ip,
    )
    audit.log("update", locked, user, {"transfer": [before, _state(locked)]}, ip=ip)
    recompute_location(consignment)
    _finance_hook(consignment, user)
    return locked


@transaction.atomic
def reverse_transfer(
    transfer: CargoTransfer, user, *, note: str = "", ip: str | None = None
) -> CargoTransfer:
    """Сторно: новая запись (status=reversed, reverses=исходная), исходная не меняется."""
    locked, consignment = _locked_transfer(transfer)
    if locked.status == CargoTransfer.REVERSED:
        raise ValidationError({"status": "Сторно-запись отменить нельзя"})
    if locked.reversals.exists():
        raise ValidationError({"status": "Передача уже отменена сторно"})
    now = timezone.now()
    storno = CargoTransfer(
        consignment=consignment,
        from_trip=locked.from_trip,
        to_trip=locked.to_trip,
        from_stop=locked.from_stop,
        to_stop=locked.to_stop,
        transfer_kind=locked.transfer_kind,
        from_carrier=locked.from_carrier,
        to_carrier=locked.to_carrier,
        carrier_changed=locked.carrier_changed,
        transferred_at=now,
        weight_kg=locked.weight_kg,
        volume_m3=locked.volume_m3,
        pallets=locked.pallets,
        status=CargoTransfer.REVERSED,
        initiated_by=user if getattr(user, "pk", None) else None,
        source=MANUAL,
        confirmed_by=user if getattr(user, "pk", None) else None,
        confirmed_at=now,
        reverses=locked,
        note=(note or "").strip(),
    )
    storno.save()
    audit.log(
        "create",
        storno,
        user,
        {"reverses": [None, locked.pk], "transfer": [None, _state(storno)]},
        ip=ip,
    )
    recompute_location(consignment)
    _finance_hook(consignment, user)
    return storno
