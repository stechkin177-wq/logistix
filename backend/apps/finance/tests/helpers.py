"""Общие хелперы тестов финансов (используют фабрики тестов экспедирования)."""

from datetime import date
from decimal import Decimal

from apps.core.handbooks.models import HandbookValue
from apps.core.models import Membership
from apps.core.tenancy import tenant_context
from apps.finance.models import ExchangeRate
from apps.forwarding.finance_lines.models import OrderService
from apps.forwarding.models import Carrier, Client
from apps.forwarding.tests.test_orders import make_order as _make_order


def cur(company, code="KZT"):
    with tenant_context(company.id):
        return HandbookValue.objects.get(handbook__code="currency", code=code)


def vat(company, code="16"):
    with tenant_context(company.id):
        return HandbookValue.objects.get(handbook__code="vat_rate", code=code)


def set_rate(company, code, rate, day=date(2026, 1, 1)):
    with tenant_context(company.id):
        return ExchangeRate.objects.create(
            company=company, currency=cur(company, code), date=day, rate=Decimal(str(rate))
        )


def make_client(company, name="ТОО Клиент", **extra):
    with tenant_context(company.id):
        return Client.objects.create(name=name, **extra)


def make_carrier(company, name="Перевозчик", **extra):
    with tenant_context(company.id):
        return Carrier.objects.create(name=name, **extra)


def make_order(company, client=None, currency="KZT", **extra):
    client = client or make_client(company)
    return _make_order(company, client, currency=cur(company, currency), client_rate=0, **extra)


def add_line(company, order, income=0, expense=0, title="Услуга", day=None, category=""):
    with tenant_context(company.id):
        return OrderService.objects.create(
            order=order,
            title=title,
            income=Decimal(str(income)),
            expense=Decimal(str(expense)),
            category=category,
            **({"date": day} if day else {}),
        )


def first_user(company):
    with tenant_context(company.id):
        return Membership.objects.filter(company=company).first().user
