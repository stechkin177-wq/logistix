from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.core import trash
from apps.core.rls import tables_missing_rls
from apps.core.tenancy import tenant_context
from apps.finance.models import Invoice, InvoiceItem, Payment
from apps.finance.tests.helpers import (
    add_line,
    cur,
    make_carrier,
    make_client,
    make_order,
    vat,
)

pytestmark = pytest.mark.django_db


def inv(company, **extra):
    base = {
        "company": company,
        "direction": "out",
        "client": make_client(company),
        "currency": cur(company),
        "vat_rate": vat(company),
    }
    base.update(extra)
    with tenant_context(company.id):
        return Invoice.objects.create(**base)


def test_out_invoice_requires_client_only(company):
    with pytest.raises(IntegrityError), transaction.atomic():
        inv(company, client=None)
    with pytest.raises(IntegrityError), transaction.atomic():
        inv(company, carrier=make_carrier(company))


def test_in_invoice_requires_carrier_only(company):
    with pytest.raises(IntegrityError), transaction.atomic():
        inv(company, direction="in", client=None, carrier=None)
    with pytest.raises(IntegrityError), transaction.atomic():
        inv(company, direction="in", carrier=make_carrier(company))  # client тоже задан
    ok = inv(company, direction="in", client=None, carrier=make_carrier(company))
    assert ok.status == "draft"


def test_payment_amount_positive(company):
    invoice = inv(company)
    with pytest.raises(IntegrityError), transaction.atomic(), tenant_context(company.id):
        Payment.objects.create(
            company=company, invoice=invoice, date=date(2026, 5, 1), amount=Decimal("0"),
            rate_to_kzt=Decimal("1"), method="bank",
        )


def test_item_amount_non_negative(company):
    invoice = inv(company)
    order = make_order(company)
    line = add_line(company, order, income=100)
    with pytest.raises(IntegrityError), transaction.atomic(), tenant_context(company.id):
        InvoiceItem.objects.create(
            company=company, invoice=invoice, title="x", amount_net=Decimal("-1"), line=line
        )


def test_number_unique_per_direction_nonempty(company):
    inv(company)
    inv(company)  # два черновика с пустым номером допустимы
    inv(company, number="СЧ-1")
    with pytest.raises(IntegrityError), transaction.atomic():
        inv(company, number="СЧ-1")
    # то же значение в другом направлении не конфликтует
    inv(company, direction="in", client=None, carrier=make_carrier(company), number="СЧ-1")


def test_trash_registered():
    reg = trash.registered()
    assert "invoices" in reg and "payments" in reg


def test_rls_tables_covered(company):
    assert tables_missing_rls() == []
