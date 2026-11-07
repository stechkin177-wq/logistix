"""Связи счетов с доходами и расходами (1.4.6)."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.core.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.finance import expenses as ex
from apps.finance import income as inc
from apps.finance import invoice_links as links
from apps.finance import invoices as inv_svc
from apps.finance.errors import FinanceError
from apps.finance.models import (
    Expense,
    ExpenseInvoiceAllocation,
    Income,
    Invoice,
    InvoiceItem,
    Payment,
)
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
from apps.finance.tests.p2_helpers import enable_new, new_trip, order_with_cargos, set_engine
from apps.finance.tests.test_expenses import manual
from apps.forwarding.models import Trip

pytestmark = pytest.mark.django_db


def code(exc):
    return exc.value.detail.code


def out_draft(company, order, amounts, currency="KZT"):
    """Черновик исходящего счёта по новым строкам заказа."""
    user = first_user(company)
    with tenant_context(company.id):
        items = []
        for amount in amounts:
            line = add_line(company, order, income=amount)
            items.append({"title": "Позиция", "amount_net": D(str(amount)), "line": line})
        return inv_svc.create_draft(
            direction="out",
            party=order.client,
            order=order,
            currency=cur(company, currency),
            vat_rate=vat(company, "0"),
            due_date=None,
            items=items,
            user=user,
        )


def items_of(invoice):
    with tenant_context(invoice.company_id):
        return list(InvoiceItem.objects.filter(invoice=invoice).order_by("id"))


def new_order(company, rate_="1000.00"):
    order, _ = order_with_cargos(company, 1, client_rate=D(rate_))
    return order


def planned_income(company, order):
    with tenant_context(company.id):
        return Income.objects.get(order=order, kind="freight")


def in_invoice(company, carrier, amount, trip=None, order=None):
    return issue_invoice(
        company,
        order=order or make_order(company),
        direction="in",
        carrier=carrier,
        amount=amount,
        trip=trip,
    )


def link_obj(expense_id):
    return ExpenseInvoiceAllocation.objects.filter(expense_id=expense_id).order_by("id")


def audit_rows(company, obj):
    with tenant_context(company.id):
        return list(
            AuditLog.objects.filter(
                object_type=obj._meta.label_lower, object_id=str(obj.pk)
            ).order_by("id")
        )


# --- доход заказа для проверки счетов ---


def test_order_income_total_by_engine(company):
    order = new_order(company, "1000.00")
    add_line(company, order, income=500)  # прежний учёт: 1000 (база) + 500
    assert links.order_income_total(order) == D("1500.00")  # legacy
    enable_new(company)
    with tenant_context(company.id):
        inc.sync_planned_freight(order)
        inc.plan_service(order, "Услуга", "", "200", first_user(company))
        voided = inc.plan_service(order, "Отмена", "", "9999", first_user(company))
        inc.void_income(voided, "ошибка", first_user(company))
    assert links.order_income_total(order) == D("1200.00")  # 1000 + 200, void не считается


def test_invoice_total_check_uses_incomes_only_for_new_engine(company):
    order = new_order(company, "1000.00")
    draft = out_draft(company, order, [1000, 500])  # Σ 1500 = прежний доход заказа
    user = first_user(company)
    with tenant_context(company.id):
        assert inv_svc.issue(draft, user=user, issue_date=date(2026, 7, 1)).status == "issued"
    other = new_order(company, "1000.00")
    draft2 = out_draft(company, other, [1000, 500])
    enable_new(company)
    with tenant_context(company.id):
        inc.sync_planned_freight(other)
        with pytest.raises(FinanceError) as exc:
            inv_svc.issue(draft2, user=user, issue_date=date(2026, 7, 1))
    assert code(exc) == "invoice_exceeds_order_income"
    set_engine(company, "shadow")  # shadow: прежний расчёт
    with tenant_context(company.id):
        assert inv_svc.issue(draft2, user=user, issue_date=date(2026, 7, 1)).status == "issued"


# --- исходящие позиции -> Income ---


def test_link_item_to_income_advance_and_rules(company):
    enable_new(company)
    order = new_order(company, "1000.00")
    income = planned_income(company, order)
    draft = out_draft(company, order, [1000])
    item = items_of(draft)[0]
    linked = links.link_item_to_income(item, income, user=first_user(company))
    assert linked.income_id == income.pk and linked.line_id == item.line_id  # line не тронут
    assert income.status == "planned"  # аванс по planned допустим
    assert links.link_item_to_income(item, income).pk == item.pk  # идемпотентно
    # тот же Income во втором активном счёте - нельзя
    draft2 = out_draft(company, order, [100])
    with pytest.raises(FinanceError) as exc:
        links.link_item_to_income(items_of(draft2)[0], income)
    assert code(exc) == "item_already_invoiced"
    # void, другой заказ, другая валюта, входящий счёт
    other_order = new_order(company)
    with pytest.raises(FinanceError) as exc:
        links.link_item_to_income(items_of(draft2)[0], planned_income(company, other_order))
    assert code(exc) == "party_mismatch"
    voided = inc.plan_service(order, "x", "", "1", first_user(company))
    inc.void_income(voided, "r", first_user(company))
    with pytest.raises(FinanceError) as exc:
        links.link_item_to_income(items_of(draft2)[0], Income.all_objects.get(pk=voided.pk))
    assert code(exc) == "income_void"
    usd = inc.plan_service(order, "usd", "", "1", first_user(company))
    Income.all_objects.filter(pk=usd.pk).update(currency=cur(company, "USD"))
    with pytest.raises(FinanceError) as exc:
        links.link_item_to_income(items_of(draft2)[0], Income.all_objects.get(pk=usd.pk))
    assert code(exc) == "currency_mismatch"
    inv_in = in_invoice(company, make_carrier(company), "50")
    with pytest.raises(FinanceError) as exc:
        links.link_item_to_income(items_of(inv_in)[0], income)
    assert code(exc) == "invoice_direction"


def test_cancel_outgoing_invoice_releases_income_and_keeps_history(company):
    enable_new(company)
    order = new_order(company, "1000.00")
    income = planned_income(company, order)
    user = first_user(company)
    invoice = issue_invoice(company, order=order, amount="1000", day=date(2026, 7, 1))
    item = items_of(invoice)[0]
    links.link_item_to_income(item, income, user=user)
    title, net = item.title, item.amount_net
    pay_invoice(company, invoice, "300", day=date(2026, 7, 2))
    with tenant_context(company.id):
        pay_before = list(Payment.objects.values_list("id", "amount"))
    from apps.finance.payments import delete_payment

    with tenant_context(company.id):
        delete_payment(Payment.objects.get(), user=user)
        cancelled = inv_svc.cancel(invoice, user=user)
    assert cancelled.status == "cancelled"
    after = items_of(invoice)[0]
    assert after.income_id is None and after.line_id is None
    assert (after.title, after.amount_net) == (title, net)  # снимок позиции цел
    last = audit_rows(company, invoice)[-1].changes
    assert last["released_incomes"] == [{"item": item.pk, "income": income.pk}]
    assert pay_before
    # доход свободен: его можно включить в новый счёт
    draft = out_draft(company, order, [100])
    assert (
        links.link_item_to_income(
            items_of(draft)[0], Income.all_objects.get(pk=income.pk)
        ).income_id
        == income.pk
    )


def test_partial_payment_unaffected_by_links(company):
    enable_new(company)
    order = new_order(company, "1000.00")
    invoice = issue_invoice(company, order=order, amount="1000", day=date(2026, 7, 1))
    links.link_item_to_income(items_of(invoice)[0], planned_income(company, order))
    pay_invoice(company, invoice, "400", day=date(2026, 7, 2))
    with tenant_context(company.id):
        fresh = Invoice.objects.get(pk=invoice.pk)
        assert inv_svc.balance(fresh) == D("600.00")
        assert Income.objects.filter(order=order).count() == 1  # платёж доход не создаёт


# --- входящие позиции -> Expense ---


def carrier_setup(company, price="100.00"):
    order, ids = order_with_cargos(company, 1)
    trip = new_trip(company, ids, price=price)
    expense = ex.create_carrier_expense(trip, user=first_user(company))
    return order, trip, expense


def test_incoming_invoice_covers_several_expenses_and_expense_several_invoices(company):
    user = first_user(company)
    order, trip, e1 = carrier_setup(company, "100.00")
    e2 = manual(company, amount=D("40"))
    invoice = in_invoice(company, trip.carrier, "140", trip=None, order=order)
    item = items_of(invoice)[0]
    # один счёт - два расхода
    a = links.link_expense_to_item(e1, item, "100.00", user=user)
    # расход другого перевозчика/рейса не мешает: у ручного расхода перевозчика нет
    b = links.link_expense_to_item(e2, item, "40", user=user)
    assert (a.amount, b.amount) == (D("100.00"), D("40.00"))
    assert Expense.all_objects.get(pk=e1.pk).needs_review is False
    assert Expense.all_objects.get(pk=e2.pk).needs_review is False
    # повтор - no-op
    assert links.link_expense_to_item(e1, item, "100", user=user).pk == a.pk
    with tenant_context(company.id):
        assert link_obj(e1.pk).count() == 1
    # позиция не покрывается больше своей суммы
    with pytest.raises(FinanceError) as exc:
        links.link_expense_to_item(manual(company, amount=D("5")), item, "1", user=user)
    assert code(exc) == "link_exceeds_item"
    # один расход закрывается двумя счетами
    e3 = manual(company, amount=D("100"))
    i1 = items_of(in_invoice(company, make_carrier(company), "60"))[0]
    i2 = items_of(in_invoice(company, make_carrier(company), "40"))[0]
    links.link_expense_to_item(e3, i1, "60", user=user)
    assert Expense.all_objects.get(pk=e3.pk).needs_review is True  # 60 != 100
    links.link_expense_to_item(e3, i2, "40", user=user)
    got = Expense.all_objects.get(pk=e3.pk)
    assert got.needs_review is False and got.review_reason == ""


def test_link_validation_rules(company):
    user = first_user(company)
    order, trip, expense = carrier_setup(company, "100.00")
    ok = items_of(in_invoice(company, trip.carrier, "100", order=order))[0]
    other_carrier = items_of(in_invoice(company, make_carrier(company, "Другой"), "100"))[0]
    with pytest.raises(FinanceError) as exc:
        links.link_expense_to_item(expense, other_carrier, "10", user=user)
    assert code(exc) == "party_mismatch"
    usd_inv = in_invoice(company, trip.carrier, "10")
    Invoice.all_objects.filter(pk=usd_inv.pk).update(currency=cur(company, "USD"))
    with pytest.raises(FinanceError) as exc:
        links.link_expense_to_item(expense, items_of(usd_inv)[0], "5", user=user)
    assert code(exc) == "currency_mismatch"
    for bad in ("0", "-1", "abc"):
        with pytest.raises(FinanceError) as exc:
            links.link_expense_to_item(expense, ok, bad, user=user)
        assert code(exc) == "amount_invalid"
    out = items_of(out_draft(company, new_order(company), [10]))[0]
    with pytest.raises(FinanceError) as exc:
        links.link_expense_to_item(expense, out, "5", user=user)
    assert code(exc) == "invoice_direction"
    order2, ids2 = order_with_cargos(company, 1)
    trip2 = new_trip(company, ids2, price="5")
    Trip.all_objects.filter(pk=trip2.pk).update(carrier=trip.carrier)
    trip2 = Trip.all_objects.get(pk=trip2.pk)
    mismatch_trip = in_invoice(company, trip.carrier, "20", trip=trip2, order=order2)
    with pytest.raises(FinanceError) as exc:
        links.link_expense_to_item(expense, items_of(mismatch_trip)[0], "5", user=user)
    assert code(exc) == "party_mismatch"
    ex.void_expense(expense, user=user, reason="r")
    with pytest.raises(FinanceError) as exc:
        links.link_expense_to_item(expense, ok, "10", user=user)
    assert code(exc) == "expense_void"


def test_amount_mismatch_sets_needs_review_and_does_not_block(company):
    user = first_user(company)
    order, trip, expense = carrier_setup(company, "100.00")
    item = items_of(in_invoice(company, trip.carrier, "100", order=order))[0]
    links.link_expense_to_item(expense, item, "80", user=user)
    got = Expense.all_objects.get(pk=expense.pk)
    assert got.needs_review is True and got.review_reason == "invoice_variance"
    assert got.amount == D("100.00")  # расход не изменён
    links.link_expense_to_item(expense, item, "100", user=user)  # поправили сумму связи
    assert Expense.all_objects.get(pk=expense.pk).needs_review is False


def test_cancel_incoming_invoice_releases_links_and_keeps_history(company):
    user = first_user(company)
    order, trip, expense = carrier_setup(company, "100.00")
    invoice = in_invoice(company, trip.carrier, "100", order=order)
    item = items_of(invoice)[0]
    link = links.link_expense_to_item(expense, item, "100", user=user)
    snapshot = (item.title, item.amount_net)
    with tenant_context(company.id):
        cancelled = inv_svc.cancel(invoice, user=user)
        released = ExpenseInvoiceAllocation.objects.get(pk=link.pk)
    assert cancelled.status == "cancelled"
    assert released.released_at is not None and released.release_reason == "invoice_cancelled"
    assert released.amount == D("100.00")  # запись остаётся историей
    after = items_of(invoice)[0]
    assert (after.title, after.amount_net) == snapshot and after.line_id is None
    last = audit_rows(company, invoice)[-1].changes
    assert last["released_expense_links"] == [
        {"link": link.pk, "expense": expense.pk, "amount": "100.00"}
    ]
    # после отмены активных связей нет: расхождение не висит, расход цел
    got = Expense.all_objects.get(pk=expense.pk)
    assert got.needs_review is False and got.status == "active" and got.amount == D("100.00")
    # новое включение в отменённый счёт запрещено
    with pytest.raises(FinanceError) as exc:
        links.link_expense_to_item(expense, item, "10", user=user)
    assert code(exc) == "invoice_not_active"


def test_cancel_one_of_two_invoices_flags_variance(company):
    user = first_user(company)
    e = manual(company, amount=D("100"))
    inv_a = in_invoice(company, make_carrier(company), "60")
    inv_b = in_invoice(company, make_carrier(company, "B"), "40")
    links.link_expense_to_item(e, items_of(inv_a)[0], "60", user=user)
    links.link_expense_to_item(e, items_of(inv_b)[0], "40", user=user)
    assert Expense.all_objects.get(pk=e.pk).needs_review is False
    with tenant_context(company.id):
        inv_svc.cancel(inv_b, user=user)
    got = Expense.all_objects.get(pk=e.pk)
    assert got.needs_review is True and got.review_reason == "invoice_variance"
    assert (
        ExpenseInvoiceAllocation.all_objects.filter(expense=e, released_at__isnull=True).count()
        == 1
    )


def test_carrier_price_change_does_not_touch_invoices_or_payments(company):
    user = first_user(company)
    order, trip, expense = carrier_setup(company, "100.00")
    invoice = in_invoice(company, trip.carrier, "100", order=order, trip=trip)
    pay_invoice(company, invoice, "100", day=date(2026, 7, 2))
    links.link_expense_to_item(expense, items_of(invoice)[0], "100", user=user)
    with tenant_context(company.id):
        pays = list(Payment.objects.values_list("id", "amount", "rate_to_kzt", "date"))
        before = Invoice.objects.filter(pk=invoice.pk).values_list("total_gross", "status").get()
        Trip.objects.filter(pk=trip.pk).update(carrier_price=D("250.00"))
    ex.sync_trip_expense(Trip.all_objects.get(pk=trip.pk), user=user)
    with tenant_context(company.id):
        assert list(Payment.objects.values_list("id", "amount", "rate_to_kzt", "date")) == pays
        assert (
            Invoice.objects.filter(pk=invoice.pk).values_list("total_gross", "status").get()
            == before
        )
        assert Expense.objects.count() == 1
    assert Expense.all_objects.get(pk=expense.pk).needs_review is True


def test_legacy_cancel_without_links_is_unchanged(company):
    invoice = issue_invoice(company, amount="100", day=date(2026, 7, 1))
    with tenant_context(company.id):
        inv_svc.cancel(invoice, user=first_user(company))
    changes = audit_rows(company, invoice)[-1].changes
    assert changes == {"status": ["issued", "cancelled"]}


def test_isolation_between_companies(company, make_company):
    other, _, _ = make_company("Other")
    user = first_user(company)
    e = manual(company, amount=D("10"))
    foreign_item = items_of(in_invoice(other, make_carrier(other), "10"))[0]
    with pytest.raises(Exception) as exc:
        links.link_expense_to_item(e, foreign_item, "5", user=user)
    assert exc.type.__name__ in ("DoesNotExist", "FinanceError")
    with tenant_context(other.id):
        assert ExpenseInvoiceAllocation.objects.count() == 0
        assert Income.objects.count() == 0
