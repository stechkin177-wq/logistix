"""Назначение собственных техники и водителя на рейс (модули fleet и drivers).

Назначение необязательно и допустимо, только если соответствующий модуль включён и есть в
тарифе. Тягач/грузовик и прицеп - разные поля; водитель и техника должны быть в работе (проверка
при смене значения, прежние назначения не ломаются). Один ресурс не может одновременно быть на
двух рейсах, которые физически в работе (статусы IN_PROGRESS и UNLOADING): иначе 409.
Свободные поля vehicle_plate и driver_name заполняются из назначенных объектов, если пусты.
"""

from django.db.models import Q
from rest_framework.exceptions import APIException, ValidationError

from apps.billing.services import get_subscription
from apps.core.module_services import effective_module_codes

BUSY_CODES = ("IN_PROGRESS", "UNLOADING")
TRUCK_KINDS = ("tractor", "truck", "other")


class ResourceBusy(APIException):
    status_code = 409
    default_detail = "Ресурс уже занят на другом рейсе в работе"
    default_code = "resource_busy"


def effective_modules(company_id: int) -> set[str]:
    sub = get_subscription(company_id)
    return set(effective_module_codes(company_id, sub.plan.modules if sub else []))


def _busy_trips(trip, *, vehicle_ids=(), driver_id=None):
    from ..models import Trip

    cond = Q()
    if vehicle_ids:
        cond |= Q(vehicle_id__in=vehicle_ids) | Q(trailer_id__in=vehicle_ids)
    if driver_id:
        cond |= Q(driver_id=driver_id)
    if not cond:
        return Trip.objects.none()
    qs = Trip.objects.filter(cond, status__code__in=BUSY_CODES)
    return qs.exclude(pk=trip.pk) if getattr(trip, "pk", None) else qs


def assert_free(trip, *, vehicle=None, trailer=None, driver=None) -> None:
    """409, если техника/прицеп/водитель (по умолчанию - рейса) заняты на другом рейсе в работе."""
    vehicle = vehicle if vehicle is not None else getattr(trip, "vehicle", None)
    trailer = trailer if trailer is not None else getattr(trip, "trailer", None)
    driver = driver if driver is not None else getattr(trip, "driver", None)
    ids = [v.pk for v in (vehicle, trailer) if v is not None]
    other = _busy_trips(trip, vehicle_ids=ids, driver_id=driver.pk if driver else None).first()
    if other is not None:
        raise ResourceBusy(
            {
                "detail": f"Техника или водитель уже заняты на рейсе {other.number}",
                "code": "resource_busy",
                "trip": other.pk,
            }
        )


def validate_assignment(attrs: dict, instance, company_id: int) -> dict:
    """Проверки назначения при создании/правке рейса; возвращает дополнения для attrs."""
    errors: dict[str, str] = {}
    modules = effective_modules(company_id)
    extra: dict = {}
    for field, module in (("vehicle", "fleet"), ("trailer", "fleet"), ("driver", "drivers")):
        if field not in attrs:
            continue
        value = attrs[field]
        previous = getattr(instance, field, None) if instance is not None else None
        if value is None or (previous is not None and value.pk == previous.pk):
            continue  # снятие назначения и неизменённое значение не проверяются
        if module not in modules:
            errors[field] = "Модуль не подключён"
        elif field == "vehicle" and value.kind == "trailer":
            errors[field] = "Прицеп назначается в поле trailer"
        elif field == "trailer" and value.kind != "trailer":
            errors[field] = "В поле trailer нужен прицеп"
        elif value.status != "active":
            errors[field] = "Техника не в работе" if field != "driver" else "Водитель не работает"
    if errors:
        raise ValidationError(errors)
    vehicle = attrs.get("vehicle", getattr(instance, "vehicle", None))
    trailer = attrs.get("trailer", getattr(instance, "trailer", None))
    driver = attrs.get("driver", getattr(instance, "driver", None))
    if vehicle is not None and trailer is not None and vehicle.pk == trailer.pk:
        raise ValidationError({"trailer": "Тягач и прицеп не могут совпадать"})
    # занятость: против других рейсов в работе (сам рейс исключается по pk)
    probe = instance if instance is not None else _Probe()
    assert_free(probe, vehicle=vehicle, trailer=trailer, driver=driver)
    # свободные поля заполняются из назначенных объектов, если пусты (совместимость документов)
    if attrs.get("vehicle") is not None and not (
        attrs.get("vehicle_plate") or getattr(instance, "vehicle_plate", "")
    ):
        extra["vehicle_plate"] = attrs["vehicle"].plate
    if attrs.get("driver") is not None and not (
        attrs.get("driver_name") or getattr(instance, "driver_name", "")
    ):
        extra["driver_name"] = attrs["driver"].full_name
    return extra


class _Probe:
    """Рейс, которого ещё нет: без pk, не исключается из выборки."""

    pk = None
    vehicle = trailer = driver = None
