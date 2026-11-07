"""Помощники тестов П2 (доходы, расходы, связи со счетами)."""

from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal as D

import time_machine

from apps.core.handbooks.models import HandbookValue
from apps.core.tenancy import tenant_context
from apps.finance.models import CompanyFinancialSettings, ExchangeRate, Income
from apps.finance.tests.helpers import cur, first_user, make_carrier
from apps.forwarding.models import Order
from apps.forwarding.tests.test_trips import make_cargos, svc_create
from apps.forwarding.trips.services import change_trip_status

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=dt_tz.utc)


def enable_new(company, **extra):
    CompanyFinancialSettings.all_objects.filter(company=company).update(
        engine="new", cutover_date=date(2026, 1, 1), **extra
    )


def set_engine(company, engine, **extra):
    CompanyFinancialSettings.all_objects.filter(company=company).update(engine=engine, **extra)


def status(company, code):
    with tenant_context(company.id):
        return HandbookValue.objects.get(handbook__code="trip_status", code=code)


def move(company, trip, code, when=None, **kw):
    """Переводит рейс в статус по коду (можно в заданный момент времени)."""
    user = first_user(company)
    kw.setdefault("can_revert", True)
    kw.setdefault("reason", "тест")
    with tenant_context(company.id):
        trip = type(trip).objects.get(pk=trip.pk)
        if when is None:
            return change_trip_status(trip, status(company, code), user, **kw)
        with time_machine.travel(when, tick=False):
            return change_trip_status(trip, status(company, code), user, **kw)


def new_trip(company, order_cargo_ids, price="0", carrier=True, currency=None):
    data = {"carrier_price": D(price)}
    if currency:
        data["currency"] = cur(company, currency)
    return svc_create(
        company, order_cargo_ids, carrier=make_carrier(company) if carrier else None, data=data
    )


def order_with_cargos(company, n=1, **extra):
    return make_cargos(company, n, **extra)


def freight(order):
    with tenant_context(order.company_id):
        return list(Income.objects.filter(order=order, kind="freight").order_by("id"))


def reload(obj):
    return type(obj).all_objects.get(pk=obj.pk)


def rate(company, code, value, day=date(2026, 1, 1), quote=None):
    with tenant_context(company.id):
        return ExchangeRate.objects.create(
            company=company,
            currency=cur(company, code),
            quote_currency=cur(company, quote) if quote else None,
            date=day,
            rate=D(str(value)),
        )


def order_obj(order):
    return Order.all_objects.get(pk=order.pk)
