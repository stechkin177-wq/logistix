from decimal import Decimal as D

import pytest

from apps.core.tenancy import tenant_context
from apps.finance import trip_expense as te
from apps.finance.errors import FinanceError
from apps.finance.tests.helpers import first_user, make_carrier
from apps.forwarding.finance_lines.models import OrderService
from apps.forwarding.finance_lines.services import order_totals
from apps.forwarding.tests.test_orders import make_order as fw_make_order
from apps.forwarding.tests.test_parties import client_with_role
from apps.forwarding.tests.test_trips import make_cargos, svc_create

pytestmark = pytest.mark.django_db


def code(exc):
    return exc.value.detail.code


def consolidated_trip(company, n=3, price="1000.00"):
    """Рейс из грузов n разных заказов одного клиента."""
    carrier = make_carrier(company)
    ids, orders = [], []
    for _ in range(n):
        order, cids = make_cargos(company, 1)
        orders.append(order)
        ids += cids
    trip = svc_create(company, ids, carrier=carrier, data={"carrier_price": D(price)})
    return trip, orders


def test_even_split_suggestion_sums_to_price(company):
    trip, orders = consolidated_trip(company, 3, "1000.00")
    with tenant_context(company.id):
        data = te.trip_expense_lines(trip)
    amounts = [a["amount"] for a in data["suggestion"]]
    assert amounts == [D("333.34"), D("333.33"), D("333.33")]
    assert sum(amounts) == D("1000.00")
    assert {o["order_id"] for o in data["orders"]} == {o.pk for o in orders}


def test_create_lines_sum_must_match(company):
    trip, orders = consolidated_trip(company, 2, "1000.00")
    user = first_user(company)
    bad = [
        {"order_id": orders[0].pk, "amount": D("400")},
        {"order_id": orders[1].pk, "amount": D("500")},
    ]
    with tenant_context(company.id):
        with pytest.raises(FinanceError) as exc:
            te.create_trip_expense(trip, bad, user=user)
    assert code(exc) == "allocation_mismatch"


def test_creates_lines_and_profit_reflects(company):
    trip, orders = consolidated_trip(company, 2, "1000.00")
    user = first_user(company)
    alloc = [
        {"order_id": orders[0].pk, "amount": D("600")},
        {"order_id": orders[1].pk, "amount": D("400")},
    ]
    with tenant_context(company.id):
        lines = te.create_trip_expense(trip, alloc, user=user)
        assert [ln.expense for ln in lines] == [D("600.00"), D("400.00")]
        assert all(ln.income == 0 and ln.category == "Перевозка" for ln in lines)
        assert order_totals(orders[0])["cost"] == D("600.00")


def test_order_not_in_trip(company):
    trip, orders = consolidated_trip(company, 1, "100.00")
    stranger = fw_make_order(company)
    user = first_user(company)
    with tenant_context(company.id):
        with pytest.raises(FinanceError) as exc:
            te.create_trip_expense(trip, [{"order_id": stranger.pk, "amount": D("100")}], user=user)
    assert code(exc) == "order_not_in_trip"


def test_duplicate_forbidden(company):
    trip, orders = consolidated_trip(company, 1, "100.00")
    user = first_user(company)
    alloc = [{"order_id": orders[0].pk, "amount": D("100")}]
    with tenant_context(company.id):
        te.create_trip_expense(trip, alloc, user=user)
        with pytest.raises(FinanceError) as exc:
            te.create_trip_expense(trip, alloc, user=user)
        assert OrderService.objects.filter(order=orders[0], category="Перевозка").count() == 1
    assert code(exc) == "expense_exists"


def test_currency_mismatch_between_trip_and_order(company):
    from apps.finance.tests.helpers import cur

    trip, orders = consolidated_trip(company, 1, "100.00")
    with tenant_context(company.id):
        trip.currency = cur(company, "USD")
        trip.save()
        with pytest.raises(FinanceError) as exc:
            te.create_trip_expense(
                trip, [{"order_id": orders[0].pk, "amount": D("100")}], user=first_user(company)
            )
    assert code(exc) == "currency_mismatch"


def test_api_permissions_and_flow(company, admin_client):
    trip, orders = consolidated_trip(company, 2, "1000.00")
    url = f"/api/finance/trips/{trip.pk}/expense-lines/"
    r = admin_client.get(url)
    assert r.status_code == 200 and len(r.data["suggestion"]) == 2
    # price - устаревший алиас, carrier_price - основное поле; значения совпадают
    assert r.data["trip"]["price"] == r.data["trip"]["carrier_price"] == "1000.00"
    _, manager = client_with_role(company, "Менеджер")
    assert manager.get(url).status_code == 200
    assert (
        manager.post(url, {"allocations": r.data["suggestion"]}, format="json").status_code == 403
    )
    r2 = admin_client.post(url, {"allocations": r.data["suggestion"]}, format="json")
    assert r2.status_code == 201, r2.content
    assert len(r2.data["lines"]) == 2
    r3 = admin_client.post(url, {"allocations": r.data["suggestion"]}, format="json")
    assert r3.status_code == 400 and r3.data["code"] == "expense_exists"
