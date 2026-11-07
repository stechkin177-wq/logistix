"""Валютный слой: курсы между валютами, снимки в базовой валюте, смена базовой валюты.

Курс - сколько единиц валюты ``to`` в одной единице валюты ``from``. Записи ExchangeRate:
quote_currency пуст - курс валюты к тенге (так же, как прежние курсы), иначе прямая пара.
Поиск курса: тот же код валюты -> 1; прямая сохранённая пара (или обратная как 1/курс); иначе
через тенге: курс(from->KZT) / курс(to->KZT), где KZT->KZT = 1. Каждая нога берётся как
последняя запись не позже даты. Курс квантуется до 6 знаков, деньги - money.quantize_money.
Курс НИКОГДА не придумывается: нет данных - FinanceError("rate_missing").

Снимок (fx_snapshot) записывается один раз при признании; изменение курсов позже его не
затрагивает, пересчёта нет. Смена базовой валюты (change_base_currency) исторические записи не
пересчитывает.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from apps.core.audit import services as audit
from apps.core.handbooks.models import HandbookValue
from apps.core.tenancy import tenant_context
from apps.forwarding.finance_lines.models import company_today

from .errors import FinanceError
from .models import (
    BASE_CURRENCY_CODES,
    CompanyFinancialSettings,
    ExchangeRate,
)
from .money import quantize_money

KZT = "KZT"
RATE_QUANT = Decimal("0.000001")
ONE = Decimal("1")


def quantize_rate(value: Decimal) -> Decimal:
    return Decimal(value).quantize(RATE_QUANT, rounding=ROUND_HALF_UP)


def _latest(currency, quote, on_date: date):
    """(курс, дата) последней записи не позже даты или None. quote=None - к тенге."""
    qs = ExchangeRate.objects.filter(currency=currency, date__lte=on_date)
    qs = (
        qs.filter(quote_currency__isnull=True) if quote is None else qs.filter(quote_currency=quote)
    )
    row = qs.order_by("-date", "-id").values_list("rate", "date").first()
    return row


def _missing(from_currency, to_currency, on_date: date) -> FinanceError:
    return FinanceError(
        "rate_missing",
        f"Нет курса {from_currency.code} к {to_currency.code} на {on_date.isoformat()}",
        status_code=409,
    )


def _kzt_leg(currency, on_date: date):
    """(курс к тенге, дата) ноги; для самого тенге (1, дата расчёта)."""
    if currency.code == KZT:
        return ONE, on_date
    return _latest(currency, None, on_date)


def resolve_rate(company, from_currency, to_currency, on_date: date) -> tuple[Decimal, str, date]:
    """(курс, источник, дата курса); источник: same / direct / via_kzt."""
    if from_currency.pk == to_currency.pk:
        return ONE, "same", on_date
    with tenant_context(company.id):
        direct = _latest(from_currency, to_currency, on_date)
        inverse = _latest(to_currency, from_currency, on_date)
        # из прямой и обратной берётся более свежая запись; при равенстве дат - прямая
        if direct is not None and (inverse is None or direct[1] >= inverse[1]):
            return quantize_rate(direct[0]), "direct", direct[1]
        if inverse is not None:
            return quantize_rate(ONE / inverse[0]), "direct", inverse[1]
        leg_from = _kzt_leg(from_currency, on_date)
        leg_to = _kzt_leg(to_currency, on_date)
    if leg_from is None or leg_to is None:
        raise _missing(from_currency, to_currency, on_date)
    rate = quantize_rate(leg_from[0] / leg_to[0])
    if rate <= 0:
        raise _missing(from_currency, to_currency, on_date)
    return rate, "via_kzt", min(leg_from[1], leg_to[1])


def get_settings(company) -> CompanyFinancialSettings:
    from .initial_settings import ensure_company_financial_settings

    with tenant_context(company.id):
        return ensure_company_financial_settings(company)


def fx_snapshot(company, amount, currency, on_date: date, settings=None) -> dict:
    """Поля снимка Income/Expense: сумма в базовой валюте компании по курсу на дату."""
    settings = settings or get_settings(company)
    base = settings.base_currency
    if base is None:
        raise FinanceError(
            "base_currency_missing", "Не задана базовая валюта компании", status_code=409
        )
    rate, source, rate_date = resolve_rate(company, currency, base, on_date)
    return {
        "fx_base_currency": base,
        "fx_rate": rate,
        "fx_rate_date": rate_date,
        "fx_rate_source": source,
        "base_amount": quantize_money(Decimal(amount) * rate),
    }


def apply_snapshot(obj, on_date: date, settings=None) -> dict:
    """Присваивает снимок объекту Income/Expense по его amount и currency (без сохранения)."""
    snap = fx_snapshot(obj.company, obj.amount, obj.currency, on_date, settings)
    for key, value in snap.items():
        setattr(obj, key, value)
    return snap


def legacy_missing_snapshot(company, currency) -> dict:
    """Снимок для истории без курса: base_amount пуст, исходная сумма остаётся в записи."""
    settings = get_settings(company)
    return {
        "fx_base_currency": settings.base_currency,
        "fx_rate": None,
        "fx_rate_date": None,
        "fx_rate_source": "legacy_missing",
        "base_amount": None,
    }


def used_currencies(company) -> list:
    """Валюты, которые компания реально использует (заказы, рейсы, счета, доходы, расходы)."""
    from apps.forwarding.models import Order, Trip

    from .models import Expense, Income, Invoice

    ids = set()
    with tenant_context(company.id):
        for model in (Order, Trip, Invoice, Income, Expense):
            ids |= set(
                model.all_objects.filter(company=company).values_list("currency_id", flat=True)
            )
        return list(HandbookValue.objects.filter(pk__in=ids).order_by("code", "id"))


@transaction.atomic
def change_base_currency(company, new_currency, user, reason: str) -> CompanyFinancialSettings:
    """Меняет базовую валюту компании. История не пересчитывается; нужен курс на сегодня."""
    reason = (reason or "").strip()
    if not reason:
        raise FinanceError("reason_required", "Укажите причину смены базовой валюты")
    with tenant_context(company.id):
        valid = (
            new_currency.company_id == company.id
            and new_currency.handbook.code == "currency"
            and new_currency.code in BASE_CURRENCY_CODES
        )
    if not valid:
        raise FinanceError(
            "base_currency_invalid",
            "Базовая валюта: KZT, RUB, USD или EUR из справочника валют компании",
        )
    get_settings(company)
    with tenant_context(company.id):
        settings = CompanyFinancialSettings.objects.select_for_update().get(company=company)
        if settings.base_currency_id == new_currency.pk:
            return settings
        today = company_today(company.id)
        missing = []
        for used in used_currencies(company):
            try:
                resolve_rate(company, used, new_currency, today)
            except FinanceError as exc:
                if getattr(exc.detail, "code", None) != "rate_missing":
                    raise
                missing.append(f"{used.code}->{new_currency.code}")
        if missing:
            raise FinanceError(
                "rate_missing",
                f"Нет курсов на {today.isoformat()} для пар: " + ", ".join(missing),
                status_code=409,
            )
        old_id = settings.base_currency_id
        settings.base_currency = new_currency
        settings.updated_by = user if user is not None and getattr(user, "pk", None) else None
        settings.save(update_fields=["base_currency", "updated_by", "updated_at"])
        audit.log(
            "update",
            settings,
            user,
            {"base_currency_id": [old_id, new_currency.pk], "reason": reason},
        )
        return settings
