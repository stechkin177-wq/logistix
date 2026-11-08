"""Этап 1.5-E3: удаление/восстановление рейса и заказа, смена валюты рейса при engine=new."""

from datetime import datetime
from datetime import timezone as dt_tz
from decimal import Decimal as D

import pytest

from apps.core.tenancy import tenant_context
from apps.finance import expenses as svc
from apps.finance.models import Expense, Income, Invoice
from apps.finance.tests.helpers import cur, first_user, vat
from apps.finance.tests.p2_helpers import enable_new, freight, move, set_engine
from apps.forwarding.models import Order, Trip
from apps.forwarding.tests.test_legs import leg, mk_trip, stops_of
from apps.forwarding.tests.test_tracking import make_route_cargo

pytestmark = pytest.mark.django_db
T1 = datetime(2026, 6, 1, 10, 0, tzinfo=dt_tz.utc)


def setup(company, rate="1000.00", kinds=("load", "unload")):
    enable_new(company)
    order, c = make_route_cargo(company, kinds=kinds, client_rate=D(rate))
    trip = mk_trip(company, [c.pk])
    with tenant_context(company.id):
        Trip.objects.filter(pk=trip.pk).update(carrier_price=D("300.00"))
    return order, c, trip


def make_expense(company, trip):
    with tenant_context(company.id):
        return svc.create_carrier_expense(Trip.objects.get(pk=trip.pk), user=first_user(company))


def trip_url(trip, tail=""):
    return f"/api/trips/{trip.pk}/{tail}"


def order_url(order, tail=""):
    return f"/api/orders/{order.pk}/{tail}"


def test_trip_with_active_expense_cannot_be_deleted_until_voided(admin_client, company):
    order, c, trip = setup(company)
    e = make_expense(company, trip)
    r = admin_client.delete(trip_url(trip))
    assert r.status_code == 409 and r.data["code"] == "trip_has_expense"
    with tenant_context(company.id):
        assert Trip.objects.filter(pk=trip.pk).exists()
        svc.void_expense(Expense.objects.get(pk=e.pk), user=first_user(company), reason="тест")
    assert admin_client.delete(trip_url(trip)).status_code == 204
    with tenant_context(company.id):
        assert not Trip.objects.filter(pk=trip.pk).exists()
        assert Trip.trash.filter(pk=trip.pk).exists()


def test_trip_delete_recalculates_recognition_and_location(admin_client, company):
    order, c, trip = setup(company)
    move(company, trip, "COMPLETED", T1)
    assert freight(order)[0].status == "recognized"
    assert admin_client.delete(trip_url(trip)).status_code == 204
    assert freight(order)[0].status == "planned"
    with tenant_context(company.id):
        from apps.forwarding.models import Consignment

        assert Consignment.objects.get(pk=c.pk).location_status == "planned"


def test_legacy_engine_trip_delete_is_untouched(admin_client, company):
    order, c, trip = setup(company)
    make_expense(company, trip)
    set_engine(company, "legacy")
    assert admin_client.delete(trip_url(trip)).status_code == 204


def test_trip_restore_checks_leg_conflicts_and_recalculates(admin_client, company):
    enable_new(company)
    _, c = make_route_cargo(company, kinds=("load", "unload"))
    s1, s2 = stops_of(company, c)
    a = mk_trip(company, legs=[leg(c, s1, s2, weight_kg=D("600"))])
    assert admin_client.delete(trip_url(a)).status_code == 204
    mk_trip(company, legs=[leg(c, s1, s2, weight_kg=D("700"))])  # место освободилось
    r = admin_client.post(f"/api/trash/trips/{a.pk}/restore/")
    assert r.status_code == 409 and "пересекаются" in r.data["detail"]
    with tenant_context(company.id):
        assert Trip.trash.filter(pk=a.pk).exists()


def test_trip_restore_without_conflict_works(admin_client, company):
    order, c, trip = setup(company)
    assert admin_client.delete(trip_url(trip)).status_code == 204
    assert admin_client.post(f"/api/trash/trips/{trip.pk}/restore/").status_code == 200


def test_order_with_planned_income_is_deleted_and_income_voided_then_restored(
    admin_client, company
):
    order, c, trip = setup(company)
    assert freight(order)[0].status == "planned"
    admin_client.delete(trip_url(trip))
    r = admin_client.delete(order_url(order))
    assert r.status_code == 204, r.content
    assert [i.status for i in freight(order)] == ["void"]
    r = admin_client.post(f"/api/trash/orders/{order.pk}/restore/")
    assert r.status_code == 200
    assert [i.status for i in freight(order)] == ["void", "planned"]  # новый плановый доход
    with tenant_context(company.id):
        assert (
            Income.objects.filter(order=order, kind="freight").exclude(status="void").count() == 1
        )


def test_order_with_recognized_income_is_blocked(admin_client, company):
    order, c, trip = setup(company)
    move(company, trip, "COMPLETED", T1)
    r = admin_client.delete(order_url(order))
    assert r.status_code == 409 and r.data["code"] == "order_has_finance"
    with tenant_context(company.id):
        assert Order.objects.filter(pk=order.pk).exists()
    assert freight(order)[0].status == "recognized"


def test_order_with_expense_allocations_is_blocked_and_nothing_is_voided(admin_client, company):
    order, c, trip = setup(company)
    make_expense(company, trip)
    r = admin_client.delete(order_url(order))
    assert r.status_code == 409 and r.data["code"] == "order_has_finance"
    assert freight(order)[0].status == "planned"  # транзакция откатилась целиком


def test_order_with_active_invoice_is_blocked(admin_client, company):
    order, c, trip = setup(company)
    with tenant_context(company.id):
        Invoice.objects.create(
            company=company,
            direction="out",
            client=order.client,
            order=order,
            currency=cur(company),
            vat_rate=vat(company),
            status="draft",
        )
    r = admin_client.delete(order_url(order))
    assert r.status_code == 409 and r.data["code"] == "order_has_finance"
    with tenant_context(company.id):
        Invoice.objects.filter(order=order).update(status="cancelled")
    admin_client.delete(trip_url(trip))
    assert admin_client.delete(order_url(order)).status_code == 204


def test_trip_currency_change_locked_while_expense_is_active(admin_client, company):
    order, c, trip = setup(company)
    e = make_expense(company, trip)
    usd = cur(company, "USD").pk
    r = admin_client.patch(trip_url(trip), {"currency": usd}, format="json")
    assert r.status_code == 409 and r.data["code"] == "trip_currency_locked"
    with tenant_context(company.id):
        assert Trip.objects.get(pk=trip.pk).currency_id == cur(company, "KZT").pk
        svc.void_expense(Expense.objects.get(pk=e.pk), user=first_user(company), reason="тест")
    assert admin_client.patch(trip_url(trip), {"currency": usd}, format="json").status_code == 200
