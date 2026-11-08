"""Этап 1.5-C: финансы не ломаются от участков (нет дублей при нескольких участках груза)."""

from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal as D

import pytest

from apps.core.tenancy import tenant_context
from apps.finance import expenses
from apps.finance import income as inc
from apps.finance.models import Income, IncomeTrip
from apps.finance.tests.p2_helpers import enable_new, freight, move
from apps.forwarding.models import Trip
from apps.forwarding.tests.test_legs import leg, make_cargos, mk_trip, stops_of

pytestmark = pytest.mark.django_db
T1 = datetime(2026, 6, 1, 10, 0, tzinfo=dt_tz.utc)
T2 = datetime(2026, 6, 3, 21, 0, tzinfo=dt_tz.utc)  # 4 июня 02:00 в Алматы
T3 = datetime(2026, 6, 5, 9, 0, tzinfo=dt_tz.utc)


def test_two_legs_of_one_cargo_in_one_trip_recognize_income_once(company):
    enable_new(company)
    order, (c,) = make_cargos(company, stops_per=4, client_rate=D("1000.00"))
    s1, s2, s3, s4 = stops_of(company, c)
    trip = mk_trip(company, legs=[leg(c, s1, s2), leg(c, s2, s4)])
    with tenant_context(company.id):
        assert [t.pk for t in inc.active_trips(order)] == [trip.pk]  # рейс один, без дублей
        assert expenses.trip_order_ids(Trip.objects.get(pk=trip.pk)) == [order.pk]
    move(company, trip, "COMPLETED", T2)
    rows = freight(order)
    assert len(rows) == 1 and rows[0].status == "recognized"
    assert rows[0].recognized_on == date(2026, 6, 4) and rows[0].amount == D("1000.00")
    with tenant_context(company.id):
        assert IncomeTrip.objects.filter(income=rows[0]).count() == 1
        assert (
            Income.objects.filter(order=order, kind="freight").exclude(status="void").count() == 1
        )
    # повторное событие (завершение уже завершённого / повторный пересчёт) второй доход не создаёт
    with tenant_context(company.id):
        from apps.finance import hooks

        hooks.after_trip_changed(Trip.objects.get(pk=trip.pk), None)
    assert len(freight(order)) == 1


def test_transfer_between_two_trips_recognizes_after_both_completed_on_last_date(company):
    """Действующее правило G1 (R-1 - этап E): доход после завершения всех действующих рейсов."""
    enable_new(company)
    order, (c,) = make_cargos(company, client_rate=D("500.00"))
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    t2 = mk_trip(company, legs=[leg(c, s2, s3)])
    move(company, t1, "COMPLETED", T1)
    assert freight(order)[0].status == "planned"
    move(company, t2, "COMPLETED", T3)
    (income,) = freight(order)
    assert income.status == "recognized" and income.recognized_on == date(2026, 6, 5)
    with tenant_context(company.id):
        assert sorted(
            IncomeTrip.objects.filter(income=income).values_list("trip_id", flat=True)
        ) == sorted([t1.pk, t2.pk])


def test_cancelled_trip_with_legs_does_not_block_recognition(company):
    enable_new(company)
    order, (c,) = make_cargos(company, client_rate=D("500.00"))
    s1, s2, s3 = stops_of(company, c)
    cancelled = mk_trip(company, legs=[leg(c, s1, s2)])
    move(company, cancelled, "CANCELLED", T1)
    done = mk_trip(company, legs=[leg(c, s1, s3)])
    move(company, done, "COMPLETED", T3)
    (income,) = freight(order)
    assert income.status == "recognized" and income.trip_id == done.pk
    with tenant_context(company.id):
        assert list(IncomeTrip.objects.filter(income=income).values_list("trip_id", flat=True)) == [
            done.pk
        ]
