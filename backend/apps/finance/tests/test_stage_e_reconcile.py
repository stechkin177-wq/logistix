"""Этап 1.5-E5: migrate_finance и reconcile_finance на данных с участками и передачами."""

from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal as D

import pytest

from apps.core.tenancy import tenant_context
from apps.finance import reconcile
from apps.finance.models import Expense, Income
from apps.finance.tests.helpers import add_line, make_order
from apps.finance.tests.test_migrate_finance import counts, run_cmd, snapshot
from apps.forwarding.models import Trip
from apps.forwarding.tests.test_legs import leg, mk_trip, stops_of
from apps.forwarding.tests.test_tracking import (
    confirm,
    initiate,
    make_route_cargo,
    transfer_data,
)

pytestmark = pytest.mark.django_db
D1, D2 = date(2026, 5, 10), date(2026, 6, 12)


def multi_leg_company(company):
    """engine=legacy: заказ с многоточечным маршрутом, два рейса двух перевозчиков (участки),
    передача на склад; строки расхода «Перевозка» по рейсам; обычный заказ с услугой."""
    order, c = make_route_cargo(company, client_rate=D("1000"))
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    t2 = mk_trip(company, legs=[leg(c, s2, s3)])
    with tenant_context(company.id):
        Trip.objects.filter(pk=t1.pk).update(carrier_price=D("300.00"))
        Trip.objects.filter(pk=t2.pk).update(carrier_price=D("200.00"))
        from apps.forwarding.finance_lines.models import OrderService
        from apps.forwarding.finance_lines.services import sync_base_line
        from apps.forwarding.models import Order

        sync_base_line(Order.all_objects.get(pk=order.pk))
        OrderService.objects.filter(order=order, is_base=True).update(date=D1)
    confirm(company, initiate(company, c, transfer_data("to_storage", s2, from_trip=t1)))
    add_line(
        company, order, expense=300, title=f"Перевозка {t1.number}", day=D1, category="Перевозка"
    )
    add_line(
        company, order, expense=200, title=f"Перевозка {t2.number}", day=D2, category="Перевозка"
    )
    other = make_order(company)
    add_line(company, other, income=50, expense=10, title="Услуга", day=D2)
    return order, t1, t2


def test_migrate_and_reconcile_with_legs_has_zero_discrepancies(company):
    order, t1, t2 = multi_leg_company(company)
    run_cmd(company)
    run = reconcile.reconcile(company.id)
    assert run.status == "success", run.summary["findings"]
    assert run.summary["unexplained"] == 0
    with tenant_context(company.id):
        migrated = Expense.objects.filter(source="migrated")
        assert migrated.count() >= 2
        assert set(migrated.values_list("allocation_method", flat=True)) == {"manual"}
        assert (
            Income.objects.filter(order=order, kind="freight").exclude(status="void").count() == 1
        )


def test_migrate_is_idempotent_with_legs_and_reconcile_is_read_only(company):
    multi_leg_company(company)
    run_cmd(company)
    first = (snapshot(company), counts(company))
    run_cmd(company)  # повтор
    assert (snapshot(company), counts(company)) == first
    before = (snapshot(company), {**counts(company), "issues": 0})
    run = reconcile.reconcile(company.id)
    assert run.status == "success"
    assert (snapshot(company), {**counts(company), "issues": 0}) == before


def test_cutover_rule_applies_r1_to_orders_with_unassigned_legs(company):
    """Правило переключения (пересчёт признания) использует тот же предикат R-1: завершённый первый
    рейс при непокрытом втором отрезке доход не признаёт; после второго рейса - признаёт."""
    from apps.finance import switching
    from apps.finance.tests.helpers import first_user
    from apps.finance.tests.p2_helpers import move

    order, t1, t2 = multi_leg_company(company)
    move(company, t1, "COMPLETED", datetime(2026, 6, 1, 10, 0, tzinfo=dt_tz.utc))
    run_cmd(company)

    def counters():
        with tenant_context(company.id):
            return switching.apply_cutover_rule(
                company,
                date(2026, 5, 1),
                user=first_user(company),
                approval_ref="тест",
                write=False,
            )

    assert counters()["recognized"] == 0
    move(company, t2, "COMPLETED", datetime(2026, 6, 5, 10, 0, tzinfo=dt_tz.utc))
    assert counters()["recognized"] == 1  # оба рейса завершены, все отрезки покрыты
