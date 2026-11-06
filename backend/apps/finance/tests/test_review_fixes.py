"""Регрессии по итоговому ревью ветки 3A: корзина, гонки, перепроверка, переполнение."""

import threading
from decimal import Decimal as D

import pytest
from django.db import connection

from apps.core import trash
from apps.core.handbooks.models import HandbookValue
from apps.core.tenancy import tenant_context
from apps.finance import invoices as svc
from apps.finance import trip_expense as te
from apps.finance.errors import FinanceError
from apps.finance.models import Invoice, InvoiceItem, Payment
from apps.finance.tests.helpers import (
    add_line,
    cur,
    first_user,
    issue_invoice,
    make_carrier,
    make_order,
    pay_invoice,
    vat,
)
from apps.forwarding.finance_lines.models import OrderService
from apps.forwarding.tests.test_trips import make_cargos, svc_create

pytestmark = pytest.mark.django_db


def code(exc):
    return exc.value.detail.code


def draft_out(company, order, lines, percent="0"):
    with tenant_context(company.id):
        return svc.create_draft(
            direction="out",
            party=order.client,
            order=order,
            currency=order.currency,
            vat_rate=vat(company, percent),
            items=[{"title": "x", "amount_net": D(str(a)), "line": ln} for ln, a in lines],
            user=first_user(company),
        )


# --- #1 корзина не обходит инварианты ------------------------------------------------------


def test_restore_payment_cannot_overpay(admin_client, company):
    inv = issue_invoice(company, amount="100")
    first = pay_invoice(company, inv, 100)
    assert admin_client.delete(f"/api/finance/payments/{first.pk}/").status_code == 204
    pay_invoice(company, inv, 100)
    r = admin_client.post(f"/api/trash/payments/{first.pk}/restore/")
    assert r.status_code == 409, r.content
    with tenant_context(company.id):
        assert Payment.objects.filter(invoice=inv).count() == 1


def test_restore_payment_on_cancelled_invoice_rejected(admin_client, company):
    inv = issue_invoice(company, amount="100")
    p = pay_invoice(company, inv, 40)
    assert admin_client.delete(f"/api/finance/payments/{p.pk}/").status_code == 204
    with tenant_context(company.id):
        svc.cancel(inv, user=first_user(company))
    assert admin_client.post(f"/api/trash/payments/{p.pk}/restore/").status_code == 409


def test_restore_payment_ok_when_balance_allows(admin_client, company):
    inv = issue_invoice(company, amount="100")
    p = pay_invoice(company, inv, 40)
    assert admin_client.delete(f"/api/finance/payments/{p.pk}/").status_code == 204
    assert admin_client.post(f"/api/trash/payments/{p.pk}/restore/").status_code == 200


def test_invoices_are_not_in_trash():
    assert "invoices" not in trash.registered()


# --- #6 удалённые и отменённые счета не держат строки --------------------------------------


def test_deleted_draft_frees_its_line(admin_client, company):
    order = make_order(company)
    line = add_line(company, order, income=100)
    inv = draft_out(company, order, [(line, 100)])
    with tenant_context(company.id):
        svc.delete_draft(inv)
        assert not Invoice.all_objects.filter(pk=inv.pk).exists()
        assert not InvoiceItem.objects.filter(line=line).exists()
    assert admin_client.delete(f"/api/order-lines/{line.pk}/").status_code == 204


def test_cancelled_invoice_frees_its_line_but_keeps_item_snapshot(admin_client, company):
    inv = issue_invoice(company, amount="100")
    with tenant_context(company.id):
        line_id = inv.items.get().line_id
        svc.cancel(inv, user=first_user(company))
        item = InvoiceItem.objects.get(invoice=inv)
        assert item.line_id is None and item.amount_net == D("100.00") and item.title
    assert admin_client.delete(f"/api/order-lines/{line_id}/").status_code == 204


# --- #3 выставление перепроверяет заголовок и строки ------------------------------------------


def test_issue_rejects_draft_whose_order_was_deleted_or_cancelled(company):
    for how in ("deleted", "cancelled"):
        order = make_order(company)
        line = add_line(company, order, income=100)
        inv = draft_out(company, order, [(line, 100)])
        with tenant_context(company.id):
            if how == "deleted":
                order.delete()
            else:
                order.status = HandbookValue.objects.get(
                    handbook__code="order_status", code="cancelled"
                )
                order.save()
            with pytest.raises(FinanceError) as exc:
                svc.issue(inv, user=first_user(company))
        assert code(exc) == "line_unavailable"
        with tenant_context(company.id):
            assert Invoice.objects.get(pk=inv.pk).status == "draft"


def test_issue_rejects_draft_whose_order_changed_client(company):
    order = make_order(company)
    line = add_line(company, order, income=100)
    inv = draft_out(company, order, [(line, 100)])
    from apps.finance.tests.helpers import make_client

    other = make_client(company, "Другой")
    with tenant_context(company.id):
        order.client = other
        order.save()
        with pytest.raises(FinanceError) as exc:
            svc.issue(inv, user=first_user(company))
    assert code(exc) == "party_mismatch"


# --- #4 переполнение сумм → 400, не 500 ---------------------------------------------------------


def test_out_invoice_gross_overflow_is_finance_error(company):
    order = make_order(company)
    line = add_line(company, order, income="999999999999.99")
    with pytest.raises(FinanceError) as exc:
        draft_out(company, order, [(line, "999999999999.99")], percent="12")
    assert code(exc) == "amount_too_large"


def test_in_invoice_sum_overflow_is_finance_error(company):
    order = make_order(company)
    carrier = make_carrier(company)
    l1 = add_line(company, order, expense="600000000000")
    l2 = add_line(company, order, expense="600000000000")
    with tenant_context(company.id), pytest.raises(FinanceError) as exc:
        svc.create_draft(
            direction="in",
            party=carrier,
            order=order,
            currency=order.currency,
            vat_rate=vat(company, "none"),
            items=[
                {"title": "a", "amount_net": D("600000000000"), "line": l1},
                {"title": "b", "amount_net": D("600000000000"), "line": l2},
            ],
            user=first_user(company),
        )
    assert code(exc) == "amount_too_large"


# --- #5 валюта строк рейсового счёта ----------------------------------------------------------


def test_trip_invoice_rejects_line_of_order_in_other_currency(company):
    order, ids = make_cargos(company, 1, currency=cur(company, "USD"))
    carrier = make_carrier(company)
    trip = svc_create(company, ids, carrier=carrier, data={"price": D("100")})  # рейс в тенге
    line = add_line(company, order, expense=50)
    with tenant_context(company.id), pytest.raises(FinanceError) as exc:
        svc.create_draft(
            direction="in",
            party=carrier,
            trip=trip,
            currency=cur(company),
            vat_rate=vat(company, "none"),
            items=[{"title": "x", "amount_net": D("50"), "line": line}],
            user=first_user(company),
        )
    assert code(exc) == "currency_mismatch"


# --- #2, #7 гонки ------------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_issue_cannot_exceed_order_income(company):
    order = make_order(company)
    l1 = add_line(company, order, income=100)
    l2 = add_line(company, order, income=0)
    with tenant_context(company.id):
        OrderService.objects.filter(pk=l2.pk).update(income=D("50"))
    first = draft_out(company, order, [(l1, 60)])
    second = draft_out(company, order, [(l2, 50)])  # 60 + 50 > 150? доход заказа = 100 + 50 = 150
    # доход заказа 150: два счёта по 100 (60+40) и 90 не помещаются вместе
    with tenant_context(company.id):
        svc.update_draft(first, items=[{"title": "x", "amount_net": D("100"), "line": l1}])
        svc.update_draft(second, items=[{"title": "y", "amount_net": D("100"), "line": l2}])
    results = []

    def run(inv):
        try:
            with tenant_context(company.id):
                svc.issue(inv, user=first_user(company))
            results.append("ok")
        except FinanceError as exc:
            results.append(exc.detail.code)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(i,)) for i in (first, second)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["invoice_exceeds_order_income", "ok"]


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_trip_expense_creates_lines_once(company):
    order, ids = make_cargos(company, 1)
    carrier = make_carrier(company)
    trip = svc_create(company, ids, carrier=carrier, data={"price": D("100")})
    results = []

    def run():
        try:
            with tenant_context(company.id):
                te.create_trip_expense(
                    trip, [{"order_id": order.pk, "amount": D("100")}], user=first_user(company)
                )
            results.append("ok")
        except FinanceError as exc:
            results.append(exc.detail.code)
        finally:
            connection.close()

    threads = [threading.Thread(target=run) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["expense_exists", "ok"]
    with tenant_context(company.id):
        assert OrderService.objects.filter(order=order, category="Перевозка").count() == 1
