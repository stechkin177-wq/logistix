from django.db import IntegrityError, transaction
from django.db.models import OuterRef
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.exceptions import APIException, ValidationError

from apps.core.audit import services as audit
from apps.core.handbooks.models import HandbookValue
from apps.core.models import LegalEntity
from apps.core.numbering.services import next_number

from ..consignments.services import create_consignment, created_changes, initial_status
from ..finance_lines.services import sync_base_line
from ..trips.models import TripConsignment
from .models import Order, OrderStatusHistory

COMPLETED_CODE = "completed"
NUMBER_CONSTRAINT = "order_company_number_uniq"


class NumberConflict(APIException):
    status_code = http_status.HTTP_409_CONFLICT
    default_detail = (
        "Номер заказа уже занят: проверьте счётчик нумерации заказов в настройках компании"
    )
    default_code = "number_conflict"


def carried_with_carrier(order=OuterRef("pk")):
    """Груз заказа едет в не удалённом рейсе с перевозчиком (рейс без перевозчика не считается)."""
    return TripConsignment.objects.filter(
        consignment__order=order,
        consignment__deleted_at__isnull=True,
        trip__deleted_at__isnull=True,
        trip__carrier__isnull=False,
    )


def _default_currency() -> HandbookValue:
    value = HandbookValue.objects.filter(
        handbook__code="currency", code="KZT", is_active=True
    ).first()
    if value is None:
        raise ValidationError({"currency": "Укажите валюту: значение KZT недоступно"})
    return value


def _default_legal_entity() -> LegalEntity:
    entity = LegalEntity.objects.filter(is_default=True).first()
    if entity is None:
        raise ValidationError({"legal_entity": "Укажите юрлицо: юрлицо по умолчанию не задано"})
    return entity


@transaction.atomic
def create_order(data: dict, user, *, ip: str | None = None) -> Order:
    """Создаёт заказ вместе с грузами и точками в одной транзакции.

    data - проверенные значения (модели вместо id): client обязателен; manager (по умолчанию
    user), legal_entity (юрлицо компании по умолчанию), currency (KZT) подставляются; номер
    выдаёт next_number, статус - начальный order_status; extra_managers и consignments (каждый
    с points) необязательны. Пишет первую строку истории статусов и аудит create.
    """
    data = dict(data)
    consignments = data.pop("consignments", None) or []
    extra_managers = data.pop("extra_managers", None) or []
    for forbidden in ("number", "status", "completed_at", "created_by"):
        data.pop(forbidden, None)
    data.setdefault("manager", user)
    if data.get("legal_entity") is None:
        data["legal_entity"] = _default_legal_entity()
    if data.get("currency") is None:
        data["currency"] = _default_currency()
    status = initial_status("order_status")
    # номер берётся внутри внешней транзакции: строка правила заблокирована до коммита,
    # поэтому параллельные заказы получают разные последовательные номера
    order = Order(number=next_number("order"), status=status, created_by=user, **data)
    try:
        with transaction.atomic():
            order.save()
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.__cause__, "diag", None), "constraint_name", "") or ""
        if constraint != NUMBER_CONSTRAINT:
            raise
        raise NumberConflict() from None
    if extra_managers:
        order.extra_managers.set(extra_managers)
    OrderStatusHistory(order=order, from_status=None, to_status=status, user=user).save()
    sync_base_line(order)  # «Начальная ставка» = client_rate; аудит заказа её уже покрывает
    changes = audit.diff({}, audit.snapshot(order))
    if extra_managers:  # как при PATCH: [было, стало] списками id
        changes["extra_managers"] = [[], sorted(u.pk for u in extra_managers)]
    audit.log("create", order, user, changes, ip=ip)
    for item in consignments:
        consignment = create_consignment(order, item)
        audit.log("create", consignment, user, created_changes(consignment), ip=ip)
    return order


@transaction.atomic
def change_status(order: Order, status: HandbookValue, user, *, ip: str | None = None) -> Order:
    """Переводит заказ в статус order_status; возвращает обновлённый заказ.

    Переходы свободные (любой -> любой), запрещён только тот же статус (ValidationError).
    completed_at ставится ТОЛЬКО при статусе с кодом `completed` и сбрасывается при любом
    другом (переоткрытие). Пишет строку истории и аудит update с разницей полей.
    """
    locked = Order.objects.select_for_update().get(pk=order.pk)
    if (
        status.handbook.code != "order_status"
        or status.company_id != locked.company_id
        or not status.is_active
    ):
        raise ValidationError({"status": "Нужен активный статус заказа этой компании"})
    if status.pk == locked.status_id:
        raise ValidationError({"status": "Заказ уже в этом статусе"})
    before = audit.snapshot(locked)
    old_status_id = locked.status_id
    locked.status = status
    locked.completed_at = timezone.now() if status.code == COMPLETED_CODE else None
    locked.save(update_fields=["status", "completed_at", "updated_at"])
    OrderStatusHistory(
        order=locked, from_status_id=old_status_id, to_status=status, user=user
    ).save()
    audit.log("update", locked, user, audit.diff(before, audit.snapshot(locked)), ip=ip)
    return locked
