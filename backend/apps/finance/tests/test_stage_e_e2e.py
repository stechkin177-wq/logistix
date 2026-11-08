"""Этап 1.5-E4: сквозной сценарий engine=new - два рейса двух перевозчиков, склад без to_trip,
R-1, расходы на каждый рейс, методы распределения, прибыль заказа, закрытый период, права."""

from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal as D

import pytest

from apps.core.tenancy import tenant_context
from apps.finance import expenses as svc
from apps.finance import periods
from apps.finance.errors import FinanceError
from apps.finance.models import Expense, ExpenseAllocation, Income
from apps.finance.reports_new import order_totals_new
from apps.finance.tests.helpers import first_user
from apps.finance.tests.p2_helpers import enable_new, freight, move
from apps.forwarding.models import CargoTransfer, Consignment, ConsignmentPoint, Trip
from apps.forwarding.tests.test_legs import leg, mk_trip, stops_of
from apps.forwarding.tests.test_parties import client_with_role
from apps.forwarding.tests.test_tracking import (
    confirm,
    event,
    getc,
    initiate,
    make_route_cargo,
    transfer_data,
)

pytestmark = pytest.mark.django_db
T1 = datetime(2026, 6, 1, 10, 0, tzinfo=dt_tz.utc)
T2 = datetime(2026, 6, 4, 10, 0, tzinfo=dt_tz.utc)
T3 = datetime(2026, 6, 9, 10, 0, tzinfo=dt_tz.utc)


def location(company, c):
    with tenant_context(company.id):
        return Consignment.objects.get(pk=c.pk).location_status


def set_price(company, trip, price):
    with tenant_context(company.id):
        Trip.objects.filter(pk=trip.pk).update(carrier_price=D(price))


def test_two_carriers_storage_without_trip_delivery_and_profit(company):
    enable_new(company)
    order, c = make_route_cargo(company, client_rate=D("1000.00"))
    _, other = make_route_cargo(company, kinds=("load", "unload"), client_rate=D("500.00"))
    s1, s2, s3 = stops_of(company, c)
    o1, o2 = stops_of(company, other)
    # рейс 1 (перевозчик A) везёт груз до склада и груз другого заказа целиком (сборный)
    t1 = mk_trip(company, legs=[leg(c, s1, s2), leg(other, o1, o2)])
    set_price(company, t1, "300.00")
    user = first_user(company)

    # расходы: на каждый рейс отдельно
    with tenant_context(company.id):
        e1 = svc.create_carrier_expense(
            Trip.objects.get(pk=t1.pk), user=user, allocation_method="proportional"
        )
    assert e1.allocation_method == "proportional"

    # 1. первый рейс завершён, груз передан на склад (без to_trip): доход не признан
    move(company, t1, "COMPLETED", T1)
    confirm(company, initiate(company, c, transfer_data("to_storage", s2, from_trip=t1)))
    assert location(company, c) == "in_storage"
    assert [i.status for i in freight(order)] == ["planned"]
    with tenant_context(company.id):
        assert Trip.objects.count() == 1  # фиктивный рейс не создан
        assert CargoTransfer.objects.filter(to_trip__isnull=True).count() == 1

    # 2. второй участок назначен на рейс другого перевозчика, груз взят со склада
    t2 = mk_trip(company, legs=[leg(c, s2, s3)])
    set_price(company, t2, "200.50")
    assert t1.carrier_id != t2.carrier_id
    confirm(company, initiate(company, c, transfer_data("from_storage", s2, to_trip=t2)))
    assert [i.status for i in freight(order)] == ["planned"]
    with tenant_context(company.id):
        e2 = svc.create_carrier_expense(Trip.objects.get(pk=t2.pk), user=user)
        assert Expense.objects.filter(kind="carrier_transport", status="active").count() == 2

    # 3. рейс 2 завершён и груз доставлен: доход признан один раз на дату последнего события
    event(company, c, "arrived", ConsignmentPoint.all_objects.get(pk=s3.pk), T2)
    move(company, t2, "COMPLETED", T3)
    event(company, c, "delivered", ConsignmentPoint.all_objects.get(pk=s3.pk), T3)
    event(company, c, "delivered", ConsignmentPoint.all_objects.get(pk=s3.pk), T3)  # повтор
    (row,) = freight(order)
    assert row.status == "recognized" and row.recognized_on == date(2026, 6, 9)
    assert location(company, c) == "delivered"
    with tenant_context(company.id):
        assert (
            Income.objects.filter(order=order, kind="freight").exclude(status="void").count() == 1
        )

    # 4. прибыль заказа суммируется по рейсам обоих перевозчиков; доля расхода учитывается один раз
    with tenant_context(company.id):
        o = type(order).all_objects.get(pk=order.pk)
        shares = ExpenseAllocation.objects.filter(order=o, expense__status="active")
        assert sorted(a.expense_id for a in shares) == sorted([e1.pk, e2.pk])
        totals = order_totals_new(o)
        # рейс 1: вес груза 1000 и 1000 -> 150.00 заказу; рейс 2: 200.50 целиком
        assert sorted(a.amount for a in shares) == [D("150.00"), D("200.50")]
        assert totals["revenue"] == D("1000.00") and totals["cost"] == D("350.50")
        assert totals["profit"] == D("649.50")
        assert sum(a.amount for a in ExpenseAllocation.objects.filter(expense=e1)) == D("300.00")


def test_closed_period_blocks_final_recognition_and_nothing_is_half_done(company):
    enable_new(company)
    order, c = make_route_cargo(company, client_rate=D("100.00"))
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    t2 = mk_trip(company, legs=[leg(c, s2, s3)])
    move(company, t1, "COMPLETED", T1)
    with tenant_context(company.id):
        periods.close_period(company, 2026, 6, first_user(company))
    with pytest.raises(FinanceError):
        move(company, t2, "COMPLETED", T3)
    assert [i.status for i in freight(order)] == ["planned"]
    with tenant_context(company.id):
        assert Trip.objects.get(pk=t2.pk).completed_at is None


def test_driver_initiates_manager_confirms_via_api(company):
    from apps.core.models import Role

    enable_new(company)
    order, c = make_route_cargo(company)
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    with tenant_context(company.id):
        Role.objects.filter(name="Водитель").update(
            permissions=["consignments.view", "consignments.update"]
        )
    _, driver = client_with_role(company, "Водитель")
    r = driver.post(
        f"/api/consignments/{c.pk}/transfers/",
        {
            "transfer_kind": "to_storage",
            "to_stop": s2.pk,
            "from_trip": t1.pk,
            "source": "driver_app",
        },
        format="json",
    )
    assert r.status_code == 201 and r.data["source"] == "driver_app"
    assert driver.post(f"/api/transfers/{r.data['id']}/confirm/").status_code == 403
    _, dispatcher = client_with_role(company, "Диспетчер")
    assert dispatcher.post(f"/api/transfers/{r.data['id']}/confirm/").status_code == 200
    assert location(company, c) == "in_storage"
    assert getc(company, c).location_status == "in_storage"
