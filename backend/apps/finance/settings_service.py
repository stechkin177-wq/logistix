"""Изменение финансовых настроек компании (сервис; API и интерфейс - позже).

Разрешены: allow_backdating, default_vat_rate, fiscal_year_start_month, expense_creation_mode,
sync_carrier_price, completed_status. Базовая валюта меняется только через fx.change_base_currency;
engine, cutover_date, income_recognition и accounting_method этим сервисом менять нельзя
(переключение движка - отдельная команда). Каждое изменение пишется в аудит (старое/новое).
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from apps.core.audit import services as audit
from apps.core.handbooks.models import HandbookValue
from apps.core.tenancy import tenant_context

from .errors import FinanceError
from .fx import get_settings
from .models import CompanyFinancialSettings

ALLOWED = {
    "allow_backdating",
    "default_vat_rate",
    "fiscal_year_start_month",
    "expense_creation_mode",
    "sync_carrier_price",
    "completed_status",
}
FORBIDDEN = {"engine", "cutover_date", "income_recognition", "accounting_method"}
EXPENSE_MODES = {c for c, _ in CompanyFinancialSettings.EXPENSE_CREATION_MODES}


def _value(raw, handbook: str, field: str, *, active: bool = False):
    """Значение справочника своей компании (объект или id); None - сброс."""
    if raw is None:
        return None
    pk = raw.pk if isinstance(raw, HandbookValue) else raw
    if isinstance(pk, bool) or not isinstance(pk, int):
        raise FinanceError("setting_invalid", f"{field}: нужен идентификатор значения справочника")
    qs = HandbookValue.objects.filter(pk=pk, handbook__code=handbook)  # только своя компания
    if active:
        qs = qs.filter(is_active=True)
    value = qs.first()
    if value is None:
        raise FinanceError(
            "setting_invalid", f"{field}: нет такого активного значения справочника {handbook}"
        )
    return value


@transaction.atomic
def update_settings(company, changes: dict, user) -> CompanyFinancialSettings:
    cid = company.pk
    changes = dict(changes)
    if "base_currency" in changes:
        raise FinanceError(
            "setting_forbidden", "Базовая валюта меняется только через смену базовой валюты"
        )
    forbidden = sorted(set(changes) & FORBIDDEN)
    if forbidden:
        raise FinanceError(
            "setting_forbidden", "Эти настройки нельзя менять здесь: " + ", ".join(forbidden)
        )
    unknown = sorted(set(changes) - ALLOWED)
    if unknown:
        raise FinanceError("setting_unknown", "Неизвестные настройки: " + ", ".join(unknown))
    with tenant_context(cid):
        get_settings(company)
        settings = CompanyFinancialSettings.objects.select_for_update().get(company_id=cid)
        before = audit.snapshot(settings)
        for field, raw in changes.items():
            if field in ("allow_backdating", "sync_carrier_price"):
                if not isinstance(raw, bool):
                    raise FinanceError("setting_invalid", f"{field}: нужно true или false")
                setattr(settings, field, raw)
            elif field == "fiscal_year_start_month":
                if isinstance(raw, bool) or not isinstance(raw, int) or not 1 <= raw <= 12:
                    raise FinanceError("setting_invalid", f"{field}: месяц от 1 до 12")
                settings.fiscal_year_start_month = raw
            elif field == "expense_creation_mode":
                if raw not in EXPENSE_MODES:
                    raise FinanceError(
                        "setting_invalid", f"{field}: допустимо manual или on_assign"
                    )
                settings.expense_creation_mode = raw
            elif field == "default_vat_rate":
                settings.default_vat_rate = _value(raw, "vat_rate", field)
            else:  # completed_status
                value = _value(raw, "trip_status", field, active=True)
                if value is None and settings.engine == "new":
                    raise FinanceError(
                        "setting_invalid", "completed_status нельзя очистить при engine=new"
                    )
                settings.completed_status = value
        try:
            settings.clean()
        except DjangoValidationError as exc:
            raise FinanceError(
                "setting_invalid", "; ".join(sum(exc.message_dict.values(), []))
            ) from None
        settings.updated_by = user if getattr(user, "pk", None) else None
        settings.save()
        changed = audit.diff(before, audit.snapshot(settings))
        changed.pop("updated_by_id", None)
        if changed:
            audit.log("update", settings, user, changed)
        return settings
