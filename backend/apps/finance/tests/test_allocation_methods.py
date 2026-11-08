"""Этап 1.5-E2: Expense.allocation_method (equal | proportional | manual)."""

import importlib
from decimal import Decimal as D

import pytest
from django.apps import apps as django_apps
from django.db import connection

from apps.core.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.finance import expenses as svc
from apps.finance.errors import FinanceError
from apps.finance.models import Expense, ExpenseAllocation
from apps.finance.tests.helpers import first_user
from apps.finance.tests.p2_helpers import enable_new
from apps.forwarding.models import Consignment, Trip
from apps.forwarding.tests.test_legs import leg, mk_trip, stops_of
from apps.forwarding.tests.test_tracking import make_route_cargo

pytestmark = pytest.mark.django_db
migration = importlib.import_module("apps.finance.migrations.0011_expense_allocation_method")
KINDS = ("load", "unload")


def build(company, weights, price="100.00", volumes=None, pallets=None, shares=None):
    """Рейс с грузами разных заказов; weights - вес груза каждого заказа."""
    enable_new(company)
    cargos = []
    for i, w in enumerate(weights):
        _, c = make_route_cargo(company, kinds=KINDS, weight=1000)
        with tenant_context(company.id):
            Consignment.objects.filter(pk=c.pk).update(
                weight_kg=w,
                volume_m3=(volumes or [10] * len(weights))[i],
                pallets=(pallets or [10] * len(weights))[i],
            )
        cargos.append(c)
    legs = []
    for i, c in enumerate(cargos):
        a, b = stops_of(company, c)
        legs.append(leg(c, a, b, **((shares or {}).get(i) or {})))
    trip = mk_trip(company, legs=legs)
    with tenant_context(company.id):
        Trip.objects.filter(pk=trip.pk).update(carrier_price=D(price))
    return trip, cargos


def expense(company, trip, **kw):
    with tenant_context(company.id):
        return svc.create_carrier_expense(
            Trip.objects.get(pk=trip.pk), user=first_user(company), **kw
        )


def rows(company, exp):
    with tenant_context(company.id):
        return [
            (a.order_id, a.amount)
            for a in ExpenseAllocation.objects.filter(expense=exp).order_by("order_id")
        ]


def amounts(company, exp):
    return [a for _, a in rows(company, exp)]


def test_equal_is_default_and_cents_go_first(company):
    trip, _ = build(company, [1000, 2000, 1000])
    e = expense(company, trip)
    assert e.allocation_method == "equal"
    assert amounts(company, e) == [D("33.34"), D("33.33"), D("33.33")]


def test_proportional_by_weight_largest_remainder(company):
    trip, _ = build(company, [1000, 2000, 1000], price="100.01")
    e = expense(company, trip, allocation_method="proportional")
    assert e.allocation_method == "proportional"
    assert amounts(company, e) == [D("25.00"), D("50.01"), D("25.00")]
    assert sum(amounts(company, e)) == D("100.01")


def test_proportional_equal_weights_cent_to_first(company):
    trip, _ = build(company, [500, 500, 500], price="100.00")
    e = expense(company, trip, allocation_method="proportional")
    assert amounts(company, e) == [D("33.34"), D("33.33"), D("33.33")]


def test_zero_weight_order_gets_no_share_but_total_is_kept(company):
    trip, cargos = build(company, [0, 2000, 1000], price="90.00")
    e = expense(company, trip, allocation_method="proportional")
    got = rows(company, e)
    assert [a for _, a in got] == [D("60.00"), D("30.00")]
    assert sum(a for _, a in got) == D("90.00")


def test_fallback_volume_then_pallets_then_equal(company):
    trip, _ = build(company, [0, 0, 0], price="100.00", volumes=[1, 1, 2])
    assert amounts(company, expense(company, trip, allocation_method="proportional")) == [
        D("25.00"),
        D("25.00"),
        D("50.00"),
    ]
    trip2, _ = build(company, [0, 0, 0], price="100.00", volumes=[0, 0, 0], pallets=[3, 1, 0])
    assert amounts(company, expense(company, trip2, allocation_method="proportional")) == [
        D("75.00"),
        D("25.00"),
    ]
    trip3, _ = build(company, [0, 0, 0], price="100.00", volumes=[0, 0, 0], pallets=[0, 0, 0])
    assert amounts(company, expense(company, trip3, allocation_method="proportional")) == [
        D("33.34"),
        D("33.33"),
        D("33.33"),
    ]


def test_leg_share_is_used_instead_of_cargo_weight(company):
    trip, _ = build(company, [1000, 1000], price="130.00", shares={0: {"weight_kg": D("300")}})
    e = expense(company, trip, allocation_method="proportional")
    assert amounts(company, e) == [D("30.00"), D("100.00")]


def test_two_legs_of_one_cargo_in_trip_count_once(company):
    enable_new(company)
    _, a = make_route_cargo(company, kinds=("load", "transit", "unload"), weight=1000)
    _, b = make_route_cargo(company, kinds=KINDS, weight=1000)
    a1, a2, a3 = stops_of(company, a)
    b1, b2 = stops_of(company, b)
    trip = mk_trip(company, legs=[leg(a, a1, a2), leg(a, a2, a3), leg(b, b1, b2)])
    with tenant_context(company.id):
        Trip.objects.filter(pk=trip.pk).update(carrier_price=D("100.00"))
    e = expense(company, trip, allocation_method="proportional")
    assert amounts(company, e) == [D("50.00"), D("50.00")]


def test_explicit_allocations_mean_manual_and_conflicts_are_rejected(company):
    trip, cargos = build(company, [1000, 1000], price="100.00")
    with tenant_context(company.id):
        orders = [c.order_id for c in Consignment.objects.filter(pk__in=[c.pk for c in cargos])]
    items = [
        {"order": orders[0], "amount": "70.00"},
        {"order": orders[1], "amount": "30.00"},
    ]
    with pytest.raises(FinanceError) as err:
        expense(company, trip, allocations=items, allocation_method="proportional")
    assert err.value.detail.code == "allocation_method_conflict"
    with pytest.raises(FinanceError):
        expense(company, trip, allocation_method="manual")
    with pytest.raises(FinanceError) as err:
        expense(company, trip, allocation_method="bogus")
    assert err.value.detail.code == "allocation_method_invalid"
    e = expense(company, trip, allocations=items)
    assert e.allocation_method == "manual" and amounts(company, e) == [D("70.00"), D("30.00")]


def test_reallocate_switches_methods_and_keeps_invariants(company):
    trip, _ = build(company, [1000, 3000], price="100.00")
    e = expense(company, trip)
    assert amounts(company, e) == [D("50.00"), D("50.00")]
    user = first_user(company)
    with tenant_context(company.id):
        e = svc.reallocate(Expense.objects.get(pk=e.pk), "proportional", user=user)
    assert e.allocation_method == "proportional"
    assert amounts(company, e) == [D("25.00"), D("75.00")]
    with tenant_context(company.id):
        e = svc.reallocate(Expense.objects.get(pk=e.pk), "manual", user=user)
        assert e.allocation_method == "manual"
    assert amounts(company, e) == [D("25.00"), D("75.00")]  # суммы не тронуты
    with tenant_context(company.id):
        e = svc.reallocate(Expense.objects.get(pk=e.pk), "equal", user=user)
    assert amounts(company, e) == [D("50.00"), D("50.00")]
    assert sum(amounts(company, e)) == e.amount
    with tenant_context(company.id):
        logged = AuditLog.objects.filter(object_type="finance.expense", object_id=e.pk)
        assert any("allocation_method" in row.changes for row in logged)
        with pytest.raises(FinanceError):
            svc.reallocate(Expense.objects.get(pk=e.pk), "weird", user=user)


def test_set_allocations_makes_method_manual(company):
    trip, cargos = build(company, [1000, 1000], price="100.00")
    e = expense(company, trip)
    with tenant_context(company.id):
        orders = sorted(
            c.order_id for c in Consignment.objects.filter(pk__in=[c.pk for c in cargos])
        )
        e = svc.set_allocations(
            Expense.objects.get(pk=e.pk),
            [{"order": orders[0], "amount": "10.00"}, {"order": orders[1], "amount": "90.00"}],
            user=first_user(company),
        )
    assert e.allocation_method == "manual"


def test_price_sync_keeps_the_method(company):
    user = first_user(company)
    for method, price, expected in (
        ("proportional", "250.55", [D("62.64"), D("187.91")]),
        ("equal", "250.55", [D("125.28"), D("125.27")]),
    ):
        trip, _ = build(company, [1000, 3000], price="100.00")
        expense(company, trip, allocation_method=method)
        with tenant_context(company.id):
            Trip.objects.filter(pk=trip.pk).update(carrier_price=D(price))
            e2 = svc.sync_trip_expense(Trip.objects.get(pk=trip.pk), user=user)
        assert e2.allocation_method == method and e2.amount == D(price)
        assert amounts(company, e2) == expected, method
        assert sum(amounts(company, e2)) == D(price)


def test_price_sync_manual_keeps_previous_proportions(company):
    trip, cargos = build(company, [1000, 1000], price="100.00")
    with tenant_context(company.id):
        orders = sorted(
            c.order_id for c in Consignment.objects.filter(pk__in=[c.pk for c in cargos])
        )
    e = expense(
        company,
        trip,
        allocations=[
            {"order": orders[0], "amount": "20.00"},
            {"order": orders[1], "amount": "80.00"},
        ],
    )
    with tenant_context(company.id):
        Trip.objects.filter(pk=trip.pk).update(carrier_price=D("200.00"))
        e = svc.sync_trip_expense(Trip.objects.get(pk=trip.pk), user=first_user(company))
    assert e.allocation_method == "manual"
    assert amounts(company, e) == [D("40.00"), D("160.00")]


def test_equal_with_custom_previous_split_does_not_lose_proportions(company):
    """Метод equal по умолчанию у старых расходов: вручную заданные доли не выравниваются."""
    trip, cargos = build(company, [1000, 1000], price="100.00")
    e = expense(company, trip)
    with tenant_context(company.id):
        a = list(ExpenseAllocation.objects.filter(expense=e).order_by("order_id"))
        ExpenseAllocation.objects.filter(pk=a[0].pk).update(amount=D("20.00"))
        ExpenseAllocation.objects.filter(pk=a[1].pk).update(amount=D("80.00"))
        Trip.objects.filter(pk=trip.pk).update(carrier_price=D("200.00"))
        e = svc.sync_trip_expense(Trip.objects.get(pk=trip.pk), user=first_user(company))
    assert amounts(company, e) == [D("40.00"), D("160.00")]


def test_no_double_counting_in_any_grouping(company):
    trip, _ = build(company, [1000, 2000, 3000], price="100.01")
    e = expense(company, trip, allocation_method="proportional")
    with tenant_context(company.id):
        allocs = list(ExpenseAllocation.objects.filter(expense=e))
        assert sum(a.amount for a in allocs) == e.amount == D("100.01")
        by_order, by_trip = {}, {}
        for a in allocs:
            by_order[a.order_id] = by_order.get(a.order_id, D(0)) + a.amount
            by_trip[a.trip_id] = by_trip.get(a.trip_id, D(0)) + a.amount
        assert sum(by_order.values()) == sum(by_trip.values()) == e.amount
        assert len({(a.order_id, a.trip_id) for a in allocs}) == len(allocs)  # доля одна


def test_each_trip_has_own_expense_and_order_profit_sums_trips(company):
    from apps.finance.reports_new import order_totals_new as totals

    enable_new(company)
    order, c = make_route_cargo(
        company, kinds=("load", "transit", "unload"), client_rate=D("1000.00")
    )
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    t2 = mk_trip(company, legs=[leg(c, s2, s3)])
    with tenant_context(company.id):
        Trip.objects.filter(pk=t1.pk).update(carrier_price=D("300.00"))
        Trip.objects.filter(pk=t2.pk).update(carrier_price=D("200.50"))
    e1, e2 = expense(company, t1), expense(company, t2)
    assert e1.pk != e2.pk and e1.carrier_id != e2.carrier_id
    with tenant_context(company.id):
        t = totals(type(order).all_objects.get(pk=order.pk))
    assert t["cost"] == D("500.50")


def test_data_migration_sets_manual_for_migrated_only(company):
    trip, _ = build(company, [1000, 1000])
    e = expense(company, trip)
    with tenant_context(company.id):
        Expense.objects.filter(pk=e.pk).update(source="migrated", allocation_method="equal")
        other = Expense.objects.get(pk=e.pk)
    assert other.allocation_method == "equal"
    migration.run_backfill(django_apps, connection)
    migration.run_backfill(django_apps, connection)  # повтор безопасен
    with tenant_context(company.id):
        assert Expense.objects.get(pk=e.pk).allocation_method == "manual"
        Expense.objects.filter(pk=e.pk).update(
            source="carrier_price_sync", allocation_method="equal"
        )
    migration.run_backfill(django_apps, connection)
    with tenant_context(company.id):
        assert Expense.objects.get(pk=e.pk).allocation_method == "equal"


def test_api_method_in_response_and_reallocate(admin_client, company):
    trip, _ = build(company, [1000, 3000], price="100.00")
    r = admin_client.post(
        f"/api/finance/trips/{trip.pk}/carrier-expense/",
        {"allocation_method": "proportional"},
        format="json",
    )
    assert r.status_code == 201, r.content
    exp = r.data["expense"]
    assert exp["allocation_method"] == "proportional"
    assert [a["amount"] for a in exp["allocations"]] == ["25.00", "75.00"]
    url = f"/api/finance/expenses/{exp['id']}/reallocate/"
    r = admin_client.post(url, {"method": "equal"}, format="json")
    assert r.status_code == 200 and r.data["allocation_method"] == "equal"
    assert [a["amount"] for a in r.data["allocations"]] == ["50.00", "50.00"]
    assert admin_client.post(url, {"method": "x"}, format="json").status_code == 400
    assert (
        admin_client.get(f"/api/finance/expenses/{exp['id']}/").data["allocation_method"] == "equal"
    )
    bad = admin_client.post(
        f"/api/finance/trips/{trip.pk}/carrier-expense/",
        {"allocation_method": "nope"},
        format="json",
    )
    assert bad.status_code == 400
