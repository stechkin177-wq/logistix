"""Участки перевозки (развитие TripConsignment): правила, покрытие маршрута, статусы.

Участок - часть маршрута груза от остановки ``from_stop`` до ``to_stop`` (по ``seq``), которую
выполняет рейс. Правила (этап 1.5-C2):

* ``from_stop.seq < to_stop.seq``, обе остановки принадлежат ЭТОМУ грузу;
* доли (вес, объём, паллеты) не отрицательны и не больше количества груза; участок с пустыми
  долями по всем измерениям - «весь груз»;
* на каждом отрезке маршрута (между соседними остановками) сумма указанных долей всех
  неотменённых участков груза по каждому измерению не больше количества груза (пустая доля по
  измерению его не ограничивает); участок «весь груз» исключает любые другие участки на том же
  отрезке;
* один груз на двух рейсах на РАЗНЫХ отрезках допустим (передача между рейсами).

Записи без остановок (NULL, NULL) - прежние связи «весь груз»: для проверок и покрытия они
считаются участком от первой до последней остановки маршрута.

«Покрытие маршрута» (``route_coverage``) считается по остановкам и неотменённым участкам, без
фиктивных строк.
"""

from dataclasses import dataclass
from decimal import Decimal

from rest_framework.exceptions import ValidationError

from ..consignments.models import Consignment, ConsignmentPoint
from .models import Trip, TripConsignment

DIMENSIONS = ("weight_kg", "volume_m3", "pallets")
COMPLETED_CODE = "COMPLETED"
CANCELLED_CODE = "CANCELLED"
IN_PROGRESS_CODES = {"IN_PROGRESS", "UNLOADING"}


def leg_status_for(trip_status_code: str | None) -> str:
    """Статус участка по системному коду статуса рейса."""
    if trip_status_code == COMPLETED_CODE:
        return TripConsignment.DONE
    if trip_status_code == CANCELLED_CODE:
        return TripConsignment.CANCELLED
    if trip_status_code in IN_PROGRESS_CODES:
        return TripConsignment.IN_PROGRESS
    return TripConsignment.PLANNED


@dataclass
class LegSpec:
    """Желаемый участок рейса для груза (до записи в БД)."""

    consignment: Consignment
    from_stop: ConsignmentPoint | None = None
    to_stop: ConsignmentPoint | None = None
    weight_kg: Decimal | None = None
    volume_m3: Decimal | None = None
    pallets: int | None = None
    # участок создан прежним способом (consignment_ids = весь маршрут): такой участок, как и раньше,
    # может сосуществовать с другим участком «весь груз на весь маршрут» (перегруз без остановок)
    legacy: bool = False

    @property
    def key(self):
        return (
            self.consignment.pk,
            self.from_stop.pk if self.from_stop else None,
            self.to_stop.pk if self.to_stop else None,
        )

    def shares(self) -> dict:
        return {d: getattr(self, d) for d in DIMENSIONS}


def stops_of(consignment: Consignment) -> list[ConsignmentPoint]:
    return sorted(consignment.points.all(), key=lambda p: (p.seq, p.pk))


def whole_route(
    consignment: Consignment,
) -> tuple[ConsignmentPoint | None, ConsignmentPoint | None]:
    """Первая погрузка и последняя выгрузка маршрута (None, None - маршрута нет)."""
    stops = stops_of(consignment)
    load = next((p for p in stops if p.kind == ConsignmentPoint.LOAD), None)
    unload = next((p for p in reversed(stops) if p.kind == ConsignmentPoint.UNLOAD), None)
    if load is None or unload is None or load.seq >= unload.seq:
        return None, None
    return load, unload


def whole_spec(consignment: Consignment) -> LegSpec:
    """Участок «весь маршрут»: от первой погрузки до последней выгрузки."""
    first, last = whole_route(consignment)
    return LegSpec(consignment, first, last, legacy=True)


def _interval(consignment: Consignment, from_stop, to_stop, last_seq: int) -> tuple[int, int]:
    """[начало, конец) участка в seq; пустая пара - весь маршрут."""
    if from_stop is None or to_stop is None:
        return 1, last_seq
    return from_stop.seq, to_stop.seq


def _is_whole(shares: dict) -> bool:
    return all(shares[d] is None for d in DIMENSIONS)


def _total(consignment: Consignment, dimension: str):
    return getattr(consignment, dimension)


def check_spec(spec: LegSpec) -> None:
    """Самостоятельные правила участка: остановки груза, порядок, доли."""
    c = spec.consignment
    if (spec.from_stop is None) != (spec.to_stop is None):
        raise ValidationError({"legs": "Укажите обе остановки участка или ни одной"})
    if spec.from_stop is not None:
        for stop in (spec.from_stop, spec.to_stop):
            if stop.consignment_id != c.pk:
                raise ValidationError({"legs": f"Остановка {stop.pk} не принадлежит грузу {c.pk}"})
        if spec.from_stop.seq >= spec.to_stop.seq:
            raise ValidationError(
                {"legs": "Участок должен идти вперёд по маршруту: начало раньше конца"}
            )
    for dimension in DIMENSIONS:
        value = getattr(spec, dimension)
        if value is None:
            continue
        if value < 0:
            raise ValidationError({"legs": "Доля участка не может быть отрицательной"})
        if value > _total(c, dimension):
            raise ValidationError({"legs": "Доля участка больше количества груза"})


def _existing_active(consignment: Consignment, *, exclude_trip_id=None) -> list:
    qs = TripConsignment.objects.filter(
        consignment=consignment, trip__deleted_at__isnull=True
    ).exclude(status=TripConsignment.CANCELLED)
    if exclude_trip_id is not None:
        qs = qs.exclude(trip_id=exclude_trip_id)
    return list(qs.select_related("from_stop", "to_stop"))


def check_consignment_legs(
    consignment: Consignment, specs: list[LegSpec], *, exclude_trip_id=None, others=None
) -> None:
    """Проверка набора участков рейса для груза вместе с участками ДРУГИХ рейсов.

    ``specs`` - желаемые неотменённые участки груза в этом рейсе. ``exclude_trip_id`` - рейс,
    чьи текущие участки заменяются (их в «других» нет). ``others`` позволяет передать готовый
    список (по умолчанию читается из БД).
    """
    for spec in specs:
        check_spec(spec)
    keys = [s.key for s in specs]
    if len(keys) != len(set(keys)):
        raise ValidationError({"legs": "Один и тот же участок груза указан дважды"})
    stops = stops_of(consignment)
    first_seq = min((p.seq for p in stops), default=1)
    last_seq = max((p.seq for p in stops), default=1)
    if others is None:
        others = _existing_active(consignment, exclude_trip_id=exclude_trip_id)

    def is_full_whole(interval, shares) -> bool:
        return interval == (first_seq, last_seq) and _is_whole(shares)

    news = [
        (_interval(consignment, s.from_stop, s.to_stop, last_seq), s.shares(), s) for s in specs
    ]
    olds = [
        (
            _interval(consignment, o.from_stop, o.to_stop, last_seq),
            {d: getattr(o, d) for d in DIMENSIONS},
        )
        for o in others
    ]
    for (start, end), _shares, spec in news:
        # прежний путь (consignment_ids) не вытесняется участком «весь груз на весь маршрут»
        rivals = [
            (interval, shares)
            for interval, shares in olds
            if not (spec.legacy and is_full_whole(interval, shares))
        ]
        items = [(interval, shares) for interval, shares, _spec in news] + rivals
        for segment in range(start, end):  # отрезок k лежит между остановками k и k+1
            covering = [it for it in items if it[0][0] <= segment < it[0][1]]
            if len(covering) < 2:
                continue
            if any(_is_whole(it[1]) for it in covering):
                raise ValidationError(
                    {
                        "legs": "На этом отрезке маршрута груз уже назначен на другой рейс "
                        "целиком: участок с полным грузом исключает другие рейсы"
                    }
                )
            for dimension in DIMENSIONS:
                total = _total(consignment, dimension)
                # пустая доля по измерению его не ограничивает; считаются указанные доли
                used = sum(it[1][dimension] for it in covering if it[1][dimension] is not None)
                if used > total:
                    raise ValidationError(
                        {
                            "legs": "Сумма долей участков на одном отрезке маршрута "
                            f"превышает количество груза ({dimension})"
                        }
                    )


# --- покрытие маршрута ---


def route_coverage(consignment: Consignment) -> dict:
    """Покрытие маршрута груза неотменёнными участками рейсов (без фиктивных строк).

    Отрезок - пара соседних остановок. Покрыт, если есть неотменённый участок рейса (рейс не
    удалён) с ``from.seq <= начало отрезка`` и ``to.seq >= конец отрезка``. Участок без
    остановок (прежняя связь) покрывает весь маршрут. Доли не учитываются: частично
    покрытый долями отрезок считается покрытым.
    """
    stops = stops_of(consignment)
    legs = [
        link
        for link in consignment.trip_links.all()
        if link.status != TripConsignment.CANCELLED and link.trip.deleted_at is None
    ]
    segments = []
    last_seq = stops[-1].seq if stops else 1
    for begin, end in zip(stops, stops[1:], strict=False):
        covering = []
        for link in legs:
            start, finish = _interval(consignment, link.from_stop, link.to_stop, last_seq)
            if start <= begin.seq and finish >= end.seq:
                covering.append(link.pk)
        segments.append(
            {
                "from_stop": begin.pk,
                "to_stop": end.pk,
                "from_seq": begin.seq,
                "to_seq": end.seq,
                "covered": bool(covering),
                "legs": covering,
            }
        )
    uncovered = [s for s in segments if not s["covered"]]
    return {
        "segments": segments,
        "uncovered": uncovered,
        "fully_assigned": bool(segments) and not uncovered,
    }


# --- статусы участков вместе с рейсом ---


def sync_leg_statuses(trip: Trip) -> int:
    """Приводит статусы участков рейса к статусу рейса (по системному коду).

    Завершён -> done, отменён -> cancelled (участок снимает покрытие отрезка), в пути/выгрузка
    -> in_progress, иначе planned. Возвращает число изменённых участков. Выход рейса из
    «Отменён» возвращает участки в работу, поэтому здесь же проверяется, что они не конфликтуют
    с участками других рейсов, назначенными за время отмены (иначе ValidationError).
    """
    target = leg_status_for(trip.status.code)
    links = list(TripConsignment.objects.filter(trip=trip).select_related("from_stop", "to_stop"))
    stale = [link for link in links if link.status != target]
    if not stale:
        return 0
    if target != TripConsignment.CANCELLED and any(
        link.status == TripConsignment.CANCELLED for link in stale
    ):
        _check_revive(trip, links)
    TripConsignment.objects.filter(pk__in=[link.pk for link in stale]).update(status=target)
    return len(stale)


def _check_revive(trip: Trip, links: list) -> None:
    by_consignment: dict[int, list] = {}
    for link in links:
        by_consignment.setdefault(link.consignment_id, []).append(link)
    consignments = {
        c.pk: c
        for c in Consignment.objects.select_for_update(of=("self",))
        .filter(pk__in=by_consignment)
        .order_by("pk")
    }
    for pk, group in by_consignment.items():
        # возвращаемые в работу участки «весь груз на весь маршрут» - прежнего вида (legacy)
        specs = [
            LegSpec(
                consignments[pk],
                link.from_stop,
                link.to_stop,
                link.weight_kg,
                link.volume_m3,
                link.pallets,
                legacy=link.from_stop_id is None
                or (link.weight_kg is None and link.volume_m3 is None and link.pallets is None),
            )
            for link in group
        ]
        try:
            check_consignment_legs(consignments[pk], specs, exclude_trip_id=trip.pk)
        except ValidationError:
            raise ValidationError(
                {
                    "status": "Нельзя вернуть рейс в работу: его участки пересекаются с участками "
                    "других рейсов, назначенных после отмены"
                }
            ) from None
