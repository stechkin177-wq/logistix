"""Сервисы груза и маршрута (остановок).

Маршрут груза - упорядоченный по ``seq`` список остановок (``ConsignmentPoint`` =
``ConsignmentStop``). Бизнес-правила живут здесь, а не в БД, чтобы маршрут можно было
править по шагам:

* маршрут (когда он задан) начинается остановкой ``load`` и заканчивается ``unload``;
* ``seq`` уникальны и идут подряд 1..N (перенумерация при вставке, удалении, перестановке);
* окно времени остановки: ``window_to`` не раньше ``window_from``;
* остановку нельзя удалить, пока на неё ссылаются участки рейсов или передачи (PROTECT).

Прежний («устаревший») способ записи - ``points`` ровно из двух остановок load + unload: он
обновляет/создаёт крайние остановки маршрута (первую погрузку и последнюю выгрузку).
"""

from django.db import transaction
from django.db.models import ProtectedError
from rest_framework.exceptions import ValidationError

from apps.core.audit import services as audit
from apps.core.handbooks.models import HandbookValue

from .models import Consignment, ConsignmentPoint

LEGACY_KINDS = {ConsignmentPoint.LOAD, ConsignmentPoint.UNLOAD}
KINDS = LEGACY_KINDS  # прежнее имя: виды устаревшего поля points
STOP_KINDS = set(ConsignmentPoint.KIND_CODES)
MAX_STOPS = 50
NEW_SEQ = 10_000  # временный seq вставляемой остановки до перенумерации
TMP_SEQ = 20_000  # временные номера при перенумерации (вне диапазона 1..MAX_STOPS)
POINT_FIELDS = (
    "window_from",
    "window_to",
    "country",
    "city",
    "street",
    "method",
    "contact",
    "postal_code",
    "lat",
    "lng",
    "note",
)
# поля остановки в расширенном API (stops); kind меняется только у существующей остановки
STOP_ONLY_FIELDS = ("kind", "status", "arrived_at", "done_at", "weight_kg", "volume_m3", "pallets")
STOP_FIELDS = POINT_FIELDS + STOP_ONLY_FIELDS


def initial_status(handbook_code: str) -> HandbookValue:
    value = HandbookValue.objects.filter(
        handbook__code=handbook_code, is_initial=True, is_active=True
    ).first()
    if value is None:
        raise ValidationError({"status": "В справочнике нет активного начального статуса"})
    return value


def created_changes(consignment: Consignment) -> dict:
    """Записи аудита создания груза; состав точек (контакты) в аудит не пишется."""
    return {**audit.diff({}, audit.snapshot(consignment)), "points": "changed"}


# --- проверки ---


def check_points(points: list[dict]) -> None:
    """Устаревшее поле points: ровно две остановки, погрузка и выгрузка."""
    if sorted(str(p.get("kind")) for p in points) != sorted(LEGACY_KINDS):
        raise ValidationError({"points": "Нужны ровно две точки: погрузка и выгрузка"})


def _check_window(window_from, window_to) -> None:
    if window_to is not None and window_from is not None and window_to < window_from:
        raise ValidationError({"points": "Окно выгрузки заканчивается раньше начала"})


def check_route(kinds: list[str]) -> None:
    """Маршрут: не короче двух остановок, первая - погрузка, последняя - выгрузка."""
    if len(kinds) < 2:
        raise ValidationError({"stops": "В маршруте нужны минимум две остановки"})
    if len(kinds) > MAX_STOPS:
        raise ValidationError({"stops": f"Не больше {MAX_STOPS} остановок в маршруте"})
    if kinds[0] != ConsignmentPoint.LOAD:
        raise ValidationError({"stops": "Маршрут должен начинаться с погрузки"})
    if kinds[-1] != ConsignmentPoint.UNLOAD:
        raise ValidationError({"stops": "Маршрут должен заканчиваться выгрузкой"})


def _check_shares(consignment: Consignment, item: dict, index: int) -> None:
    for field, total in (
        ("weight_kg", consignment.weight_kg),
        ("volume_m3", consignment.volume_m3),
        ("pallets", consignment.pallets),
    ):
        value = item.get(field)
        if value is not None and value > total:
            raise ValidationError(
                {"stops": {index: {field: ["Доля на остановке больше количества груза"]}}}
            )


def _check_times(item: dict, index: int) -> None:
    start, end = item.get("arrived_at"), item.get("done_at")
    if start is not None and end is not None and end < start:
        raise ValidationError({"stops": {index: {"done_at": ["Раньше времени прибытия"]}}})


def _renumber(ordered: list[ConsignmentPoint]) -> None:
    """Присваивает seq 1..N по порядку списка (уже сохранённые остановки) без нарушения
    уникальности на промежуточных шагах: сначала временные номера, затем итоговые."""
    if all(p.seq == n for n, p in enumerate(ordered, start=1)):
        return
    for n, p in enumerate(ordered, start=1):
        ConsignmentPoint.objects.filter(pk=p.pk).update(seq=TMP_SEQ + n)
    for n, p in enumerate(ordered, start=1):
        ConsignmentPoint.objects.filter(pk=p.pk).update(seq=n)
        p.seq = n


def _lock(consignment: Consignment) -> None:
    """Правки маршрута одного груза выполняются по очереди."""
    Consignment.objects.select_for_update().filter(pk=consignment.pk).first()


def stops_of(consignment: Consignment) -> list[ConsignmentPoint]:
    return list(ConsignmentPoint.objects.filter(consignment=consignment).order_by("seq", "id"))


def first_load(stops) -> ConsignmentPoint | None:
    return next((p for p in stops if p.kind == ConsignmentPoint.LOAD), None)


def last_unload(stops) -> ConsignmentPoint | None:
    return next((p for p in reversed(list(stops)) if p.kind == ConsignmentPoint.UNLOAD), None)


def _delete_stop(stop: ConsignmentPoint) -> None:
    try:
        stop.delete()
    except ProtectedError:
        raise ValidationError(
            {
                "stops": "Нельзя удалить остановку: на неё ссылаются участки рейсов или "
                "передачи груза. Сначала измените участки"
            }
        ) from None


# --- создание груза ---


def _stop_values(item: dict) -> dict:
    return {k: item[k] for k in STOP_FIELDS if k in item}


@transaction.atomic
def create_consignment(order, data: dict) -> Consignment:
    """Груз заказа с маршрутом; статус по умолчанию - начальный consignment_status.

    Маршрут задаётся ``stops`` (расширенно) либо ``points`` (устаревшее: ровно load + unload).
    """
    data = dict(data)
    points = data.pop("points", None)
    stops = data.pop("stops", None)
    if points is not None and stops is not None:
        raise ValidationError({"stops": "Передайте либо points, либо stops, но не оба поля"})
    if stops is None and points is None:
        raise ValidationError({"points": "Нужны ровно две точки: погрузка и выгрузка"})
    if stops is None:
        check_points(points)
        # порядок: погрузка, затем выгрузка, независимо от порядка в запросе
        stops = sorted(points, key=lambda p: p["kind"] != ConsignmentPoint.LOAD)
    else:
        check_route([str(s.get("kind")) for s in stops])
    data.setdefault("status", None)
    if data["status"] is None:
        data["status"] = initial_status("consignment_status")
    consignment = Consignment(order=order, **data)
    consignment.save()
    for index, item in enumerate(stops):
        _check_window(item.get("window_from"), item.get("window_to"))
        _check_shares(consignment, item, index)
        _check_times(item, index)
        ConsignmentPoint(consignment=consignment, seq=index + 1, **_stop_values(item)).save()
    return consignment


# --- правка маршрута: stops (список целиком) ---


@transaction.atomic
def replace_stops(consignment: Consignment, items: list[dict]) -> bool:
    """Транзакционно заменяет/обновляет маршрут: порядок списка = порядок остановок.

    Элемент с ``id`` обновляет существующую остановку этого груза (частичные данные допустимы,
    вид менять можно), без ``id`` - создаёт новую. Остановки, которых нет в списке, удаляются
    (если на них ссылаются участки/передачи - ValidationError, маршрут не меняется).
    Возвращает True, если что-то изменилось.
    """
    _lock(consignment)
    current = {p.pk: p for p in stops_of(consignment)}
    seen: set[int] = set()
    plan: list[tuple[ConsignmentPoint | None, dict]] = []
    kinds: list[str] = []
    for index, item in enumerate(items):
        pk = item.get("id")
        stop = None
        if pk is not None:
            stop = current.get(pk)
            if stop is None:
                raise ValidationError(
                    {"stops": {index: {"id": ["Остановка не принадлежит грузу"]}}}
                )
            if pk in seen:
                raise ValidationError({"stops": {index: {"id": ["Остановка указана дважды"]}}})
            seen.add(pk)
        else:
            for required in ("kind", "window_from", "city"):
                if not item.get(required):
                    raise ValidationError(
                        {"stops": {index: {required: ["Обязательное поле новой остановки"]}}}
                    )
        kinds.append(str(item.get("kind") or stop.kind))
        plan.append((stop, item))
    check_route(kinds)
    for index, (stop, item) in enumerate(plan):
        _check_window(
            item.get("window_from", stop.window_from if stop else None),
            item.get("window_to", stop.window_to if stop else None),
        )
        _check_shares(consignment, item, index)
        _check_times(item, index)
    changed = False
    for pk, stop in current.items():  # лишние удаляем первыми: ошибка защиты до любых записей
        if pk not in seen:
            _delete_stop(stop)
            changed = True
    old_seq = {pk: stop.seq for pk, stop in current.items() if pk in seen}
    for number, (stop, _item) in enumerate(plan, start=1):  # освобождаем номера 1..N
        if stop is not None:
            ConsignmentPoint.objects.filter(pk=stop.pk).update(seq=TMP_SEQ + number)
    for number, (stop, item) in enumerate(plan, start=1):
        if stop is None:
            ConsignmentPoint(consignment=consignment, seq=number, **_stop_values(item)).save()
            changed = True
            continue
        before = [getattr(stop, f) for f in STOP_FIELDS]
        for field in STOP_FIELDS:
            if field in item:
                setattr(stop, field, item[field])
        stop.seq = number
        stop.save()
        if [getattr(stop, f) for f in STOP_FIELDS] != before or old_seq[stop.pk] != number:
            changed = True
    return changed


# --- точечные операции с перенумерацией ---


@transaction.atomic
def add_stop(consignment: Consignment, data: dict, position: int | None = None):
    """Вставляет остановку на позицию (1..N+1; по умолчанию перед последней выгрузкой не
    вставляет, а добавляет в конец). Остальные сдвигаются, seq остаются подряд."""
    _lock(consignment)
    stops = stops_of(consignment)
    position = len(stops) + 1 if position is None else position
    if not 1 <= position <= len(stops) + 1:
        raise ValidationError({"position": "Позиция вне маршрута"})
    _check_window(data.get("window_from"), data.get("window_to"))
    _check_shares(consignment, data, 0)
    kinds = [s.kind for s in stops]
    kinds.insert(position - 1, str(data.get("kind")))
    if len(kinds) >= 2:
        check_route(kinds)
    stop = ConsignmentPoint(consignment=consignment, seq=NEW_SEQ, **_stop_values(data))
    stop.save()
    ordered = stops[: position - 1] + [stop] + stops[position - 1 :]
    _renumber(ordered)
    return stop


@transaction.atomic
def remove_stop(stop: ConsignmentPoint) -> None:
    """Удаляет остановку (если не защищена участками/передачами) и перенумеровывает остальные."""
    consignment = stop.consignment
    _lock(consignment)
    stops = [s for s in stops_of(consignment) if s.pk != stop.pk]
    if stops:
        check_route([s.kind for s in stops])
    _delete_stop(stop)
    _renumber(stops)


@transaction.atomic
def move_stop(stop: ConsignmentPoint, position: int) -> list[ConsignmentPoint]:
    """Переставляет остановку на позицию 1..N; маршрут остаётся валидным."""
    consignment = stop.consignment
    _lock(consignment)
    stops = stops_of(consignment)
    if not 1 <= position <= len(stops):
        raise ValidationError({"position": "Позиция вне маршрута"})
    stops = [s for s in stops if s.pk != stop.pk]
    stops.insert(position - 1, stop)
    check_route([s.kind for s in stops])
    stop.refresh_from_db(fields=["seq"])
    _renumber(stops)
    return stops


# --- устаревшее поле points: крайние остановки ---


@transaction.atomic
def update_points(consignment: Consignment, items: list[dict]) -> bool:
    """Обновляет первую погрузку и последнюю выгрузку по виду (частичные данные допустимы);
    недостающую крайнюю остановку создаёт. True, если что-то изменилось."""
    check_points(items)
    _lock(consignment)
    stops = stops_of(consignment)
    current = {
        ConsignmentPoint.LOAD: first_load(stops),
        ConsignmentPoint.UNLOAD: last_unload(stops),
    }
    changed = False
    for item in items:
        point = current[item["kind"]]
        if point is None:
            point = _create_edge(consignment, stops, item)
            current[item["kind"]] = point
            changed = True
            continue
        before = [getattr(point, f) for f in POINT_FIELDS]
        for field in POINT_FIELDS:
            if field in item:
                setattr(point, field, item[field])
        if [getattr(point, f) for f in POINT_FIELDS] != before:
            _check_window(point.window_from, point.window_to)
            point.save()
            changed = True
    return changed


def _create_edge(consignment: Consignment, stops: list, item: dict) -> ConsignmentPoint:
    """Недостающая крайняя остановка: погрузка - в начало, выгрузка - в конец маршрута."""
    _check_window(item.get("window_from"), item.get("window_to"))
    values = {k: item[k] for k in POINT_FIELDS if k in item}
    values["kind"] = item["kind"]
    if item["kind"] == ConsignmentPoint.LOAD:
        point = ConsignmentPoint(consignment=consignment, seq=NEW_SEQ, **values)
        point.save()
        _renumber([point, *stops])
    else:
        point = ConsignmentPoint(consignment=consignment, seq=len(stops) + 1, **values)
        point.save()
    stops.insert(0 if item["kind"] == ConsignmentPoint.LOAD else len(stops), point)
    return point
