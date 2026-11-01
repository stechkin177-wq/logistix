from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.core.handbooks.models import HandbookValue
from apps.core.tenancy import tenant_context
from apps.finance.errors import FinanceError
from apps.finance.models import ExchangeRate
from apps.finance.rates import rate_on


def cur(company, code):
    with tenant_context(company.id):
        return HandbookValue.objects.get(handbook__code="currency", code=code)


def add_rate(company, code, day, rate):
    with tenant_context(company.id):
        return ExchangeRate.objects.create(
            company=company, currency=cur(company, code), date=day, rate=Decimal(rate)
        )


def test_kzt_is_one(company):
    with tenant_context(company.id):
        assert rate_on(cur(company, "KZT"), date(2026, 5, 1)) == Decimal("1")


def test_picks_latest_not_after_date(company):
    add_rate(company, "USD", date(2026, 5, 1), "450.5")
    add_rate(company, "USD", date(2026, 5, 10), "470")
    usd = cur(company, "USD")
    with tenant_context(company.id):
        assert rate_on(usd, date(2026, 5, 5)) == Decimal("450.5")
        assert rate_on(usd, date(2026, 5, 10)) == Decimal("470")
        assert rate_on(usd, date(2026, 6, 1)) == Decimal("470")


def test_missing_rate_raises(company):
    usd = cur(company, "USD")
    with tenant_context(company.id):
        with pytest.raises(FinanceError) as exc:
            rate_on(usd, date(2026, 5, 1))
    assert exc.value.detail.code == "rate_missing"
    add_rate(company, "USD", date(2026, 5, 10), "470")
    with tenant_context(company.id):
        with pytest.raises(FinanceError):
            rate_on(usd, date(2026, 5, 9))


def test_rate_must_be_positive(company):
    with pytest.raises(IntegrityError), transaction.atomic():
        add_rate(company, "USD", date(2026, 5, 1), "0")


def test_unique_per_day(company):
    add_rate(company, "USD", date(2026, 5, 1), "450")
    with pytest.raises(IntegrityError), transaction.atomic():
        add_rate(company, "USD", date(2026, 5, 1), "451")
