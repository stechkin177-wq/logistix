"""Режим legacy: заказ 250 000, рейс привлечённого перевозчика 180 000, расход перевозчику.

Сценарий заказчика: доход 250 000, расход перевозчику 180 000, прибыль до прочих расходов 70 000,
маржа 28 %. Расход не учитывается дважды, отражается в сводке и связан с заказом.
"""

from decimal import Decimal as D

import pytest

from apps.core.tenancy import tenant_context
from apps.finance.tests.helpers import make_carrier
from apps.forwarding.finance_lines.models import OrderService
from apps.forwarding.tests.test_trips import make_cargos, svc_create

pytestmark = pytest.mark.django_db


@pytest.fixture
def scenario(company, admin_client):
    order, ids = make_cargos(company, 1, client_rate=D("250000"))
    carrier = make_carrier(company, "Привлечённый перевозчик")
    trip = svc_create(company, ids, carrier=carrier, data={"carrier_price": D("180000")})
    return order, trip


def totals(client, order):
    """Итоги заказа по строкам (доход, расход, прибыль) из API."""
    data = client.get(f"/api/orders/{order.pk}/").json()
    return data


def lines(company, order):
    with tenant_context(company.id):
        return list(OrderService.objects.filter(order=order).order_by("id"))


def summary(client):
    return client.get("/api/finance/summary/").json()


def test_before_expense_trip_price_is_not_counted_in_legacy(company, admin_client, scenario):
    """Цена рейса сама по себе в расходы legacy не попадает: расход вносится явно."""
    order, trip = scenario
    rows = lines(company, order)
    assert [(ln.is_base, ln.income, ln.expense) for ln in rows] == [(True, D("250000"), D("0"))]
    s = summary(admin_client)
    assert D(s["month_profit_kzt"]) == D("250000.00") and D(s["month_margin_pct"]) == D("100.00")


def test_manual_expense_line_gives_70000_profit_and_28_percent_margin(
    company, admin_client, scenario
):
    order, trip = scenario
    r = admin_client.post(
        "/api/order-lines/",
        {"order": order.pk, "title": "Оплата перевозчику", "category": "Перевозка",
         "expense": "180000.00"},
        format="json",
    )  # fmt: skip
    assert r.status_code == 201, r.content
    rows = lines(company, order)
    assert sum(ln.income for ln in rows) == D("250000")
    assert sum(ln.expense for ln in rows) == D("180000")
    # расход связан с заказом (строка заказа) и виден в карточке заказа
    assert rows[-1].order_id == order.pk and rows[-1].expense == D("180000")
    s = summary(admin_client)
    assert D(s["month_profit_kzt"]) == D("70000.00")
    assert D(s["month_margin_pct"]) == D("28.00")
    # не дважды: рейс остаётся данными (долг перевозчику), в доходы/расходы сводки не добавляется
    assert D(s["month_profit_kzt"]) != D("-110000.00")


def test_official_way_trip_expense_gives_same_result_and_blocks_second_press(
    company, admin_client, scenario
):
    """Штатное действие «расход рейса»: сумма равна цене рейса, строка связана с заказом и рейсом,
    повторное нажатие отклоняется (expense_exists)."""
    order, trip = scenario
    body = {"allocations": [{"order_id": order.pk, "amount": "180000.00"}]}
    first = admin_client.post(f"/api/finance/trips/{trip.pk}/expense-lines/", body, format="json")
    assert first.status_code == 201, first.content
    s = summary(admin_client)
    assert D(s["month_profit_kzt"]) == D("70000.00") and D(s["month_margin_pct"]) == D("28.00")
    again = admin_client.post(f"/api/finance/trips/{trip.pk}/expense-lines/", body, format="json")
    assert again.status_code == 400 and again.json()["code"] == "expense_exists"
    assert D(summary(admin_client)["month_profit_kzt"]) == D("70000.00")
    row = lines(company, order)[-1]
    assert row.title == f"Перевозка {trip.number}" and row.category == "Перевозка"


def test_wrong_amount_is_rejected_for_official_way(company, admin_client, scenario):
    order, trip = scenario
    body = {"allocations": [{"order_id": order.pk, "amount": "170000.00"}]}
    r = admin_client.post(f"/api/finance/trips/{trip.pk}/expense-lines/", body, format="json")
    assert r.status_code == 400 and r.json()["code"] == "allocation_mismatch"


def test_known_limit_manual_line_plus_official_button_would_count_twice(
    company, admin_client, scenario
):
    """Ограничение legacy: защита от двойного расхода работает по названию строки рейса.

    Ручная строка с другим названием и кнопка «расход рейса» дают 360 000: нужен один способ."""
    order, trip = scenario
    admin_client.post(
        "/api/order-lines/",
        {"order": order.pk, "title": "Оплата перевозчику", "expense": "180000.00"},
        format="json",
    )
    body = {"allocations": [{"order_id": order.pk, "amount": "180000.00"}]}
    admin_client.post(f"/api/finance/trips/{trip.pk}/expense-lines/", body, format="json")
    assert D(summary(admin_client)["month_profit_kzt"]) == D("-110000.00")
