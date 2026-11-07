"""Курсы валют к тенге."""

from datetime import date
from decimal import Decimal

from apps.forwarding.orders.services import BASE_CURRENCY_CODE

from .errors import FinanceError
from .models import ExchangeRate

ONE = Decimal("1")


def rate_on(currency, on: date) -> Decimal:
    """Курс валюты (значение справочника currency) к тенге на дату: последняя запись не позже
    даты. Для тенге всегда 1. Нет записи - FinanceError rate_missing (операция невозможна)."""
    if currency.code == BASE_CURRENCY_CODE:
        return ONE
    rate = (
        ExchangeRate.objects.filter(currency=currency, quote_currency__isnull=True, date__lte=on)
        .order_by("-date")
        .values_list("rate", flat=True)
        .first()
    )
    if rate is None:
        raise FinanceError("rate_missing", f"Нет курса {currency.code} к тенге на {on.isoformat()}")
    return rate
