# ruff: noqa: E501
"""API новой финансовой модели (1.4.12): доходы, расходы, настройки, периоды, миграция, карточки."""

from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal as D

import pytest
import time_machine
from rest_framework.test import APIClient

from apps.core.api.auth import issue_tokens
from apps.core.models import Membership, Role, User
from apps.core.tenancy import tenant_context
from apps.finance import income as inc_svc
from apps.finance import periods
from apps.finance.models import (
    CompanyFinancialSettings,
    Expense,
    FinanceMigrationIssue,
    FinancialPeriod,
    Income,
)
from apps.finance.tests.helpers import cur, first_user, make_order
from apps.finance.tests.p2_helpers import (
    enable_new,
    move,
    new_trip,
    order_with_cargos,
    rate,
    set_engine,
)
from apps.forwarding.tests.test_parties import client_with_role

pytestmark = pytest.mark.django_db
NOW = datetime(2026, 7, 15, 12, 0, tzinfo=dt_tz.utc)
F = "/api/finance"
BASE_FINANCE = ["finance.view", "finance.create", "finance.update", "finance.delete"]


@pytest.fixture(autouse=True)
def frozen():
    with time_machine.travel(NOW, tick=False):
        yield


def custom_client(company, perms, name="Роль"):
    n = User.objects.count()
    user = User.objects.create_user(email=f"c{n}@api1412.kz", password="s3cret-pass-1")
    with tenant_context(company.id):
        role = Role.objects.create(name=f"{name} {n}", permissions=list(perms))
    Membership.objects.create(user=user, company=company, role=role)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    return api


@pytest.fixture
def new_company(company, admin_client, admin_user):
    enable_new(company)
    admin_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {issue_tokens(admin_user, company.id)['access']}"
    )
    return company


def code(r):
    return r.json().get("code")


def service(company, order=None, amount="100"):
    order = order or make_order(company)
    with tenant_context(company.id):
        return inc_svc.plan_service(
            order, "Экспедирование", "Услуги", D(amount), first_user(company)
        )


def category(company, c="OTHER"):
    from apps.core.handbooks.models import HandbookValue

    with tenant_context(company.id):
        return HandbookValue.objects.get(handbook__code="expense_category", code=c)


# --- engine / права -----------------------------------------------------------------------


def test_engine_endpoint_and_permissions(new_company, admin_client):
    r = admin_client.get(f"{F}/engine/")
    assert (
        r.status_code == 200
        and r.json()["engine"] == "new"
        and r.json()["base_currency"]["code"] == "KZT"
    )
    nobody = custom_client(new_company, [])
    assert nobody.get(f"{F}/engine/").status_code == 403
    for url in (
        "incomes/",
        "expenses/",
        "periods/",
        "settings/",
        "migration/",
        "settings/status-mapping/",
    ):
        assert nobody.get(f"{F}/{url}").status_code == 403


def test_view_only_role_cannot_write(new_company):
    _, observer = client_with_role(new_company, "Наблюдатель")
    o = make_order(new_company)
    assert observer.get(f"{F}/incomes/").status_code == 200
    assert (
        observer.post(
            f"{F}/incomes/", {"order": o.pk, "title": "x", "amount": "1"}, format="json"
        ).status_code
        == 403
    )
    assert observer.post(f"{F}/expenses/", {}, format="json").status_code == 403
    assert observer.get(f"{F}/settings/").status_code == 403  # manage_settings


# --- доходы -------------------------------------------------------------------------------


def test_income_service_flow_and_filters(new_company, admin_client):
    o = make_order(new_company)
    r = admin_client.post(
        f"{F}/incomes/",
        {"order": o.pk, "title": "Услуга", "category": "Доп", "amount": "250.50"},
        format="json",
    )
    assert (
        r.status_code == 201 and r.json()["status"] == "planned" and r.json()["kind"] == "service"
    )
    pk = r.json()["id"]
    r = admin_client.post(f"{F}/incomes/{pk}/confirm/", {}, format="json")
    assert r.status_code == 409 and code(r) == "service_not_delivered"
    r = admin_client.post(
        f"{F}/incomes/{pk}/deliver/", {"delivered_on": "2026-07-15"}, format="json"
    )
    assert r.status_code == 200 and r.json()["delivered_on"] == "2026-07-15"
    r = admin_client.post(f"{F}/incomes/{pk}/confirm/", {}, format="json")
    assert (
        r.status_code == 200
        and r.json()["status"] == "recognized"
        and r.json()["recognized_on"] == "2026-07-15"
    )
    assert r.json()["base_amount"] == "250.50"
    r = admin_client.post(
        f"{F}/incomes/{pk}/adjust/", {"new_amount": "300", "reason": ""}, format="json"
    )
    assert r.status_code == 400 and code(r) == "field_required"
    r = admin_client.post(
        f"{F}/incomes/{pk}/adjust/",
        {"new_amount": "300", "reason": "Уточнили тариф"},
        format="json",
    )
    assert r.status_code == 200 and r.json()["amount"] == "300.00"
    # фильтры
    lst = admin_client.get(
        f"{F}/incomes/?status=recognized&kind=service&order={o.pk}&currency=KZT&date_from=2026-07-01&date_to=2026-07-31"
    ).json()
    assert lst["count"] == 1
    assert admin_client.get(f"{F}/incomes/?status=planned&kind=service&order={o.pk}").json()["count"] == 0
    # аннулировать можно только плановый
    r = admin_client.post(f"{F}/incomes/{pk}/void/", {"reason": "ошибка"}, format="json")
    assert r.status_code == 409 and code(r) == "income_not_planned"
    pk2 = admin_client.post(
        f"{F}/incomes/", {"order": o.pk, "title": "Вторая", "amount": "5"}, format="json"
    ).json()["id"]
    r = admin_client.post(f"{F}/incomes/{pk2}/void/", {"reason": "Дубль"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "void"


def test_income_errors_period_backdating_frozen_rate(new_company, admin_client):
    o = make_order(new_company)
    pk = admin_client.post(
        f"{F}/incomes/", {"order": o.pk, "title": "Услуга", "amount": "10"}, format="json"
    ).json()["id"]
    # запрет обратного датирования: роль без finance.backdate
    CompanyFinancialSettings.all_objects.filter(company=new_company).update(allow_backdating=False)
    plain = custom_client(new_company, BASE_FINANCE)
    r = plain.post(f"{F}/incomes/{pk}/deliver/", {"delivered_on": "2026-07-10"}, format="json")
    assert r.status_code == 409 and code(r) == "backdating_forbidden"
    # закрытый период
    CompanyFinancialSettings.all_objects.filter(company=new_company).update(allow_backdating=True)
    periods.close_period(new_company, 2026, 6, first_user(new_company))
    r = plain.post(f"{F}/incomes/{pk}/deliver/", {"delivered_on": "2026-06-10"}, format="json")
    assert r.status_code == 409 and code(r) == "period_closed"
    r = admin_client.post(
        f"{F}/incomes/{pk}/deliver/", {"delivered_on": "2026-06-10"}, format="json"
    )
    assert r.status_code == 400 and code(r) == "period_reason_required"
    r = admin_client.post(
        f"{F}/incomes/{pk}/deliver/",
        {"delivered_on": "2026-06-10", "adjust_reason": "Поздний акт"},
        format="json",
    )
    assert r.status_code == 200
    # нет курса (заказ в USD)
    usd = make_order(new_company, currency="USD")
    pk2 = admin_client.post(
        f"{F}/incomes/", {"order": usd.pk, "title": "USD", "amount": "10"}, format="json"
    ).json()["id"]
    admin_client.post(f"{F}/incomes/{pk2}/deliver/", {"delivered_on": "2026-07-15"}, format="json")
    r = admin_client.post(f"{F}/incomes/{pk2}/confirm/", {}, format="json")
    assert r.status_code == 409 and code(r) == "rate_missing"
    # заморозка
    CompanyFinancialSettings.all_objects.filter(company=new_company).update(
        financial_writes_frozen=True
    )
    r = admin_client.post(
        f"{F}/incomes/", {"order": o.pk, "title": "x", "amount": "1"}, format="json"
    )
    assert r.status_code == 423 and code(r) == "finance_frozen"
    assert admin_client.get(f"{F}/incomes/").status_code == 200  # чтение работает


def test_income_isolation_between_companies(new_company, admin_client, make_company):
    other, _, other_client = make_company("Other")
    enable_new(other)
    inc = service(other)
    assert admin_client.get(f"{F}/incomes/{inc.pk}/").status_code == 404
    assert (
        admin_client.post(f"{F}/incomes/{inc.pk}/void/", {"reason": "x"}, format="json").status_code
        == 404
    )
    assert admin_client.get(f"{F}/incomes/?kind=service").json()["count"] == 0
    # чужой заказ при создании
    foreign = make_order(other)
    r = admin_client.post(
        f"{F}/incomes/", {"order": foreign.pk, "title": "x", "amount": "1"}, format="json"
    )
    assert r.status_code == 404
    with tenant_context(other.id):
        assert Income.objects.filter(kind="service").count() == 1
    assert other_client.get(f"{F}/incomes/?kind=service").json()["count"] == 1


# --- расходы ------------------------------------------------------------------------------


def make_expense_via_api(client, company, **extra):
    body = {
        "title": "Аренда", "category": category(company).pk, "amount": "100.00",
        "currency": cur(company).pk, "expense_date": "2026-07-15", **extra,
    }  # fmt: skip
    return client.post(f"{F}/expenses/", body, format="json")


def test_expense_crud_filters_allocations_void(new_company, admin_client):
    r = make_expense_via_api(admin_client, new_company)
    assert r.status_code == 201, r.content
    e = r.json()
    assert (
        e["source"] == "manual"
        and e["kind"] == "other"
        and e["unallocated"] == "100.00"
        and e["allocations"] == []
    )
    pk = e["id"]
    o = make_order(new_company)
    r = admin_client.put(
        f"{F}/expenses/{pk}/allocations/",
        {"allocations": [{"order": o.pk, "amount": "60"}]},
        format="json",
    )
    assert (
        r.status_code == 200
        and r.json()["allocated"] == "60.00"
        and r.json()["unallocated"] == "40.00"
    )
    r = admin_client.put(
        f"{F}/expenses/{pk}/allocations/",
        {"allocations": [{"order": o.pk, "amount": "160"}]},
        format="json",
    )
    assert r.status_code == 400 and code(r) == "allocation_exceeds"
    # PATCH ограничен: только название и категория
    r = admin_client.patch(f"{F}/expenses/{pk}/", {"amount": "5"}, format="json")
    assert r.status_code == 400 and code(r) == "field_not_editable"
    r = admin_client.patch(f"{F}/expenses/{pk}/", {"title": "Аренда склада"}, format="json")
    assert r.status_code == 200 and r.json()["title"] == "Аренда склада"
    # фильтры
    assert admin_client.get(f"{F}/expenses/?order={o.pk}").json()["count"] == 1
    assert (
        admin_client.get(f"{F}/expenses/?category=OTHER&status=active&date_from=2026-07-01").json()[
            "count"
        ]
        == 1
    )
    assert admin_client.get(f"{F}/expenses/?needs_review=true").json()["count"] == 0
    assert admin_client.get(f"{F}/expenses/?date_to=2026-07-01").json()["count"] == 0
    r = admin_client.post(f"{F}/expenses/{pk}/void/", {"reason": ""}, format="json")
    assert r.status_code == 400
    r = admin_client.post(f"{F}/expenses/{pk}/void/", {"reason": "Ошибочный ввод"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "void"
    r = admin_client.patch(f"{F}/expenses/{pk}/", {"title": "x"}, format="json")
    assert r.status_code == 409 and code(r) == "expense_void"


def test_expense_errors_period_backdating_frozen_rate(new_company, admin_client):
    plain = custom_client(new_company, BASE_FINANCE)
    CompanyFinancialSettings.all_objects.filter(company=new_company).update(allow_backdating=False)
    r = make_expense_via_api(plain, new_company, expense_date="2026-07-10")
    assert r.status_code == 409 and code(r) == "backdating_forbidden"
    CompanyFinancialSettings.all_objects.filter(company=new_company).update(allow_backdating=True)
    periods.close_period(new_company, 2026, 6, first_user(new_company))
    r = make_expense_via_api(plain, new_company, expense_date="2026-06-10")
    assert r.status_code == 409 and code(r) == "period_closed"
    usd = cur(new_company, "USD").pk
    r = admin_client.post(
        f"{F}/expenses/",
        {
            "title": "USD",
            "category": category(new_company).pk,
            "amount": "5",
            "currency": usd,
            "expense_date": "2026-07-15",
        },
        format="json",
    )
    assert r.status_code == 409 and code(r) == "rate_missing"
    CompanyFinancialSettings.all_objects.filter(company=new_company).update(
        financial_writes_frozen=True
    )
    r = make_expense_via_api(admin_client, new_company)
    assert r.status_code == 423 and code(r) == "finance_frozen"
    assert admin_client.get(f"{F}/expenses/").status_code == 200


def test_expense_isolation_and_no_n_plus_one(
    new_company, admin_client, make_company, django_assert_max_num_queries
):
    other, _, other_client = make_company("Other")
    enable_new(other)
    foreign = make_expense_via_api(other_client, other).json()["id"]
    assert admin_client.get(f"{F}/expenses/{foreign}/").status_code == 404
    assert (
        admin_client.post(
            f"{F}/expenses/{foreign}/void/", {"reason": "x"}, format="json"
        ).status_code
        == 404
    )
    o = make_order(new_company)
    for i in range(3):
        pk = make_expense_via_api(admin_client, new_company, title=f"Р{i}").json()["id"]
        admin_client.put(
            f"{F}/expenses/{pk}/allocations/",
            {"allocations": [{"order": o.pk, "amount": "10"}]},
            format="json",
        )
    with django_assert_max_num_queries(12):
        r = admin_client.get(f"{F}/expenses/")
    for i in range(6):
        make_expense_via_api(admin_client, new_company, title=f"Д{i}")
    with django_assert_max_num_queries(12):  # число запросов не растёт с числом строк
        admin_client.get(f"{F}/expenses/")
    assert r.json()["count"] == 3


# --- расход перевозчика ----------------------------------------------------------------------


def test_carrier_expense_new_engine(new_company, admin_client):
    o, ids = order_with_cargos(new_company, 1)
    trip = new_trip(new_company, ids, price="150")
    r = admin_client.get(f"/api/trips/{trip.pk}/finance/")
    assert (
        r.status_code == 200
        and r.json()["can_create_expense"] is True
        and r.json()["expense"] is None
    )
    r = admin_client.post(f"{F}/trips/{trip.pk}/carrier-expense/", {}, format="json")
    assert (
        r.status_code == 201
        and r.json()["engine"] == "new"
        and r.json()["expense"]["amount"] == "150.00"
    )
    assert (
        r.json()["expense"]["kind"] == "carrier_transport"
        and r.json()["expense"]["trip"]["id"] == trip.pk
    )
    r = admin_client.post(f"{F}/trips/{trip.pk}/carrier-expense/", {}, format="json")
    assert r.status_code == 409 and code(r) == "expense_exists"
    card = admin_client.get(f"/api/trips/{trip.pk}/finance/").json()
    assert (
        card["can_create_expense"] is False
        and card["expense"]["amount"] == "150.00"
        and card["invoice_variance"] is None
    )
    ocard = admin_client.get(f"/api/orders/{o.pk}/finance/").json()
    assert ocard["engine"] == "new" and ocard["expenses"][0]["order_amount"] == "150.00"
    assert ocard["totals"]["cost"] == "150.00"
    _, observer = client_with_role(new_company, "Наблюдатель")
    assert (
        observer.post(f"{F}/trips/{trip.pk}/carrier-expense/", {}, format="json").status_code == 403
    )
    assert observer.get(f"/api/trips/{trip.pk}/finance/").status_code == 200


def test_carrier_expense_legacy_keeps_old_behaviour(company, admin_client):
    o, ids = order_with_cargos(company, 1)
    trip = new_trip(company, ids, price="80")
    r = admin_client.post(f"{F}/trips/{trip.pk}/carrier-expense/", {}, format="json")
    assert (
        r.status_code == 201
        and r.json()["engine"] == "legacy"
        and r.json()["lines"][0]["expense"] == "80.00"
    )
    with tenant_context(company.id):
        assert Expense.objects.count() == 0  # новая модель не затронута
    # старый эндпоинт строк расхода по-прежнему работает и совместим
    assert admin_client.get(f"{F}/trips/{trip.pk}/expense-lines/").status_code == 200


def test_order_card_incomes_invoices_needs_review(new_company, admin_client):
    o, ids = order_with_cargos(new_company, 1)
    trip = new_trip(new_company, ids, price="100")
    move(new_company, trip, "COMPLETED", when=NOW)
    exp = admin_client.post(f"{F}/trips/{trip.pk}/carrier-expense/", {}, format="json").json()[
        "expense"
    ]
    with tenant_context(new_company.id):
        Expense.objects.filter(pk=exp["id"]).update(
            needs_review=True, review_reason="invoice_variance"
        )
    card = admin_client.get(f"/api/orders/{o.pk}/finance/").json()
    assert card["needs_review"] is True and card["expenses"][0]["needs_review"] is True
    assert card["incomes"][0]["kind"] == "freight"
    assert admin_client.get(f"{F}/expenses/?needs_review=true").json()["count"] == 1


# --- настройки и сопоставление статусов ---------------------------------------------------------


def test_settings_get_patch_and_permissions(new_company, admin_client):
    s = admin_client.get(f"{F}/settings/").json()
    assert (
        s["engine"] == "new"
        and s["base_currency"]["code"] == "KZT"
        and s["unmapped"] == []
        and s["switch_blocked"] is False
    )
    r = admin_client.patch(
        f"{F}/settings/", {"allow_backdating": False, "sync_carrier_price": False}, format="json"
    )
    assert (
        r.status_code == 200
        and r.json()["allow_backdating"] is False
        and r.json()["sync_carrier_price"] is False
    )
    r = admin_client.patch(f"{F}/settings/", {"engine": "legacy"}, format="json")
    assert r.status_code == 400 and code(r) == "setting_forbidden"
    r = admin_client.patch(f"{F}/settings/", {"fiscal_year_start_month": 13}, format="json")
    assert r.status_code == 400 and code(r) == "setting_invalid"
    accountant = client_with_role(new_company, "Бухгалтер")[1]
    assert accountant.get(f"{F}/settings/").status_code == 403
    assert (
        accountant.patch(f"{F}/settings/", {"allow_backdating": True}, format="json").status_code
        == 403
    )


def test_base_currency_change_needs_reason_and_rate(new_company, admin_client):
    usd = cur(new_company, "USD").pk
    r = admin_client.patch(f"{F}/settings/", {"base_currency": usd}, format="json")
    assert r.status_code == 400 and code(r) == "reason_required"
    rate(new_company, "USD", "500", date(2026, 7, 1))
    r = admin_client.patch(
        f"{F}/settings/", {"base_currency": usd, "reason": "Переход на доллар"}, format="json"
    )
    assert r.status_code == 200 and r.json()["base_currency"]["code"] == "USD"
    assert (
        admin_client.patch(
            f"{F}/settings/", {"base_currency": 999999, "reason": "x"}, format="json"
        ).status_code
        == 400
    )


def test_status_mapping_endpoints(company, admin_client):
    from apps.finance.tests.test_status_mapping import unmap

    v = unmap(company)
    rep = admin_client.get(f"{F}/settings/status-mapping/").json()
    assert rep["switch_blocked"] is True and rep["unmapped_system_codes"] == ["COMPLETED"]
    s = admin_client.get(f"{F}/settings/").json()
    assert s["unmapped"] == ["COMPLETED"] and s["switch_blocked"] is True
    r = admin_client.post(
        f"{F}/settings/status-mapping/", {"value": v.pk, "code": "COMPLETED"}, format="json"
    )
    assert r.status_code == 201 and r.json()["switch_blocked"] is False
    assert admin_client.get(f"{F}/settings/").json()["completed_status"]["id"] == v.pk
    r = admin_client.post(
        f"{F}/settings/status-mapping/", {"value": v.pk, "code": "CANCELLED"}, format="json"
    )
    assert r.status_code == 409 and code(r) == "status_already_coded"
    assert (
        admin_client.post(
            f"{F}/settings/status-mapping/", {"value": v.pk, "code": "BAD"}, format="json"
        ).status_code
        == 400
    )
    acc = client_with_role(company, "Бухгалтер")[1]
    assert (
        acc.post(
            f"{F}/settings/status-mapping/", {"value": v.pk, "code": "COMPLETED"}, format="json"
        ).status_code
        == 403
    )


def test_status_mapping_foreign_company_value_404(company, admin_client, make_company):
    from apps.finance.tests.test_status_mapping import unmap

    other, _, _ = make_company("Other")
    foreign = unmap(other)
    r = admin_client.post(
        f"{F}/settings/status-mapping/", {"value": foreign.pk, "code": "COMPLETED"}, format="json"
    )
    assert r.status_code == 404 and code(r) == "status_not_found"


# --- периоды -------------------------------------------------------------------------------


def test_periods_close_reopen_permissions(new_company, admin_client):
    accountant = client_with_role(new_company, "Бухгалтер")[1]
    r = accountant.post(
        f"{F}/periods/", {"year": 2026, "month": 6, "comment": "Закрытие июня"}, format="json"
    )
    assert (
        r.status_code == 201
        and r.json()["status"] == "closed"
        and r.json()["events"][0]["action"] == "close"
    )
    assert (
        accountant.post(f"{F}/periods/", {"year": 2026, "month": 7}, format="json").status_code
        == 409
    )  # не завершён
    pid = r.json()["id"]
    assert (
        accountant.post(
            f"{F}/periods/{pid}/reopen/", {"reason": "нужно"}, format="json"
        ).status_code
        == 403
    )
    _, manager = client_with_role(new_company, "Менеджер")
    assert (
        manager.post(f"{F}/periods/", {"year": 2026, "month": 5}, format="json").status_code == 403
    )
    assert manager.get(f"{F}/periods/").status_code == 200
    r = admin_client.post(f"{F}/periods/{pid}/reopen/", {"reason": ""}, format="json")
    assert r.status_code == 400 and code(r) == "reason_required"
    r = admin_client.post(
        f"{F}/periods/{pid}/reopen/", {"reason": "Ошибка в закрытии"}, format="json"
    )
    assert (
        r.status_code == 200
        and r.json()["status"] == "open"
        and [e["action"] for e in r.json()["events"]] == ["close", "reopen"]
    )
    assert (
        admin_client.post(
            f"{F}/periods/{pid}/reopen/", {"reason": "ещё раз"}, format="json"
        ).status_code
        == 409
    )
    with tenant_context(new_company.id):
        assert FinancialPeriod.objects.count() == 1


def test_periods_isolation(new_company, admin_client, make_company):
    other, _, other_client = make_company("Other")
    pid = other_client.post(f"{F}/periods/", {"year": 2026, "month": 6}, format="json").json()["id"]
    assert admin_client.get(f"{F}/periods/").json() == []
    assert (
        admin_client.post(
            f"{F}/periods/{pid}/reopen/", {"reason": "чужой"}, format="json"
        ).status_code
        == 404
    )


# --- миграция --------------------------------------------------------------------------------


def test_migration_status_and_resolve_issue(company, admin_client):
    from apps.finance.tests.test_migrate_finance import build, run_cmd

    s = build(company)
    run_cmd(company)
    data = admin_client.get(f"{F}/migration/").json()
    assert data["open_count"] >= 5 and data["runs"][0]["kind"] == "migrate"
    issue = next(i for i in data["open_issues"] if i["source_id"] == s["no_trip"].pk)
    url = f"{F}/migration/issues/{issue['id']}/resolve/"
    r = admin_client.post(url, {"note": "Подтверждено"}, format="json")
    assert r.status_code == 400 and code(r) == "resolution_required"
    r = admin_client.post(
        url, {"note": "Списано по акту №7", "resolution": "manual_expense"}, format="json"
    )
    assert (
        r.status_code == 200
        and r.json()["status"] == "resolved"
        and r.json()["resolution"] == "manual_expense"
    )
    acc = client_with_role(company, "Бухгалтер")[1]
    assert acc.get(f"{F}/migration/").status_code == 403
    assert acc.post(url, {"note": "x"}, format="json").status_code == 403


def test_migration_isolation(company, admin_client, make_company):
    from apps.finance.tests.test_migrate_finance import build, run_cmd

    other, _, other_client = make_company("Other")
    s = build(other)
    run_cmd(other)
    with tenant_context(other.id):
        foreign_issue = FinanceMigrationIssue.objects.filter(source_id=s["no_trip"].pk).get()
    assert admin_client.get(f"{F}/migration/").json()["open_count"] == 0
    r = admin_client.post(
        f"{F}/migration/issues/{foreign_issue.pk}/resolve/",
        {"note": "чужая", "resolution": "manual_expense"},
        format="json",
    )
    assert r.status_code == 404
    assert other_client.get(f"{F}/migration/").json()["open_count"] > 0


# --- старые эндпоинты совместимы ---------------------------------------------------------------


def test_legacy_endpoints_still_work_with_adjust_reason(company, admin_client):
    o = make_order(company)
    r = admin_client.post(
        "/api/order-lines/",
        {"order": o.pk, "title": "Услуга", "income": "10", "adjust_reason": "не нужна"},
        format="json",
    )
    assert r.status_code == 201
    for url in (
        "/finance/summary/",
        "/finance/operations/",
        "/finance/debts/clients/",
        "/finance/invoices/",
        "/finance/payments/",
        "/finance/rates/",
    ):
        assert admin_client.get(f"/api{url}").status_code == 200, url
    set_engine(company, "shadow")
    assert admin_client.get(f"{F}/engine/").json()["engine"] == "shadow"
