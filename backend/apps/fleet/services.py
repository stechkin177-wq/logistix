"""Эксплуатационный учёт: пробег, расход топлива, напоминания. Деньги здесь не считаются."""

from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.models import Company
from apps.core.tenancy import get_current_company_id

from .models import FuelFill, Insurance, MileageReading, ServiceRecord, Vehicle, VehicleDocument

CENT = Decimal("0.01")


def company_today() -> date:
    company = Company.objects.get(pk=get_current_company_id())
    return timezone.now().astimezone(ZoneInfo(company.timezone)).date()


# --- пробег ---------------------------------------------------------------------------------


def day_start(day: date) -> datetime:
    """Момент показаний одометра по записи обслуживания: начало дня выполнения (UTC)."""
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


def record_mileage(vehicle: Vehicle, km: int | None, at: datetime, source: str):
    """Записывает показание, если такого (техника, значение, источник) ещё нет."""
    if km is None:
        return None
    existing = MileageReading.objects.filter(vehicle=vehicle, odometer_km=km, source=source)
    if existing.filter(recorded_at=at).exists():
        return None
    return MileageReading.objects.create(
        vehicle=vehicle, recorded_at=at, odometer_km=km, source=source
    )


def latest_odometer(vehicle_id: int) -> int | None:
    row = (
        MileageReading.objects.filter(vehicle_id=vehicle_id)
        .order_by("-odometer_km")
        .values_list("odometer_km", flat=True)
        .first()
    )
    return row


# --- расход топлива -------------------------------------------------------------------------


def fuel_stats(vehicle: Vehicle) -> dict:
    """Расход на 100 км по заправкам «до полного бака».

    Сегмент - от одной полной заправки до следующей полной: литры всех заправок сегмента
    (после предыдущей полной, включая текущую) делятся на пройденные километры. Заправки без
    пробега в расчёт не входят (перечислены в ``skipped``). Среднее - по сумме сегментов.
    """
    fills = list(FuelFill.objects.filter(vehicle=vehicle).order_by("filled_at", "id"))
    skipped = [f.pk for f in fills if f.odometer_km is None]
    usable = [f for f in fills if f.odometer_km is not None]
    segments = []
    anchor = None
    liters = Decimal(0)
    for fill in usable:
        if anchor is None:
            if fill.full_tank:
                anchor, liters = fill, Decimal(0)
            continue
        liters += fill.liters
        if fill.full_tank:
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
        "skipped": skipped,
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
