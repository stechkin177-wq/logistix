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


def expense_url(trip):
    return f"/api/finance/trips/{trip.pk}/expense-lines/"


def button_body(order, amount="180000.00"):
    return {"allocations": [{"order_id": order.pk, "amount": amount}]}


def test_manual_line_with_any_title_blocks_the_button(company, admin_client, scenario):
    """Ручная оплата перевозчику (название и категория любые) не должна дублироваться кнопкой."""
    order, trip = scenario
    admin_client.post(
        "/api/order-lines/",
        {"order": order.pk, "title": "Совсем другое название", "expense": "180000.00"},
        format="json",
    )
    r = admin_client.post(expense_url(trip), button_body(order), format="json")
    assert r.status_code == 400 and r.json()["code"] == "manual_carrier_expense_exists"
    assert D(summary(admin_client)["month_profit_kzt"]) == D("70000.00")
    hint = admin_client.get(expense_url(trip)).json()
    assert [m["title"] for m in hint["manual_unlinked"]] == ["Совсем другое название"]
    # категория «Перевозка» блокирует и при другой сумме
    other = admin_client.post(
        "/api/order-lines/",
        {"order": order.pk, "title": "Аванс", "category": "перевозка", "expense": "50000.00"},
        format="json",
    )
    assert other.status_code == 201
    assert (
        admin_client.post(expense_url(trip), button_body(order), format="json").status_code == 400
    )


def test_manual_line_linked_to_trip_is_the_trip_expense(company, admin_client, scenario):
    order, trip = scenario
    r = admin_client.post(
        "/api/order-lines/",
        {
            "order": order.pk, "title": "Оплата ИП Перевозчик",
            "expense": "180000.00", "trip": trip.pk,
        },
        format="json",
    )  # fmt: skip
    assert r.status_code == 201, r.content
    assert r.json()["trip"] == trip.pk and r.json()["trip_number"] == trip.number
    assert r.json()["category"] == "Перевозка"
    s = summary(admin_client)
    assert D(s["month_profit_kzt"]) == D("70000.00") and D(s["month_margin_pct"]) == D("28.00")
    # кнопка блокируется связью, а не названием; вторая ручная строка по тому же рейсу - тоже
    again = admin_client.post(expense_url(trip), button_body(order), format="json")
    assert again.status_code == 400 and again.json()["code"] == "expense_exists"
    dup = admin_client.post(
        "/api/order-lines/",
        {"order": order.pk, "title": "Ещё раз", "expense": "180000.00", "trip": trip.pk},
        format="json",
    )
    assert dup.status_code == 400 and "trip" in dup.json()
    assert D(summary(admin_client)["month_profit_kzt"]) == D("70000.00")
    # удалили строку - расход можно создать снова (учёт одного платежа не двоится)
    admin_client.delete(f"/api/order-lines/{r.json()['id']}/")
    assert (
        admin_client.post(expense_url(trip), button_body(order), format="json").status_code == 201
    )
    assert D(summary(admin_client)["month_profit_kzt"]) == D("70000.00")


def test_renaming_the_trip_line_does_not_unblock_the_button(company, admin_client, scenario):
    order, trip = scenario
    first = admin_client.post(expense_url(trip), button_body(order), format="json")
    line = first.json()["lines"][0]["id"]
    admin_client.patch(f"/api/order-lines/{line}/", {"title": "Переименовано"}, format="json")
    again = admin_client.post(expense_url(trip), button_body(order), format="json")
    assert again.status_code == 400 and again.json()["code"] == "expense_exists"
    assert D(summary(admin_client)["month_profit_kzt"]) == D("70000.00")


def test_trip_link_must_belong_to_the_order_and_be_an_expense(company, admin_client, scenario):
    order, trip = scenario
    other_order, _ = make_cargos(company, 1, client_rate=D("1000"))
    wrong = admin_client.post(
        "/api/order-lines/",
        {"order": other_order.pk, "title": "x", "expense": "10.00", "trip": trip.pk},
        format="json",
    )
    assert wrong.status_code == 400 and "trip" in wrong.json()
    income = admin_client.post(
        "/api/order-lines/",
        {"order": order.pk, "title": "x", "income": "10.00", "trip": trip.pk},
        format="json",
    )
    assert income.status_code == 400 and "trip" in income.json()


@pytest.mark.django_db(transaction=True)
def test_concurrent_and_repeated_presses_create_exactly_one_expense(
    company, admin_client, scenario
):
    """Двойное нажатие и параллельные запросы: один расход, остальные отклонены."""
    import threading

    from rest_framework.test import APIClient

    order, trip = scenario
    token = admin_client._credentials["HTTP_AUTHORIZATION"]
    results = []

    def press():
        from django.db import connections

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=token)
        try:
            results.append(
                client.post(expense_url(trip), button_body(order), format="json").status_code
            )
        finally:
            connections.close_all()  # соединение потока не должно мешать удалению тестовой БД

    threads = [threading.Thread(target=press) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [201, 400, 400, 400, 400, 400]
    carrier_lines = [ln for ln in lines(company, order) if ln.trip_id == trip.pk]
    assert len(carrier_lines) == 1 and carrier_lines[0].expense == D("180000")
    assert D(summary(admin_client)["month_profit_kzt"]) == D("70000.00")


def test_database_constraint_rejects_second_line_for_order_and_trip(company, scenario):
    from django.db import IntegrityError, transaction

    order, trip = scenario
    with tenant_context(company.id):
        OrderService.objects.create(order=order, trip=trip, title="a", expense=D("1"))
        with pytest.raises(IntegrityError), transaction.atomic():
            OrderService.objects.create(order=order, trip=trip, title="b", expense=D("1"))


def test_migration_links_existing_trip_expense_lines_and_keeps_duplicates_visible(
    company, scenario
):
    """Прежние строки «Перевозка <рейс>» получают ссылку на рейс; дубль остаётся без ссылки."""
    import importlib

    from django.db import connection
    from django.db.migrations.loader import MigrationLoader

    order, trip = scenario
    with tenant_context(company.id):
        first = OrderService.objects.create(
            order=order, title=f"Перевозка {trip.number}", category="Перевозка", expense=D("180000")
        )
        dup = OrderService.objects.create(
            order=order, title=f"Перевозка {trip.number}", category="Перевозка", expense=D("180000")
        )
    mod = importlib.import_module("apps.forwarding.migrations.0016_orderservice_trip_link")
    state = MigrationLoader(connection).project_state(("forwarding", "0016_orderservice_trip_link"))
    mod.link_existing(state.apps, None)  # исторические модели, как при migrate
    with tenant_context(company.id):
        first.refresh_from_db()
        dup.refresh_from_db()
    assert first.trip_id == trip.pk and dup.trip_id is None
