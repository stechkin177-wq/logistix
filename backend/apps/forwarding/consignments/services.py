from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.core.audit import services as audit
from apps.core.handbooks.models import HandbookValue

from .models import Consignment, ConsignmentPoint

KINDS = {ConsignmentPoint.LOAD, ConsignmentPoint.UNLOAD}
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


def check_points(points: list[dict]) -> None:
    if sorted(str(p.get("kind")) for p in points) != sorted(KINDS):
        raise ValidationError({"points": "Нужны ровно две точки: погрузка и выгрузка"})


def _check_window(window_from, window_to) -> None:
    if window_to is not None and window_from is not None and window_to < window_from:
        raise ValidationError({"points": "Окно выгрузки заканчивается раньше начала"})


@transaction.atomic
def create_consignment(order, data: dict) -> Consignment:
    """Груз заказа с обеими точками; статус по умолчанию - начальный consignment_status."""
    data = dict(data)
    points = data.pop("points", [])
    check_points(points)
    data.setdefault("status", None)
    if data["status"] is None:
        data["status"] = initial_status("consignment_status")
    consignment = Consignment(order=order, **data)
    consignment.save()
    for item in points:
        _check_window(item.get("window_from"), item.get("window_to"))
        ConsignmentPoint(consignment=consignment, **item).save()
    return consignment


@transaction.atomic
def update_points(consignment: Consignment, items: list[dict]) -> bool:
    """Обновляет точки по виду (частичные данные допустимы); True, если что-то изменилось."""
    check_points(items)
    current = {p.kind: p for p in consignment.points.all()}
    changed = False
    for item in items:
        point = current[item["kind"]]
        before = [getattr(point, f) for f in POINT_FIELDS]
        for field in POINT_FIELDS:
            if field in item:
                setattr(point, field, item[field])
        if [getattr(point, f) for f in POINT_FIELDS] != before:
            _check_window(point.window_from, point.window_to)
            point.save()
            changed = True
    return changed
