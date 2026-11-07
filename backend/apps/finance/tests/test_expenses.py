"""Расходы и распределения (1.4.5)."""

import threading
from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal as D

import pytest
import time_machine
from django.db import connection
from django.db.models import Sum

from apps.core.audit.models import AuditLog
from apps.core.handbooks.models import HandbookValue
from apps.core.tenancy import tenant_context
from apps.finance import expenses as ex
from apps.finance import periods
from apps.finance.errors import FinanceError
from apps.finance.models import (
    CompanyFinancialSettings,
    Expense,
    ExpenseAllocation,
    ExpenseInvoiceAllocation,
    InvoiceItem,
    Payment,
)
from apps.finance.tests.helpers import cur, first_user, issue_invoice, make_carrier, pay_invoice
from apps.finance.tests.p2_helpers import enable_new, new_trip, order_with_cargos, rate, set_engine
from apps.forwarding.models import Trip

pytestmark = pytest.mark.django_db
TODAY = date(2026, 7, 15)
ADJ = "finance.adjust_closed"


@pytest.fixture(autouse=True)
def frozen():
    with time_machine.travel(datetime(2026, 7, 15, 12, 0, tzinfo=dt_tz.utc), tick=False):
        yield


def code(exc):
    return exc.value.detail.code


def category(company, code_="FUEL"):
    with tenant_context(company.id):
        return HandbookValue.objects.get(handbook__code="expense_category", code=code_)


def manual(company, **kw):
    data = {
        "title": "Топливо",
        "category": category(company),
        "amount": D("1000"),
        "currency": cur(company),
        "expense_date": TODAY,
        "user": first_user(company),
    }
    data.update(kw)
    return ex.create_expense(company, **data)


def allocs(expense):
    with tenant_context(expense.company_id):
        return [
            (a.order_id, a.trip_id, a.amount)
            for a in ExpenseAllocation.objects.filter(expense=expense).order_by("id")
        ]


def reload(expense):
    return Expense.all_objects.get(pk=expense.pk)


def audit_rows(company, obj):
    with tenant_context(company.id):
        return list(
            AuditLog.objects.filter(
                object_type=obj._meta.label_lower, object_id=str(obj.pk)
            ).order_by("id")
        )


def trip_with_orders(company, n_orders=1, price="100.00", currency=None):
    orders, ids = [], []
    for _ in range(n_orders):
        o, cids = order_with_cargos(company, 1)
        orders.append(o)
        ids += cids
    return orders, new_trip(company, ids, price=price, currency=currency)


def carrier_expense(company, trip, **kw):
    kw.setdefault("user", first_user(company))
    return ex.create_carrier_expense(trip, **kw)


# --- ручной расход ---


def test_manual_expense_fully_partially_and_unallocated(company):
    o1, _ = order_with_cargos(company, 1)
    o2, _ = order_with_cargos(company, 1)
    full = manual(
        company,
        requires_full_allocation=True,
        allocations=[{"order": o1, "amount": "600"}, {"order": o2, "amount": "400"}],
    )
    assert full.source == "manual" and full.kind == "other" and full.status == "active"
    assert [a[2] for a in allocs(full)] == [D("600.00"), D("400.00")]
    part = manual(company, allocations=[{"order": o1, "amount": "250.50"}])
    assert allocs(part)[0][2] == D("250.50")
    general = manual(company, title="Аренда офиса")  # нераспределённый общий расход
    assert allocs(general) == [] and general.requires_full_allocation is False
    assert audit_rows(company, general)[0].action == "create"


def test_manual_expense_allocation_rules(company):
    o1, _ = order_with_cargos(company, 1)
    for items, expected in (
        ([{"order": o1, "amount": "1000.01"}], "allocation_exceeds"),
        ([{"order": o1, "amount": "0"}], "amount_invalid"),
        ([{"amount": "10"}], "allocation_target"),
        ([{"order": o1, "amount": "10"}, {"order": o1, "amount": "5"}], "allocation_duplicate"),
    ):
        with pytest.raises(FinanceError) as exc:
            manual(company, allocations=items)
        assert code(exc) == expected
    with pytest.raises(FinanceError) as exc:
        manual(
            company, requires_full_allocation=True, allocations=[{"order": o1, "amount": "999.99"}]
        )
    assert code(exc) == "allocation_mismatch"
    with tenant_context(company.id):
        assert Expense.objects.count() == 0


def test_manual_expense_validation_and_fx(company):
    for field, value, expected in (
        ("title", "  ", "title_required"),
        ("amount", "-1", "amount_invalid"),
        ("category", cur(company), "handbook_invalid"),  # не категория расходов
        ("currency", category(company), "handbook_invalid"),
        ("kind", "carrier_transport", "expense_kind_invalid"),
    ):
        with pytest.raises(FinanceError) as exc:
            manual(company, **{field: value})
        assert code(exc) == expected, field
    with pytest.raises(FinanceError) as exc:  # нет курса - ничего не создаётся
        manual(company, currency=cur(company, "USD"))
    assert code(exc) == "rate_missing"
    rate(company, "USD", "480", date(2026, 1, 1))
    usd = manual(company, currency=cur(company, "USD"), amount=D("10.01"))
    assert (usd.fx_rate_source, usd.fx_rate, usd.base_amount) == ("via_kzt", D("480"), D("4804.80"))
    with tenant_context(company.id):
        assert Expense.objects.count() == 1


def test_manual_expense_dates_and_periods(company):
    user = first_user(company)
    with tenant_context(company.id):
        pass
    periods.close_period(company, 2026, 5, user)
    day = date(2026, 5, 10)
    with pytest.raises(FinanceError) as exc:
        manual(company, expense_date=day)
    assert code(exc) == "period_closed"
    with pytest.raises(FinanceError) as exc:
        manual(company, expense_date=day, perms={ADJ})
    assert code(exc) == "period_reason_required"
    done = manual(company, expense_date=day, perms={ADJ}, adjust_reason="поздний акт")
    assert "closed_period_adjustment" in audit_rows(company, done)[0].changes
    CompanyFinancialSettings.all_objects.filter(company=company).update(allow_backdating=False)
    with pytest.raises(FinanceError) as exc:
        manual(company, expense_date=date(2026, 7, 14))
    assert code(exc) == "backdating_forbidden"
    manual(company, expense_date=date(2026, 7, 14), perms={"finance.backdate"})
    manual(company, expense_date=TODAY)


# --- расход перевозчика ---


def test_carrier_expense_single_trip(company):
    (order,), trip = trip_with_orders(company, 1, "100.00")
    exp = carrier_expense(company, trip)
    assert (exp.kind, exp.source, exp.amount, exp.requires_full_allocation) == (
        "carrier_transport", "carrier_price_sync", D("100.00"), True,
    )  # fmt: skip
    assert exp.carrier_id == trip.carrier_id and exp.carrier_price_snapshot == D("100.00")
    assert exp.currency_id == trip.currency_id and exp.expense_date == TODAY
    assert exp.fx_rate_source == "same" and exp.base_amount == D("100.00")
    assert allocs(exp) == [(order.pk, trip.pk, D("100.00"))]


def test_carrier_expense_consolidated_trip_penny_split(company):
    orders, trip = trip_with_orders(company, 3, "100.00")
    exp = carrier_expense(company, trip)
    assert [a[2] for a in allocs(exp)] == [D("33.34"), D("33.33"), D("33.33")]
    assert sum(a[2] for a in allocs(exp)) == D("100.00")
    assert [a[0] for a in allocs(exp)] == sorted(o.pk for o in orders)


def test_carrier_expense_rules(company):
    orders, trip = trip_with_orders(company, 2, "50.00")
    no_carrier = new_trip(company, [order_with_cargos(company, 1)[1][0]], carrier=False, price="10")
    with pytest.raises(FinanceError) as exc:
        carrier_expense(company, no_carrier)
    assert code(exc) == "trip_without_carrier"
    exp = carrier_expense(company, trip)
    with pytest.raises(FinanceError) as exc:
        carrier_expense(company, trip)
    assert code(exc) == "expense_exists" and exc.value.status_code == 409
    with tenant_context(company.id):
        assert Expense.objects.filter(kind="carrier_transport").count() == 1
    ex.void_expense(exp, user=first_user(company), reason="ошибка")
    again = carrier_expense(company, trip)  # после аннулирования можно создать новый
    assert again.pk != exp.pk


def test_carrier_expense_custom_allocations_and_mismatches(company):
    orders, trip = trip_with_orders(company, 2, "100.00")
    ok = carrier_expense(
        company, trip,
        allocations=[{"order": orders[0], "amount": "70"}, {"order": orders[1], "amount": "30"}],
    )  # fmt: skip
    assert [a[2] for a in allocs(ok)] == [D("70.00"), D("30.00")]
    ex.void_expense(ok, user=first_user(company), reason="r")
    for items, expected in (
        ([{"order": orders[0], "amount": "99"}], "allocation_mismatch"),
        ([{"order": orders[0], "amount": "101"}], "allocation_exceeds"),
    ):
        with pytest.raises(FinanceError) as exc:
            carrier_expense(company, trip, allocations=items)
        assert code(exc) == expected
    foreign, _ = order_with_cargos(company, 1)
    with pytest.raises(FinanceError) as exc:
        carrier_expense(company, trip, allocations=[{"order": foreign, "amount": "100"}])
    assert code(exc) == "order_not_in_trip"


def test_carrier_expense_currency_mismatch_and_zero_price(company):
    orders, trip = trip_with_orders(company, 1, "10", currency="USD")
    with pytest.raises(FinanceError) as exc:
        carrier_expense(company, trip)
    assert code(exc) == "currency_mismatch"
    _, zero = trip_with_orders(company, 1, "0")
    exp = carrier_expense(company, zero)
    assert exp.amount == D("0.00") and allocs(exp) == []


def test_carrier_expense_date_rules(company):
    user = first_user(company)
    _, trip = trip_with_orders(company, 1, "10")
    periods.close_period(company, 2026, 5, user)
    with pytest.raises(FinanceError) as exc:
        carrier_expense(company, trip, expense_date=date(2026, 5, 3))
    assert code(exc) == "period_closed"
    exp = carrier_expense(
        company, trip, expense_date=date(2026, 5, 3), perms={ADJ}, adjust_reason="доначисление"
    )
    assert exp.expense_date == date(2026, 5, 3)


# --- синхронизация с ценой ---


def set_price(trip, price):
    with tenant_context(trip.company_id):
        Trip.objects.filter(pk=trip.pk).update(carrier_price=D(str(price)))
    return Trip.all_objects.get(pk=trip.pk)


def sync(company, trip, **kw):
    kw.setdefault("user", first_user(company))
    return ex.sync_trip_expense(trip, **kw)


def test_sync_growth_and_decrease_keep_proportions(company):
    orders, trip = trip_with_orders(company, 2, "1000.00")
    exp = carrier_expense(
        company, trip,
        allocations=[{"order": orders[0], "amount": "600"}, {"order": orders[1], "amount": "400"}],
    )  # fmt: skip
    trip = set_price(trip, "1500.00")
    got = sync(company, trip)
    assert (
        got.pk == exp.pk
        and got.amount == D("1500.00")
        and got.carrier_price_snapshot == D("1500.00")
    )
    assert [a[2] for a in allocs(exp)] == [D("900.00"), D("600.00")]
    trip = set_price(trip, "500.00")
    sync(company, trip)
    assert [a[2] for a in allocs(exp)] == [D("300.00"), D("200.00")]
    with tenant_context(company.id):
        assert Expense.objects.filter(kind="carrier_transport").count() == 1
    last = audit_rows(company, exp)[-1]
    assert last.changes["amount"] == ["1500.00", "500.00"]
    assert last.changes["allocations"][0] != last.changes["allocations"][1]


def test_sync_penny_remainder_and_sum_exact(company):
    orders, trip = trip_with_orders(company, 3, "100.00")
    exp = carrier_expense(company, trip)  # 33.34 / 33.33 / 33.33
    for price in ("100.01", "200.00", "0.07", "1234.57"):
        trip = set_price(trip, price)
        sync(company, trip)
        parts = [a[2] for a in allocs(exp)]
        assert all(p > 0 for p in parts)
        assert sum(parts) == D(price), (price, parts)
        assert reload(exp).amount == D(price)


def test_sync_zero_price_then_growth_and_idempotent(company):
    orders, trip = trip_with_orders(company, 2, "100.00")
    exp = carrier_expense(company, trip)
    trip = set_price(trip, "0.00")
    sync(company, trip)
    assert (
        allocs(exp) == []
        and reload(exp).amount == D("0.00")
        and reload(exp).base_amount == D("0.00")
    )
    trip = set_price(trip, "50.00")
    sync(company, trip)
    assert [a[2] for a in allocs(exp)] == [D("25.00"), D("25.00")]  # по умолчанию поровну
    n = len(audit_rows(company, exp))
    sync(company, trip)
    sync(company, trip)
    assert len(audit_rows(company, exp)) == n  # идемпотентно


def test_sync_noop_without_expense_or_when_void(company):
    _, trip = trip_with_orders(company, 1, "100")
    trip = set_price(trip, "200")
    assert sync(company, trip) is None
    with tenant_context(company.id):
        assert Expense.objects.count() == 0  # автосоздания нет
    exp = carrier_expense(company, trip)
    ex.void_expense(exp, user=first_user(company), reason="r")
    trip = set_price(trip, "300")
    assert sync(company, trip) is None
    assert reload(exp).amount == D("200.00")


def test_sync_keeps_fx_rate_and_recomputes_base(company):
    rate(company, "USD", "480", date(2026, 1, 1))
    orders, trip = trip_with_orders(company, 1, "10.00", currency="USD")
    with tenant_context(company.id):
        from apps.forwarding.models import Order

        Order.all_objects.filter(pk=orders[0].pk).update(currency=cur(company, "USD"))
    exp = carrier_expense(company, trip)
    assert exp.base_amount == D("4800.00")
    rate(company, "USD", "999", date(2026, 7, 1))
    trip = set_price(trip, "12.50")
    sync(company, trip)
    got = reload(exp)
    assert got.fx_rate == D("480") and got.base_amount == D("6000.00") and got.amount == D("12.50")


def test_sync_closed_period_three_outcomes(company):
    orders, trip = trip_with_orders(company, 1, "100.00")
    user = first_user(company)
    exp = carrier_expense(company, trip, expense_date=TODAY)
    Expense.all_objects.filter(pk=exp.pk).update(expense_date=date(2026, 5, 10))
    periods.close_period(company, 2026, 5, user)
    trip = set_price(trip, "150.00")
    with pytest.raises(FinanceError) as exc:
        sync(company, trip)
    assert code(exc) == "period_closed" and exc.value.status_code == 409
    assert reload(exp).amount == D("100.00")
    with pytest.raises(FinanceError) as exc:
        sync(company, trip, can_adjust=True)
    assert code(exc) == "period_reason_required" and exc.value.status_code == 400
    sync(company, trip, can_adjust=True, reason="уточнение цены")
    assert reload(exp).amount == D("150.00")
    last = audit_rows(company, exp)[-1].changes
    assert last["closed_period_adjustment"]["reason"] == "уточнение цены"
    assert last["closed_period_adjustment"]["old"] == {"amount": "100.00"}


def test_invoice_variance_flags_review_without_blocking(company):
    orders, trip = trip_with_orders(company, 1, "100.00")
    exp = carrier_expense(company, trip)
    invoice = issue_invoice(
        company, order=orders[0], direction="in", carrier=trip.carrier, amount="100", trip=trip
    )
    pay_invoice(company, invoice, "40")
    with tenant_context(company.id):
        item = InvoiceItem.objects.get(invoice=invoice)
        ExpenseInvoiceAllocation.objects.create(expense=exp, invoice_item=item, amount=D("100.00"))
        payments_before = list(Payment.objects.values_list("id", "amount"))
        totals_before = (invoice.total_net, invoice.status)
    ex.refresh_invoice_variance(reload(exp))
    assert reload(exp).needs_review is False  # сумма совпала
    trip = set_price(trip, "130.00")
    sync(company, trip)
    got = reload(exp)
    assert got.amount == D("130.00")  # цена не заблокирована
    assert got.needs_review is True and got.review_reason == "invoice_variance"
    trip = set_price(trip, "100.00")  # вернулась: расхождения нет - флаг снят
    sync(company, trip)
    got = reload(exp)
    assert got.needs_review is False and got.review_reason == ""
    with tenant_context(company.id):  # счета и платежи не менялись
        from apps.finance.models import Invoice

        fresh = Invoice.objects.get(pk=invoice.pk)
        assert (fresh.total_net, fresh.status) == totals_before
        assert list(Payment.objects.values_list("id", "amount")) == payments_before
        assert ExpenseInvoiceAllocation.objects.get(expense=exp).amount == D("100.00")


def test_payments_and_invoices_never_create_expenses(company):
    orders, trip = trip_with_orders(company, 1, "100.00")
    invoice = issue_invoice(
        company, order=orders[0], direction="in", carrier=trip.carrier, amount="100", trip=trip
    )
    pay_invoice(company, invoice, "100")
    with tenant_context(company.id):
        assert Expense.objects.count() == 0


def test_no_double_counting_between_order_and_trip_slices(company):
    orders, trip = trip_with_orders(company, 3, "100.00")
    exp = carrier_expense(company, trip)
    with tenant_context(company.id):
        total = ExpenseAllocation.objects.filter(expense=exp).aggregate(t=Sum("amount"))["t"]
        by_order = ExpenseAllocation.objects.filter(expense=exp, order__isnull=False).aggregate(
            t=Sum("amount")
        )["t"]
        by_trip = ExpenseAllocation.objects.filter(expense=exp, trip=trip).aggregate(
            t=Sum("amount")
        )["t"]
    assert total == by_order == by_trip == exp.amount == D("100.00")  # одна доля - один срез


# --- распределение и аннулирование ---


def test_set_allocations_replaces_and_validates(company):
    o1, _ = order_with_cargos(company, 1)
    o2, _ = order_with_cargos(company, 1)
    user = first_user(company)
    exp = manual(company)
    ex.set_allocations(exp, [{"order": o1, "amount": "300"}], user=user)  # Σ < суммы допустимо
    assert [a[2] for a in allocs(exp)] == [D("300.00")]
    n = len(audit_rows(company, exp))
    ex.set_allocations(exp, [{"order": o1, "amount": "300"}], user=user)  # то же - no-op
    assert len(audit_rows(company, exp)) == n
    ex.set_allocations(
        exp,
        [
            {"order": o2, "amount": "1000"},
        ],
        user=user,
    )
    assert [a[0] for a in allocs(exp)] == [o2.pk]
    ex.set_allocations(exp, [], user=user)
    assert allocs(exp) == []
    full = manual(company, requires_full_allocation=True)
    with pytest.raises(FinanceError) as exc:
        ex.set_allocations(full, [{"order": o1, "amount": "10"}], user=user)
    assert code(exc) == "allocation_mismatch"
    with pytest.raises(FinanceError) as exc:
        ex.set_allocations(exp, [{"order": o1, "amount": "1001"}], user=user)
    assert code(exc) == "allocation_exceeds"
    orders, trip = trip_with_orders(company, 2, "40")
    carrier = carrier_expense(company, trip)
    with pytest.raises(FinanceError) as exc:
        ex.set_allocations(carrier, [{"order": o1, "amount": "40"}], user=user)
    assert code(exc) == "order_not_in_trip"


def test_set_allocations_closed_period_and_void(company):
    o1, _ = order_with_cargos(company, 1)
    user = first_user(company)
    exp = manual(company, expense_date=TODAY)
    Expense.all_objects.filter(pk=exp.pk).update(expense_date=date(2026, 5, 10))
    periods.close_period(company, 2026, 5, user)
    items = [{"order": o1, "amount": "10"}]
    with pytest.raises(FinanceError) as exc:
        ex.set_allocations(exp, items, user=user)
    assert code(exc) == "period_closed"
    with pytest.raises(FinanceError) as exc:
        ex.set_allocations(exp, items, user=user, perms={ADJ})
    assert code(exc) == "period_reason_required"
    ex.set_allocations(exp, items, user=user, perms={ADJ}, reason="перенос")
    with pytest.raises(FinanceError) as exc:
        ex.void_expense(exp, user=user, reason="r")
    assert code(exc) == "period_closed"
    with pytest.raises(FinanceError) as exc:
        ex.void_expense(exp, user=user, reason=" ", can_adjust=True)
    assert code(exc) == "reason_required"
    voided = ex.void_expense(exp, user=user, reason="ошибка", can_adjust=True)
    assert voided.status == "void" and voided.voided_by_id == user.pk and voided.voided_at
    assert len(allocs(exp)) == 1  # доли остались историей
    with pytest.raises(FinanceError) as exc:
        ex.set_allocations(voided, [], user=user)
    assert code(exc) == "expense_void"
    assert ex.void_expense(voided, user=user, reason="повтор").pk == exp.pk  # идемпотентно


def test_split_proportionally_examples():
    assert ex.split_proportionally(D("100"), [D("1"), D("1"), D("1")]) == [
        D("33.34"),
        D("33.33"),
        D("33.33"),
    ]
    assert sum(ex.split_proportionally(D("0.05"), [D("3"), D("5"), D("2")])) == D("0.05")
    assert ex.split_proportionally(D("10"), [D("7")]) == [D("10.00")]
    assert ex.split_proportionally(D("0"), [D("1"), D("2")]) == [D("0.00"), D("0.00")]


# --- хук цены рейса через API ---


def patch_price(client, trip, price, **extra):
    return client.patch(f"/api/trips/{trip.pk}/", {"carrier_price": price, **extra}, format="json")


def test_trip_price_hook_only_for_engine_new_and_sync_flag(admin_client, company):
    enable_new(company)
    orders, trip = trip_with_orders(company, 1, "100.00")
    exp = carrier_expense(company, trip)
    r = patch_price(admin_client, trip, "250.00")
    assert r.status_code == 200, r.content
    assert reload(exp).amount == D("250.00")
    CompanyFinancialSettings.all_objects.filter(company=company).update(sync_carrier_price=False)
    assert patch_price(admin_client, trip, "300.00").status_code == 200
    assert reload(exp).amount == D("250.00")
    CompanyFinancialSettings.all_objects.filter(company=company).update(
        sync_carrier_price=True, engine="shadow"
    )
    assert patch_price(admin_client, trip, "400.00").status_code == 200
    assert reload(exp).amount == D("250.00")  # legacy/shadow: хук спит
    set_engine(company, "new")
    assert (
        patch_price(admin_client, trip, "400.00").status_code == 200
    )  # цена не менялась с последнего PATCH
    assert reload(exp).amount == D(
        "250.00"
    )  # сравнение с ценой до PATCH: изменения нет, хук не вызывался
    assert patch_price(admin_client, trip, "410.00").status_code == 200
    assert reload(exp).amount == D("410.00")


def test_trip_price_hook_closed_period_returns_409_and_keeps_price(admin_client, company):
    enable_new(company)
    orders, trip = trip_with_orders(company, 1, "100.00")
    exp = carrier_expense(company, trip)
    Expense.all_objects.filter(pk=exp.pk).update(expense_date=date(2026, 5, 10))
    periods.close_period(company, 2026, 5, first_user(company))
    plain_client = admin_client
    # админ имеет adjust_closed: без причины - 400
    r = patch_price(plain_client, trip, "150.00")
    assert r.status_code == 400 and r.data["code"] == "period_reason_required"
    assert Trip.all_objects.get(pk=trip.pk).carrier_price == D("100.00")  # откат запроса
    r = patch_price(plain_client, trip, "150.00", adjust_reason="правка цены")
    assert r.status_code == 200
    assert Trip.all_objects.get(pk=trip.pk).carrier_price == D("150.00") and reload(
        exp
    ).amount == D("150.00")


# --- конкурентность и изоляция ---


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_sync_and_create_leaves_one_active_expense(company):
    enable_new(company)
    orders, trip = trip_with_orders(company, 2, "100.00")
    user = first_user(company)
    errors = []
    barrier = threading.Barrier(3)

    def create():
        try:
            barrier.wait()
            ex.create_carrier_expense(trip, user=user)
        except FinanceError as exc:
            if exc.detail.code != "expense_exists":
                errors.append(exc)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    def change():
        try:
            barrier.wait()
            with tenant_context(company.id):
                Trip.objects.filter(pk=trip.pk).update(carrier_price=D("160.00"))
            ex.sync_trip_expense(Trip.all_objects.get(pk=trip.pk), user=user)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    threads = [
        threading.Thread(target=create),
        threading.Thread(target=create),
        threading.Thread(target=change),
    ]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    with tenant_context(company.id):
        active = list(Expense.objects.filter(kind="carrier_transport", status="active"))
    assert len(active) == 1
    # итоговая цена отражена, в каком бы порядке ни шли создание и смена цены
    final = Trip.all_objects.get(pk=trip.pk).carrier_price
    ex.sync_trip_expense(Trip.all_objects.get(pk=trip.pk), user=user)
    assert reload(active[0]).amount == final == D("160.00")
    assert sum(a[2] for a in allocs(active[0])) == D("160.00")


def test_isolation_between_companies(company, make_company):
    other, _, _ = make_company("Other")
    orders, trip = trip_with_orders(company, 1, "10")
    carrier_expense(company, trip)
    manual(company)
    with tenant_context(other.id):
        assert Expense.objects.count() == 0 and ExpenseAllocation.objects.count() == 0
    # чужой заказ в долях не принимается
    foreign, _ = order_with_cargos(other, 1)
    with pytest.raises(FinanceError) as exc:
        manual(company, allocations=[{"order": foreign, "amount": "1"}])
    assert code(exc) == "allocation_target"
    assert make_carrier and Payment
