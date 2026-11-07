from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.core.models import Company
from apps.core.tenancy import tenant_context

from . import system_codes
from .defaults import DEFAULTS
from .models import STATUS_HANDBOOK_CODES, Handbook, HandbookValue
from .system_codes import MSG_MAKE_INITIAL, SystemValueProtected, system_code_assignment


@transaction.atomic
def seed_handbooks(company: Company) -> None:
    """Создаёт справочники по умолчанию. Идемпотентно: значения заполняются только у
    вновь созданного справочника, поэтому правки и удаления пользователя не затираются."""
    with tenant_context(company.id), system_code_assignment():  # RLS: WITH CHECK по app.company_id
        for code, spec in DEFAULTS.items():
            handbook, created = Handbook.all_objects.get_or_create(
                company=company, code=code, defaults={"name": spec["name"], "group": spec["group"]}
            )
            if not created:
                continue
            HandbookValue.all_objects.bulk_create(
                HandbookValue(
                    company=company,
                    handbook=handbook,
                    name=item["name"],
                    code=item.get("code", ""),
                    order=i,
                    is_initial=item.get("is_initial", False),
                    is_final=item.get("is_final", False),
                )
                for i, item in enumerate(spec["values"], start=1)
            )


def is_status_handbook(handbook: Handbook) -> bool:
    return handbook.code in STATUS_HANDBOOK_CODES


def validate_value_change(handbook: Handbook, instance, data: dict) -> None:
    """Инвариант справочников статусов: ровно одно активное начальное значение.

    data - итоговые значения полей (после слияния с instance). Бросает ValidationError.
    """
    if not is_status_handbook(handbook):
        if data.get("is_initial"):
            raise ValidationError(
                {"is_initial": "Начальное значение задаётся только в справочниках статусов"}
            )
        return
    is_initial = data.get("is_initial", instance.is_initial if instance else False)
    is_active = data.get("is_active", instance.is_active if instance else True)
    if is_initial and not is_active:
        raise ValidationError({"is_active": "Начальный статус нельзя деактивировать"})
    others = HandbookValue.objects.filter(handbook=handbook, is_initial=True)
    if instance is not None:
        others = others.exclude(pk=instance.pk)
    if is_initial and others.exists():
        raise ValidationError(
            {"is_initial": "Начальный статус уже задан; используйте действие make-initial"}
        )
    if not is_initial and not others.exists():
        raise ValidationError({"is_initial": "В справочнике статусов должен быть начальный статус"})


@transaction.atomic
def make_initial(value: HandbookValue) -> HandbookValue:
    """Атомарно переносит признак начального значения на value."""
    if not value.is_active:
        raise ValidationError({"detail": "Неактивное значение нельзя сделать начальным"})
    current = HandbookValue.objects.filter(handbook=value.handbook, is_initial=True).first()
    if current is not None and current.pk != value.pk and current.is_system:
        # начальный системный статус (PLANNED) неизменен: другое значение начальным не сделать
        raise SystemValueProtected(MSG_MAKE_INITIAL.format(name=current.name))
    HandbookValue.objects.filter(handbook=value.handbook, is_initial=True).exclude(
        pk=value.pk
    ).update(is_initial=False)
    if not value.is_initial:
        value.is_initial = True
        value.save(update_fields=["is_initial"])
    return value


def unmapped_system_codes(company: Company, handbook_code: str = "trip_status") -> list[str]:
    """Системные коды справочника, которых нет ни у одного значения компании (по реестру).

    Компания считается «не сопоставленной», если список не пуст: справочника нет либо хотя бы
    один код реестра не назначен значению (статус переименован, дубликаты, иные признаки при
    миграции - см. check_system_status_codes). Нужна переключению на engine=new: пока список
    не пуст, переключать компанию нельзя (само переключение здесь не реализовано).
    """
    reserved = system_codes.reserved_codes(handbook_code)
    with tenant_context(company.id):
        present = set(
            HandbookValue.objects.filter(
                handbook__code=handbook_code, code__in=reserved
            ).values_list("code", flat=True)
        )
    return sorted(reserved - present)
