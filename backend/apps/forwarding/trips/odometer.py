"""Официальный пробег рейса: выезд (IN_PROGRESS) и завершение (COMPLETED) по отчёту водителя.

Пробег передаётся вместе со сменой статуса или отдельным действием (позднее внесение или
исправление). Хранится в fleet.MileageReading; пробег из заправок, обслуживания и GPS сюда не
попадает. Передавать пробег необязательно: рейс можно начать и завершить без него.
"""

from rest_framework.exceptions import ValidationError

from .resources import effective_modules

START, END = "start", "end"
STARTED_CODES = ("IN_PROGRESS", "UNLOADING", "COMPLETED")


def phase_for_transition(old_code: str, new_code: str) -> str | None:
    """Выезд - переход в IN_PROGRESS не из UNLOADING; завершение - переход в COMPLETED."""
    if new_code == "IN_PROGRESS" and old_code != "UNLOADING":
        return START
    if new_code == "COMPLETED":
        return END
    return None


def record(trip, phase: str, *, vehicle_km=None, trailer_km=None) -> list:
    """Записывает официальные показания тягача и/или прицепа рейса; возвращает показания."""
    from apps.fleet import services

    if vehicle_km is None and trailer_km is None:
        return []
    if "fleet" not in effective_modules(trip.company_id):
        raise ValidationError({"odometer": "Модуль автопарка не подключён"})
    status_code = trip.status.code
    if phase == START and status_code not in STARTED_CODES:
        raise ValidationError({"odometer": "Пробег выезда вносится после выезда рейса"})
    if phase == END and status_code != "COMPLETED":
        raise ValidationError({"odometer": "Пробег завершения вносится после завершения рейса"})
    out = []
    units = (("vehicle_km", vehicle_km, trip.vehicle), ("trailer_km", trailer_km, trip.trailer))
    for field, km, unit in units:
        if km is None:
            continue
        if unit is None:
            raise ValidationError({field: "На рейсе не назначена соответствующая техника"})
        out.append(services.record_trip_mileage(trip, unit, km, phase))
    return out
