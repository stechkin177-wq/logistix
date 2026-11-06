import threading
from datetime import date
from decimal import Decimal as D

import pytest
from django.db import connection

from apps.core.tenancy import tenant_context
from apps.finance import invoices as inv_svc
from apps.finance import payments as pay
from apps.finance.errors import FinanceError
from apps.finance.models import Payment
from apps.finance.tests.helpers import add_line, cur, first_user, make_order, set_rate, vat

pytestmark = pytest.mark.django_db


def code(exc):
    return exc.value.detail.code


def issued(company, *, currency="KZT", amount="1000", percent="0", day=date(2026, 5, 1)):
    order = make_order(company, currency=currency)
    line = add_line(company, order, income=amount)
    user = first_user(company)
    with tenant_context(company.id):
        inv = inv_svc.create_draft(
            direction="out",
            party=order.client,
            order=order,
            currency=cur(company, currency),
            vat_rate=vat(company, percent),
            items=[{"title": "x", "amount_net": D(amount), "line": line}],
            user=user,
        )
        return inv_svc.issue(inv, user=user, issue_date=day)


def add(company, invoice, amount, day=date(2026, 5, 2), **kw):
    with tenant_context(company.id):
        return pay.add_payment(
            invoice, date=day, amount=D(str(amount)), method="bank", user=first_user(company), **kw
        )


def test_partial_payments_sum_to_paid(company):
    inv = issued(company)
    add(company, inv, 300)
    add(company, inv, 200)
    with tenant_context(company.id):
        assert inv_svc.paid_amount(inv) == D("500.00")
        assert inv_svc.balance(inv) == D("500.00")


def test_overpayment_rejected(company):
    inv = issued(company)
    add(company, inv, 900)
    with pytest.raises(FinanceError) as exc:
        add(company, inv, 100.01)
    assert code(exc) == "payment_exceeds_balance"
    add(company, inv, 100)  # ровно остаток допустим
    with tenant_context(company.id):
        assert inv_svc.balance(inv) == D("0.00")


def test_payment_on_draft_rejected(company):
    order = make_order(company)
    line = add_line(company, order, income=10)
    user = first_user(company)
    with tenant_context(company.id):
        draft = inv_svc.create_draft(
            direction="out",
            party=order.client,
            order=order,
            currency=cur(company),
            vat_rate=vat(company),
            items=[{"title": "x", "amount_net": D("10"), "line": line}],
            user=user,
        )
    with pytest.raises(FinanceError) as exc:
        add(company, draft, 1)
    assert code(exc) == "invoice_not_editable"


def test_payment_rate_snapshot_and_fx_difference(company):
    set_rate(company, "USD", 450, day=date(2026, 5, 1))
    set_rate(company, "USD", 470, day=date(2026, 5, 10))
    inv = issued(company, currency="USD", amount="1000")
    p = add(company, inv, 100, day=date(2026, 5, 10))
    assert p.rate_to_kzt == D("470")
    with tenant_context(company.id):
        assert pay.payment_fx_difference(p) == D("2000.00")


def test_fx_difference_for_incoming_is_negative(company):
    set_rate(company, "USD", 450, day=date(2026, 5, 1))
    set_rate(company, "USD", 470, day=date(2026, 5, 10))
    inv = issued(company, currency="USD", amount="1000")
    p = add(company, inv, 100, day=date(2026, 5, 10))
    with tenant_context(company.id):
        p.invoice.direction = "in"
        assert pay.payment_fx_difference(p) == D("-2000.00")


def test_delete_payment_restores_balance(company):
    inv = issued(company)
    p = add(company, inv, 400)
    with tenant_context(company.id):
        pay.delete_payment(p, user=first_user(company))
        assert inv_svc.balance(inv) == D("1000.00")
        assert not Payment.objects.filter(pk=p.pk).exists()


def test_missing_rate_on_payment_date(company):
    set_rate(company, "USD", 450, day=date(2026, 5, 1))
    inv = issued(company, currency="USD", amount="100")
    with pytest.raises(FinanceError) as exc:
        add(company, inv, 10, day=date(2026, 4, 1))  # до первого курса
    assert code(exc) == "rate_missing"


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_payments_one_wins(company):
    inv = issued(company)
    results = []

    def run():
        try:
            add(company, inv, 600)
            results.append("ok")
        except FinanceError as exc:
            results.append(exc.detail.code)
        finally:
            connection.close()

    threads = [threading.Thread(target=run) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["ok", "payment_exceeds_balance"]
