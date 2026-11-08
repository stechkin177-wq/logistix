"""Этап 1.5-E1: правило признания дохода R-1 (addendum v1.1, разд. 4 и 9)."""

from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal as D

import pytest

from apps.core.tenancy import tenant_context
from apps.finance import hooks
from apps.finance import income as inc
from apps.finance.models import Income, IncomeTrip
from apps.finance.tests.p2_helpers import enable_new, freight, move
from apps.forwarding.models import Consignment, ConsignmentPoint, Trip, TripConsignment
from apps.forwarding.tests.test_legs import leg, mk_trip, stops_of
from apps.forwarding.tests.test_tracking import (
    confirm,
    event,
    initiate,
    make_route_cargo,
    transfer_data,
)
from apps.forwarding.tracking import services as tr

pytestmark = pytest.mark.django_db
T1 = datetime(2026, 6, 1, 10, 0, tzinfo=dt_tz.utc)
T2 = datetime(2026, 6, 3, 10, 0, tzinfo=dt_tz.utc)
T3 = datetime(2026, 6, 5, 10, 0, tzinfo=dt_tz.utc)
T4 = datetime(2026, 6, 8, 10, 0, tzinfo=dt_tz.utc)


def setup_order(company, kinds=("load", "transfer", "unload"), rate="1000.00"):
    enable_new(company)
    order, c = make_route_cargo(company, kinds=kinds, client_rate=D(rate))
    return order, c, stops_of(company, c)


def state(company, order):
    with tenant_context(company.id):
        settings = inc.get_settings_for(company.id)
        return inc.recognition_state(type(order).all_objects.get(pk=order.pk), settings)


def codes(company, order):
    return sorted(b["code"] for b in state(company, order).blockers)


def status(order):
    (row,) = freight(order)
    return row.status


def test_second_leg_not_assigned_blocks_income_even_if_first_trip_completed(company):
    order, c, (s1, s2, s3) = setup_order(company)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    move(company, t1, "COMPLETED", T1)
    assert status(order) == "planned"
    assert "route_not_assigned" in codes(company, order)
    assert not state(company, order).ready


def test_cargo_in_storage_blocks_then_second_leg_and_delivery_recognize_once(company):
    order, c, (s1, s2, s3) = setup_order(company)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    move(company, t1, "COMPLETED", T1)
    confirm(company, initiate(company, c, transfer_data("to_storage", s2, from_trip=t1)))
    assert status(order) == "planned"
    with tenant_context(company.id):
        assert Consignment.objects.get(pk=c.pk).location_status == "in_storage"
    assert set(codes(company, order)) >= {"route_not_assigned"}
    # следующий рейс назначен и завершён -> признан один раз на дату последнего завершения
    t2 = mk_trip(company, legs=[leg(c, s2, s3)])
    assert status(order) == "planned"
    move(company, t2, "COMPLETED", T3)
    (row,) = freight(order)
    assert row.status == "recognized" and row.recognized_on == date(2026, 6, 5)
    assert row.amount == D("1000.00")
    with tenant_context(company.id):
        assert sorted(IncomeTrip.objects.filter(income=row).values_list("trip_id", flat=True)) == [
            t1.pk,
            t2.pk,
        ]
        assert Consignment.objects.get(pk=c.pk).location_status == "delivered"
    # повторное событие и повторные вызовы не создают второй доход
    stop = ConsignmentPoint.all_objects.get(pk=s3.pk)
    event(company, c, "delivered", stop, T4)
    event(company, c, "delivered", stop, T4)
    with tenant_context(company.id):
        hooks.after_trip_changed(Trip.objects.get(pk=t2.pk), None)
        hooks.after_consignment_changed(Consignment.objects.get(pk=c.pk), None)
        assert (
            Income.objects.filter(order=order, kind="freight").exclude(status="void").count() == 1
        )
    assert freight(order)[0].recognized_on == date(2026, 6, 5)


def test_from_storage_transfer_and_events_keep_income_blocked_until_completion(company):
    order, c, (s1, s2, s3) = setup_order(company)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    move(company, t1, "COMPLETED", T1)
    confirm(company, initiate(company, c, transfer_data("to_storage", s2, from_trip=t1)))
    t2 = mk_trip(company, legs=[leg(c, s2, s3)])
    confirm(company, initiate(company, c, transfer_data("from_storage", s2, to_trip=t2)))
    event(company, c, "arrived", ConsignmentPoint.all_objects.get(pk=s3.pk), T3)
    assert status(order) == "planned"  # рейс 2 ещё не завершён
    assert codes(company, order) == ["not_delivered", "trips_not_completed"]
    move(company, t2, "COMPLETED", T4)
    assert freight(order)[0].status == "recognized"
    assert freight(order)[0].recognized_on == date(2026, 6, 8)


def test_cancelled_trip_leg_removes_coverage_and_blocks_recognition(company):
    order, c, (s1, s2, s3) = setup_order(company)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    t2 = mk_trip(company, legs=[leg(c, s2, s3)])
    move(company, t1, "COMPLETED", T1)
    move(company, t2, "CANCELLED", T2)
    assert status(order) == "planned"
    assert codes(company, order) == ["not_delivered", "route_not_assigned"]
    t3 = mk_trip(company, legs=[leg(c, s2, s3)])  # новый рейс на отрезок
    move(company, t3, "COMPLETED", T3)
    (row,) = freight(order)
    assert row.status == "recognized" and row.recognized_on == date(2026, 6, 5)
    with tenant_context(company.id):
        assert (
            list(IncomeTrip.objects.filter(income=row).values_list("trip_id", flat=True)).count(
                t2.pk
            )
            == 0
        )


def test_cancelling_trip_of_recognized_income_returns_it_to_planned_when_leg_is_lost(company):
    order, c, (s1, s2, s3) = setup_order(company)
    t1 = mk_trip(company, legs=[leg(c, s1, s3)])
    move(company, t1, "COMPLETED", T1)
    assert status(order) == "recognized"
    move(company, t1, "CANCELLED", T2, can_revert=True, reason="ошибка")
    assert status(order) == "planned"
    assert len(freight(order)) == 1


def test_single_leg_cargo_keeps_old_behaviour(company):
    order, c, (s1, s2) = setup_order(company, kinds=("load", "unload"), rate="500.00")
    t1 = mk_trip(company, [c.pk])
    assert status(order) == "planned"
    move(company, t1, "COMPLETED", T1)
    (row,) = freight(order)
    assert row.status == "recognized" and row.recognized_on == date(2026, 6, 1)


def test_two_trips_two_carriers_recognized_after_both_on_last_date(company):
    order, c, (s1, s2, s3) = setup_order(company)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    t2 = mk_trip(company, legs=[leg(c, s2, s3)])
    assert t1.carrier_id != t2.carrier_id
    move(company, t2, "COMPLETED", T2)
    assert status(order) == "planned"
    move(company, t1, "COMPLETED", T3)
    (row,) = freight(order)
    assert row.status == "recognized" and row.recognized_on == date(2026, 6, 5)


def test_blockers_and_ready_use_one_predicate(company):
    order, c, (s1, s2, s3) = setup_order(company)
    t1 = mk_trip(company, legs=[leg(c, s1, s3)])
    with tenant_context(company.id):
        o = type(order).all_objects.get(pk=order.pk)
        settings = inc.get_settings_for(company.id)
        assert not inc.income_recognition_ready(o, settings)
        assert [b["code"] for b in inc.income_recognition_blockers(o, settings)] == [
            "trips_not_completed",
            "not_delivered",
        ]
    move(company, t1, "COMPLETED", T1)
    with tenant_context(company.id):
        assert inc.income_recognition_ready(type(order).all_objects.get(pk=order.pk), settings)
        assert (
            inc.income_recognition_blockers(type(order).all_objects.get(pk=order.pk), settings)
            == []
        )


def test_last_stop_done_satisfies_delivery_and_sets_date_of_last_event(company):
    """Ветка (в) «последняя остановка выполнена»: участок не помечен done, остановка - done."""
    order, c, (s1, s2) = setup_order(company, kinds=("load", "unload"))
    t1 = mk_trip(company, [c.pk])
    move(company, t1, "COMPLETED", T1)
    assert status(order) == "recognized"
    with tenant_context(company.id):  # имитация: участок не отмечен, но груз доставлен позже
        TripConsignment.objects.filter(trip=t1).update(status="planned")
        Income.objects.filter(order=order).update(status="planned", recognized_on=None)
        ConsignmentPoint.objects.filter(pk=s2.pk).update(status="done", done_at=T4)
    assert state(company, order).ready
    assert state(company, order).recognized_on(company.id) == date(2026, 6, 8)


def test_closed_period_blocks_recognition_and_rolls_back(company):
    from apps.finance import periods
    from apps.finance.errors import FinanceError
    from apps.finance.tests.helpers import first_user

    order, c, (s1, s2) = setup_order(company, kinds=("load", "unload"))
    t1 = mk_trip(company, [c.pk])
    with tenant_context(company.id):
        periods.close_period(company, 2026, 6, first_user(company))
    with pytest.raises(FinanceError):
        move(company, t1, "COMPLETED", T1)
    assert status(order) == "planned"
    with tenant_context(company.id):
        assert Trip.objects.get(pk=t1.pk).completed_at is None  # откат основной операции


def test_hooks_sleep_when_engine_is_not_new(company):
    order, c = make_route_cargo(company, kinds=("load", "unload"), client_rate=D("100.00"))
    t1 = mk_trip(company, [c.pk])
    move(company, t1, "COMPLETED", T1)
    with tenant_context(company.id):
        assert Income.objects.count() == 0  # legacy: финансовых записей нового движка нет
        tr.recompute_location(Consignment.objects.get(pk=c.pk))
