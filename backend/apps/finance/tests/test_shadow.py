"""Shadow-запись (1.4.7): зеркало OrderService в новые сущности только при engine='shadow'."""

import threading
from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal as D

import pytest
import time_machine
from django.db import connection

from apps.core.tenancy import tenant_context
from apps.finance import expenses as ex
from apps.finance import invoices as inv_svc
from apps.finance import migration, shadow
from apps.finance.models import (
    Expense,
    ExpenseAllocation,
    ExpenseInvoiceAllocation,
    FinanceMigrationIssue,
    Income,
    InvoiceItem,
)
from apps.finance.tests.helpers import cur, first_user, make_carrier, make_client, vat
from apps.finance.tests.p2_helpers import new_trip, order_with_cargos, set_engine
from apps.forwarding.finance_lines.models import OrderService
from apps.forwarding.models import Order
from apps.forwarding.tests.test_orders import make_order as fw_make_order

pytestmark = pytest.mark.django_db
LINES = "/api/order-lines/"


@pytest.fixture(autouse=True)
def frozen():
    with time_machine.travel(datetime(2026, 7, 15, 12, 0, tzinfo=dt_tz.utc), tick=False):
        yield


def post_line(client, order, **extra):
    body = {"order": order.pk, "title": "Услуга", "income": "100", **extra}
    r = client.post(LINES, body, format="json")
    assert r.status_code == 201, r.content
    return r.data["id"]


def incomes(company, **f):
    with tenant_context(company.id):
        return list(Income.objects.filter(**f).order_by("id"))


def expenses(company, **f):
    with tenant_context(company.id):
        return list(Expense.objects.filter(**f).order_by("id"))


def issues(company, type_="shadow_error"):
    with tenant_context(company.id):
        return list(FinanceMigrationIssue.objects.filter(issue_type=type_))


def new_order(company, rate="500.00"):
    return fw_make_order(company, make_client(company), client_rate=D(rate))


# --- точки зеркала ---


def test_order_create_and_client_rate_change_mirror_base_line(admin_client, company):
    set_engine(company, "shadow")
    order = new_order(company)
    with tenant_context(company.id):
        base = OrderService.objects.get(order=order, is_base=True)
    inc = incomes(company, legacy_line=base)
    assert len(inc) == 1
    assert (inc[0].kind, inc[0].status, inc[0].amount) == ("freight", "recognized", D("500.00"))
    assert inc[0].recognition_basis == "legacy_line_date" and inc[0].recognized_on == base.date
    r = admin_client.patch(f"/api/orders/{order.pk}/", {"client_rate": "900.00"}, format="json")
    assert r.status_code == 200, r.content
    inc = incomes(company, order=order)
    assert len(inc) == 1 and inc[0].amount == D("900.00") and inc[0].base_amount == D("900.00")


def test_line_create_update_delete_mirror(admin_client, company):
    set_engine(company, "shadow")
    order = new_order(company, "0")
    pk = post_line(admin_client, order, income="100", expense="40", title="Хранение")
    (inc,) = incomes(company, legacy_line_id=pk)
    assert inc.kind == "service" and inc.amount == D("100.00")
    (exp,) = expenses(company, legacy_group_key=f"line:{pk}")
    assert exp.kind == "other" and exp.source == "migrated" and exp.amount == D("40.00")
    with tenant_context(company.id):
        assert ExpenseAllocation.objects.get(legacy_line_id=pk).amount == D("40.00")
    r = admin_client.patch(f"{LINES}{pk}/", {"income": "150", "expense": "55"}, format="json")
    assert r.status_code == 200, r.content
    assert incomes(company, legacy_line_id=pk)[0].amount == D("150.00")
    assert expenses(company, pk=exp.pk)[0].amount == D("55.00")
    assert incomes(company, order=order, status="recognized").__len__() == 1
    r = admin_client.delete(f"{LINES}{pk}/")
    assert r.status_code == 204, r.content
    gone = incomes(company, pk=inc.pk)[0]
    assert (
        gone.status == "void"
        and gone.void_reason == "legacy_line_deleted"
        and gone.legacy_line_id is None
    )
    with tenant_context(company.id):
        assert ExpenseAllocation.objects.filter(expense=exp).count() == 0
    assert (
        expenses(company, pk=exp.pk)[0].status == "void"
    )  # у зеркального расхода долей не осталось
    assert issues(company) == []
    # история цела: записи не удалены
    assert incomes(company, pk=inc.pk) and expenses(company, pk=exp.pk)


def test_line_zeroed_unlinks_mirror(admin_client, company):
    set_engine(company, "shadow")
    order = new_order(company, "0")
    pk = post_line(admin_client, order, income="10", expense="5")
    admin_client.patch(f"{LINES}{pk}/", {"income": "0", "expense": "0"}, format="json")
    assert incomes(company, order=order, status="recognized") == []
    assert expenses(company, status="active") == []


def test_trip_expense_group_mirror_and_line_delete_recalculates(admin_client, company):
    from apps.finance import trip_expense as te

    set_engine(company, "shadow")
    orders, ids = [], []
    for _ in range(3):
        o, cids = order_with_cargos(company, 1)
        orders.append(o)
        ids += cids
    trip = new_trip(company, ids, price="100.00")
    user = first_user(company)
    alloc = [
        {"order_id": o.pk, "amount": a}
        for o, a in zip(sorted(orders, key=lambda o: o.pk), [D("33.34"), D("33.33"), D("33.33")])
    ]
    with tenant_context(company.id):
        lines = te.create_trip_expense(trip, alloc, user=user)
    (exp,) = expenses(company, kind="carrier_transport")
    assert exp.source == "migrated" and exp.amount == D("100.00") and exp.trip_id == trip.pk
    assert exp.legacy_group_key == f"trip:{trip.pk}" and exp.needs_review is False
    with tenant_context(company.id):
        assert ExpenseAllocation.objects.filter(expense=exp).count() == 3
    # повторное зеркало ничего не дублирует
    for o in orders:
        shadow.mirror_order(o, "again")
    assert len(expenses(company, kind="carrier_transport")) == 1
    with tenant_context(company.id):
        assert ExpenseAllocation.objects.filter(expense=exp).count() == 3
    # удаляем одну строку: доля снята, сумма расхода пересчитана и помечена на проверку
    r = admin_client.delete(f"{LINES}{lines[0].pk}/")
    assert r.status_code == 204
    exp = expenses(company, pk=exp.pk)[0]
    assert exp.status == "active" and exp.amount == D("66.66") and exp.needs_review is True
    assert exp.review_reason == "migrated_mismatch"


def test_invoice_issue_and_cancel_mirror_links(admin_client, company):
    set_engine(company, "shadow")
    user = first_user(company)
    order = new_order(company, "0")
    out_line = post_line(admin_client, order, income="300")
    in_line = post_line(admin_client, order, income="0", expense="120", title="Склад")
    carrier = make_carrier(company)
    with tenant_context(company.id):
        line_o = OrderService.objects.get(pk=out_line)
        line_i = OrderService.objects.get(pk=in_line)
        d_out = inv_svc.create_draft(
            direction="out", party=order.client, order=order, currency=cur(company),
            vat_rate=vat(company, "0"), due_date=None, user=user,
            items=[{"title": "x", "amount_net": D("300"), "line": line_o}],
        )  # fmt: skip
        d_in = inv_svc.create_draft(
            direction="in", party=carrier, order=order, currency=cur(company),
            vat_rate=vat(company, "0"), due_date=None, user=user,
            items=[{"title": "y", "amount_net": D("120"), "line": line_i}],
        )  # fmt: skip
        out_inv = inv_svc.issue(d_out, user=user, issue_date=date(2026, 7, 15))
        in_inv = inv_svc.issue(d_in, user=user, issue_date=date(2026, 7, 15))
        item_o = InvoiceItem.objects.get(invoice=out_inv)
        item_i = InvoiceItem.objects.get(invoice=in_inv)
        assert item_o.income.legacy_line_id == out_line
        link = ExpenseInvoiceAllocation.objects.get(invoice_item=item_i)
        assert link.amount == D("120.00") and link.released_at is None
        inv_svc.cancel(out_inv, user=user)
        inv_svc.cancel(in_inv, user=user)
        assert InvoiceItem.objects.get(pk=item_o.pk).income_id is None
        assert ExpenseInvoiceAllocation.objects.get(pk=link.pk).released_at is not None


# --- другие движки ---


@pytest.mark.parametrize("engine", ["legacy", "new"])
def test_no_mirror_for_legacy_and_new(admin_client, company, engine):
    set_engine(company, engine, **({"cutover_date": date(2026, 1, 1)} if engine == "new" else {}))
    order = new_order(company)
    pk = post_line(admin_client, order, income="100", expense="10")
    assert incomes(company, legacy_line_id=pk) == []
    assert expenses(company, source="migrated") == []
    with tenant_context(company.id):
        assert ExpenseAllocation.objects.count() == 0
    admin_client.delete(f"{LINES}{pk}/")
    assert issues(company) == []


# --- ошибка зеркала ---


def test_mirror_failure_does_not_break_operation_and_records_issue(
    admin_client, company, monkeypatch
):
    set_engine(company, "shadow")
    order = new_order(company)
    before_incomes = len(incomes(company))

    def boom(*a, **k):
        raise RuntimeError("секрет не должен попасть в текст")

    monkeypatch.setattr(migration, "migrate_order", boom)
    pk = post_line(admin_client, order, income="100", expense="10")  # основная операция выполнена
    with tenant_context(company.id):
        assert OrderService.objects.filter(pk=pk).exists()
    assert len(incomes(company)) == before_incomes  # зеркала нет
    (issue,) = issues(company)
    assert issue.severity == "error" and issue.status == "open"
    assert (
        issue.details["operation"] == "order_line_saved"
        and "RuntimeError" in issue.details["error"]
    )
    assert issue.source_model == "forwarding.order" and issue.source_id == order.pk
    # частично записанное зеркало откатывается savepoint-ом целиком
    monkeypatch.undo()
    calls = {}
    real = migration._migrate_manual

    def half(ctx, line, order_):
        real(ctx, line, order_)
        raise RuntimeError("после частичной записи")

    monkeypatch.setattr(migration, "_migrate_manual", half)
    pk2 = post_line(admin_client, order, income="7", expense="3", title="Ещё")
    assert (
        incomes(company, legacy_line_id=pk2) == []
        and expenses(company, legacy_group_key=f"line:{pk2}") == []
    )
    assert len(issues(company)) == 2
    assert calls == {}


def test_shadow_does_not_touch_old_data(admin_client, company):
    set_engine(company, "shadow")
    order = new_order(company)
    pk = post_line(admin_client, order, income="100", expense="10")
    with tenant_context(company.id):
        line = OrderService.objects.get(pk=pk)
        assert (line.income, line.expense, line.title) == (D("100.00"), D("10.00"), "Услуга")
        assert Order.objects.get(pk=order.pk).client_rate == D("500.00")


# --- параллельность ---


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_parallel_mirrors_do_not_duplicate(company):
    set_engine(company, "shadow")
    order = new_order(company, "10")
    with tenant_context(company.id):
        for i in range(3):
            OrderService.objects.create(order=order, title=f"Л{i}", income=D("5"), expense=D("2"))
    errors = []
    barrier = threading.Barrier(4)

    def work():
        try:
            barrier.wait()
            migration.migrate_order(Order.all_objects.get(pk=order.pk), overwrite=True)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=work) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    with tenant_context(company.id):
        assert Income.objects.filter(order=order).count() == 4  # база + 3 строки
        assert Expense.objects.filter(source="migrated").count() == 3
        assert ExpenseAllocation.objects.filter(legacy_line__isnull=False).count() == 3
    assert ex and first_user


def test_set_allocations_keeps_legacy_line_of_unchanged_allocations(admin_client, company):
    set_engine(company, "shadow")
    order = new_order(company, "0")
    other = new_order(company, "0")
    pk = post_line(admin_client, order, income="0", expense="40", title="Склад")
    (exp,) = expenses(company, legacy_group_key=f"line:{pk}")
    user = first_user(company)
    with tenant_context(company.id):
        alloc_id = ExpenseAllocation.objects.get(legacy_line_id=pk).pk
        ex.set_allocations(exp, [{"order": order, "amount": "30"}], user=user)
        got = ExpenseAllocation.objects.get(expense=exp)
        assert got.pk == alloc_id and got.legacy_line_id == pk and got.amount == D("30.00")
        ex.set_allocations(
            exp, [{"order": order, "amount": "30"}, {"order": other, "amount": "10"}], user=user
        )
        assert ExpenseAllocation.objects.get(pk=alloc_id).legacy_line_id == pk
        assert ExpenseAllocation.objects.filter(expense=exp).count() == 2
        ex.set_allocations(exp, [{"order": other, "amount": "10"}], user=user)
        assert not ExpenseAllocation.objects.filter(pk=alloc_id).exists()  # убранная доля удалена
