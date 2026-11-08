"""Эксплуатационный учёт: пробег, расход топлива, напоминания. Деньги здесь не считаются."""

from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.models import Company
from apps.core.tenancy import get_current_company_id

from .models import (
    FleetSettings,
    FuelFill,
    Insurance,
    MileageReading,
    ServiceRecord,
    Vehicle,
    VehicleDocument,
)

CENT = Decimal("0.01")


def company_today() -> date:
    company = Company.objects.get(pk=get_current_company_id())
    return timezone.now().astimezone(ZoneInfo(company.timezone)).date()


# --- официальный пробег ---------------------------------------------------------------------
# Фиксируется только при выезде в рейс и по завершении рейса (отчёт водителя). Пробег в заправках,
# обслуживании и т.п. - справочный и сюда не попадает. GPS показания не создаёт и не меняет.


def day_start(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC)


def check_odometer(vehicle: Vehicle, km: int, at: datetime, *, exclude_id=None) -> None:
    """Показание не должно нарушать порядок: не меньше предыдущего и не больше следующего."""
    qs = MileageReading.objects.filter(vehicle=vehicle)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    before = qs.filter(recorded_at__lte=at).order_by("-recorded_at", "-id").first()
    after = qs.filter(recorded_at__gt=at).order_by("recorded_at", "id").first()
    if before is not None and km < before.odometer_km:
        raise ValidationError(
            {"odometer_km": f"Пробег меньше предыдущего показания ({before.odometer_km} км)"}
        )
    if after is not None and km > after.odometer_km:
        raise ValidationError(
            {"odometer_km": f"Пробег больше следующего показания ({after.odometer_km} км)"}
        )


def record_trip_mileage(trip, vehicle: Vehicle, km: int, phase: str) -> MileageReading:
    """Официальное показание единицы техники для рейса: одно на (рейс, техника, фаза).

    Повторная передача исправляет значение (исправление ошибки водителя/диспетчера) без второй
    записи. Показание при завершении не меньше показания выезда этого же рейса.
    """
    source = MileageReading.TRIP_START if phase == "start" else MileageReading.TRIP_END
    existing = MileageReading.objects.filter(trip=trip, vehicle=vehicle, source=source).first()
    at = existing.recorded_at if existing else timezone.now()
    check_odometer(vehicle, km, at, exclude_id=existing.pk if existing else None)
    if phase == "end":
        start = MileageReading.objects.filter(
            trip=trip, vehicle=vehicle, source=MileageReading.TRIP_START
        ).first()
        if start is not None and km < start.odometer_km:
            raise ValidationError(
                {"odometer_km": f"Пробег по завершении меньше пробега выезда ({start.odometer_km})"}
            )
    if existing:
        existing.odometer_km = km
        existing.save(update_fields=["odometer_km"])
        return existing
    return MileageReading.objects.create(
        vehicle=vehicle, trip=trip, recorded_at=at, odometer_km=km, source=source
    )


def latest_official(vehicle_id: int) -> MileageReading | None:
    return (
        MileageReading.objects.filter(vehicle_id=vehicle_id)
        .order_by("-recorded_at", "-id")
        .first()
    )


def latest_odometer(vehicle_id: int) -> int | None:
    reading = latest_official(vehicle_id)
    return reading.odometer_km if reading else None


def fleet_settings() -> FleetSettings:
    """Настройки автопарка текущей компании (создаются при первом обращении)."""
    obj = FleetSettings.objects.first()
    return obj or FleetSettings.objects.create()


def mileage_check(vehicle: Vehicle) -> dict:
    """Сверка официального пробега с GPS (только показ; ничего не меняет и не записывает).

    GPS-модуль регистрирует источник через ``register_gps_source``; пока источника нет или он не
    отдаёт данные, ``gps_available`` = False (данные недоступны).
    """
    if not vehicle.gps_check:
        return {"enabled": False}
    threshold = fleet_settings().gps_mismatch_km
    official = latest_official(vehicle.pk)
    result = {
        "enabled": True,
        "official_km": official.odometer_km if official else None,
        "official_at": official.recorded_at if official else None,
        "gps_km": None,
        "gps_available": False,
        "difference_km": None,
        "threshold_km": threshold,
        "warning": False,
    }
    gps = gps_mileage(vehicle, official.recorded_at if official else timezone.now())
    if gps is not None:
        result["gps_km"], result["gps_available"] = gps, True
        if official is not None:
            diff = gps - official.odometer_km
            result["difference_km"] = diff
            result["warning"] = abs(diff) > threshold
    return result


_GPS_SOURCES = []


def register_gps_source(source) -> None:
    """Источник GPS-пробега: ``source(vehicle, at) -> км | None`` (регистрирует модуль gps)."""
    if source not in _GPS_SOURCES:
        _GPS_SOURCES.append(source)


def unregister_gps_source(source) -> None:
    if source in _GPS_SOURCES:
        _GPS_SOURCES.remove(source)


def gps_mileage(vehicle: Vehicle, at: datetime) -> int | None:
    for source in _GPS_SOURCES:
        value = source(vehicle, at)
        if value is not None:
            return value
    return None


# --- расход топлива -------------------------------------------------------------------------


def fuel_stats(vehicle: Vehicle) -> dict:
    """Расход на 100 км между полными заправками.

    Точки отсчёта (якоря) - только ПОЛНЫЕ заправки С пробегом: по ним определяется пройденное
    расстояние. Литры ВСЕХ заправок между двумя соседними якорями (после первого, включая второй)
    суммируются, даже если у части из них нет пробега или бак не полный: топливо потрачено, а
    расстояние известно по якорям. Заправки до первого якоря не учитываются (неизвестен уровень
    топлива в начале). Заправки без пробега не могут быть якорем и перечислены в ``no_odometer``.
    Сегмент с нулевым или отрицательным расстоянием отбрасывается. Среднее - по сумме сегментов.
    """
    fills = list(FuelFill.objects.filter(vehicle=vehicle).order_by("filled_at", "id"))
    no_odometer = [f.pk for f in fills if f.odometer_km is None]
    segments = []
    anchor = None
    liters = Decimal(0)
    for fill in fills:
        is_anchor = fill.full_tank and fill.odometer_km is not None
        if anchor is None:
            if is_anchor:
                anchor, liters = fill, Decimal(0)
            continue
        liters += fill.liters
        if is_anchor:
            distance = fill.odometer_km - anchor.odometer_km
            if distance > 0:
                segments.append(
                    {
                        "fill": fill.pk,
                        "from_km": anchor.odometer_km,
                        "to_km": fill.odometer_km,
                        "distance_km": distance,
                        "liters": liters,
                        "l_per_100km": (liters / distance * 100).quantize(CENT, ROUND_HALF_UP),
                    }
                )
            anchor, liters = fill, Decimal(0)
    total_distance = sum(s["distance_km"] for s in segments)
    total_liters = sum((s["liters"] for s in segments), Decimal(0))
    average = (
        (total_liters / total_distance * 100).quantize(CENT, ROUND_HALF_UP)
        if total_distance
        else None
    )
    return {
        "vehicle": vehicle.pk,
        "average_l_per_100km": average,
        "distance_km": total_distance,
        "liters": total_liters,
        "segments": segments,
        "no_odometer": no_odometer,
    }


# --- напоминания ----------------------------------------------------------------------------


def _state(due_date, due_km, current_km, today, days, km_margin):
    """overdue / due_soon / None по дате и пробегу (что наступит раньше)."""
    states = []
    if due_date is not None:
        states.append(
            "overdue"
            if due_date < today
            else "due_soon"
            if due_date <= today + timedelta(days=days)
            else None
        )
    if due_km is not None and current_km is not None:
        states.append(
            "overdue"
            if current_km >= due_km
            else "due_soon"
            if current_km + km_margin >= due_km
            else None
        )
    if "overdue" in states:
        return "overdue"
    return "due_soon" if "due_soon" in states else None


def reminders(days: int = 30, km_margin: int = 1000, vehicle_id: int | None = None) -> list[dict]:
    """Просроченные и приближающиеся ТО, документы и страховки (источник для уведомлений).

    ТО: планируемые записи (planned_date) и последнее выполненное обслуживание каждого вида с
    заданным next_due_date/next_due_km. Пробег берётся из показаний каждой единицы техники.
    """
    today = company_today()
    vehicles = Vehicle.objects.exclude(status=Vehicle.INACTIVE)
    if vehicle_id:
        vehicles = vehicles.filter(pk=vehicle_id)
    out: list[dict] = []
    for vehicle in vehicles.order_by("plate"):
        current = latest_odometer(vehicle.pk)

        def add(kind, title, due_date, due_km, vehicle=vehicle, current=current):
            state = _state(due_date, due_km, current, today, days, km_margin)
            if state:
                out.append(
                    {
                        "type": kind,
                        "state": state,
                        "vehicle": vehicle.pk,
                        "plate": vehicle.plate,
                        "title": title,
                        "due_date": due_date,
                        "due_km": due_km,
                        "current_km": current,
                    }
                )

        services = ServiceRecord.objects.filter(vehicle=vehicle)
        planned = services.filter(status__in=["planned", "in_progress"], planned_date__isnull=False)
        for rec in planned:
            add("service", rec.title, rec.planned_date, None)
        seen = set()
        done = services.filter(status="done").filter(
            Q(next_due_date__isnull=False) | Q(next_due_km__isnull=False)
        )
        for rec in done.order_by("-done_date", "-id"):
            if rec.kind in seen:
                continue
            seen.add(rec.kind)
            add("service", rec.title, rec.next_due_date, rec.next_due_km)
        for doc in VehicleDocument.objects.filter(vehicle=vehicle, expires_at__isnull=False):
            add("document", doc.get_kind_display(), doc.expires_at, None)
        for ins in Insurance.objects.filter(vehicle=vehicle, expires_at__isnull=False):
            add("insurance", ins.get_kind_display(), ins.expires_at, None)
    out.sort(key=lambda r: (r["state"] != "overdue", r["due_date"] or date.max, r["plate"]))
    return out
