"""Эксплуатационный учёт: пробег, ТО и ремонты, заправки, расход, напоминания, связь с G1."""

from datetime import timedelta
from decimal import Decimal

import pytest

from apps.core.module_services import set_company_modules
from apps.core.tenancy import tenant_context
from apps.finance.tests.test_ledger_models import make_expense
from apps.fleet import services
from apps.fleet.models import FuelFill, MileageReading, ServiceRecord, Vehicle

pytestmark = pytest.mark.django_db

MILEAGE, SERVICES, FUEL = "/api/mileage/", "/api/service-records/", "/api/fuel-fills/"
REMINDERS = "/api/fleet/reminders/"


@pytest.fixture
def fco(make_company):
    return make_company("Ops", modules=["logistics", "fleet"])  # finance подключается спутником


def vehicle(company, plate="T1", **extra):
    with tenant_context(company.id):
        return Vehicle.objects.create(plate=plate, **extra)


def reading(api, v, km, at, **extra):
    return api.post(MILEAGE, {"vehicle": v.pk, "odometer_km": km, "recorded_at": at, **extra})


# --- пробег ---


def test_mileage_monotonic_and_independent_per_vehicle(fco):
    company, _, api = fco
    tractor, trailer = vehicle(company, "T1"), vehicle(company, "P1", kind="trailer")
    assert reading(api, tractor, 1000, "2026-06-01T10:00:00Z").status_code == 201
    assert reading(api, tractor, 1500, "2026-06-10T10:00:00Z").status_code == 201
    assert reading(api, tractor, 900, "2026-06-11T10:00:00Z").status_code == 400  # меньше прежнего
    assert (
        reading(api, tractor, 1600, "2026-06-05T10:00:00Z").status_code == 400
    )  # больше следующего
    assert reading(api, tractor, 1200, "2026-06-05T10:00:00Z").status_code == 201  # между
    # у прицепа свой одометр, значения тягача ему не мешают
    assert reading(api, trailer, 50, "2026-06-02T10:00:00Z").status_code == 201
    assert api.get(MILEAGE, {"vehicle": tractor.pk}).json()["count"] == 3
    assert api.get(MILEAGE, {"vehicle": trailer.pk}).json()["count"] == 1


# --- топливо ---


def fill(api, v, at, liters, km=None, **extra):
    data = {"vehicle": v.pk, "filled_at": at, "liters": liters, **extra}
    if km is not None:
        data["odometer_km"] = km
    return api.post(FUEL, data, format="json")


def test_fuel_consumption_between_full_tanks(fco):
    company, _, api = fco
    v = vehicle(company)
    assert fill(api, v, "2026-06-01T08:00:00Z", "300", 10000).status_code == 201  # якорь (полный)
    assert fill(api, v, "2026-06-03T08:00:00Z", "100", 10400, full_tank=False).status_code == 201
    assert fill(api, v, "2026-06-05T08:00:00Z", "130", 10800).status_code == 201  # полный
    stats = api.get(f"/api/vehicles/{v.pk}/fuel-stats/").json()
    # (100 + 130) л на 800 км = 28.75 л/100 км
    assert stats["average_l_per_100km"] == "28.75"
    assert stats["distance_km"] == 800 and len(stats["segments"]) == 1
    listing = api.get(FUEL, {"vehicle": v.pk}).json()["results"]
    by_liters = {Decimal(r["liters"]): r["l_per_100km"] for r in listing}
    assert by_liters[Decimal("130")] == "28.75" and by_liters[Decimal("300")] is None
    # заправка записала показания одометра (источник fuel)
    with tenant_context(company.id):
        assert MileageReading.objects.filter(vehicle=v, source="fuel").count() == 3


def test_fuel_validation_and_skipped_without_odometer(fco):
    company, _, api = fco
    v = vehicle(company)
    assert fill(api, v, "2026-06-01T08:00:00Z", "0").status_code == 400
    assert fill(api, v, "2026-06-01T08:00:00Z", "-5").status_code == 400
    assert fill(api, v, "2026-06-01T08:00:00Z", "50").status_code == 201  # без пробега
    stats = services_stats(company, v)
    assert stats["average_l_per_100km"] is None and len(stats["skipped"]) == 1


def services_stats(company, v):
    with tenant_context(company.id):
        return services.fuel_stats(v)


def test_fuel_with_lower_odometer_rejected(fco):
    company, _, api = fco
    v = vehicle(company)
    assert fill(api, v, "2026-06-01T08:00:00Z", "100", 5000).status_code == 201
    assert fill(api, v, "2026-06-02T08:00:00Z", "100", 4000).status_code == 400


# --- обслуживание ---


def test_service_flow_and_mileage_sync(fco):
    company, _, api = fco
    v = vehicle(company)
    r = api.post(SERVICES, {"vehicle": v.pk, "title": "ТО-1", "planned_date": "2026-07-01"})
    assert r.status_code == 201, r.content
    sid = r.json()["id"]
    done = api.patch(f"{SERVICES}{sid}/", {"status": "done"}, format="json")
    assert done.status_code == 400 and "done_date" in done.json()  # без даты нельзя
    ok = api.patch(
        f"{SERVICES}{sid}/",
        {"status": "done", "done_date": "2026-06-30", "odometer_km": 120000, "next_due_km": 135000},
        format="json",
    )
    assert ok.status_code == 200, ok.content
    with tenant_context(company.id):
        assert MileageReading.objects.filter(
            vehicle=v, source="service", odometer_km=120000
        ).exists()
    assert api.get(SERVICES, {"vehicle": v.pk, "status": "done"}).json()["count"] == 1
    assert api.post(SERVICES, {"vehicle": v.pk, "title": " "}).status_code == 400


def test_service_links_finance_expense_without_duplicating_money(fco):
    company, _, api = fco
    v = vehicle(company)
    expense = make_expense(company)
    r = api.post(
        SERVICES,
        {"vehicle": v.pk, "title": "Ремонт подвески", "kind": "repair", "expense": expense.pk},
        format="json",
    )
    assert r.status_code == 201, r.content
    assert r.json()["expense"] == expense.pk
    assert "amount" not in r.json()  # деньги живут только в Finance
    with tenant_context(company.id):
        from apps.finance.models import Expense

        assert Expense.objects.count() == 1  # новых расходов fleet не создаёт
    # аннулированный расход привязать нельзя
    with tenant_context(company.id):
        void = make_expense(company)
        Expense.objects.filter(pk=void.pk).update(status="void")
    bad = api.post(SERVICES, {"vehicle": v.pk, "title": "x", "expense": void.pk}, format="json")
    assert bad.status_code == 400


def test_expense_link_requires_finance_and_own_company(make_company):
    a, _, api = make_company("A", modules=["logistics", "fleet"])
    b, _, _ = make_company("B", modules=["logistics", "fleet"])
    v = vehicle(a)
    foreign = make_expense(b)
    r = api.post(
        FUEL,
        {
            "vehicle": v.pk,
            "filled_at": "2026-06-01T08:00:00Z",
            "liters": "10",
            "expense": foreign.pk,
        },
        format="json",
    )
    assert r.status_code == 400
    mine = make_expense(a)
    set_company_modules(a, ["logistics", "fleet"])  # finance выключен
    r = api.post(
        FUEL,
        {"vehicle": v.pk, "filled_at": "2026-06-01T08:00:00Z", "liters": "10", "expense": mine.pk},
        format="json",
    )
    assert r.status_code == 400 and "expense" in r.json()


# --- напоминания ---


def test_reminders_by_date_km_documents_and_insurance(fco):
    company, _, api = fco
    v = vehicle(company)
    today = services_today(company)
    reading(api, v, 99_500, "2026-06-01T10:00:00Z")
    api.post(
        SERVICES,
        {
            "vehicle": v.pk,
            "title": "Замена масла",
            "kind": "oil",
            "status": "done",
            "done_date": "2026-05-01",
            "next_due_km": 100_000,
        },
        format="json",
    )
    api.post(
        SERVICES,
        {"vehicle": v.pk, "title": "Осмотр", "planned_date": str(today - timedelta(days=2))},
        format="json",
    )
    api.post(
        "/api/vehicle-documents/",
        {"vehicle": v.pk, "kind": "inspection", "expires_at": str(today + timedelta(days=10))},
        format="json",
    )
    api.post(
        "/api/insurances/",
        {"vehicle": v.pk, "kind": "osago", "expires_at": str(today + timedelta(days=400))},
        format="json",
    )
    items = api.get(REMINDERS).json()["results"]
    by_title = {i["title"]: i["state"] for i in items}
    assert by_title["Замена масла"] == "due_soon"  # 99 500 из 100 000, запас 1000 км
    assert by_title["Осмотр"] == "overdue"
    assert by_title["Техосмотр"] == "due_soon"
    assert "ОСАГО" not in by_title  # через 400 дней - не напоминаем
    assert items[0]["state"] == "overdue"  # просроченные первыми
    wide = api.get(REMINDERS, {"days": 500}).json()["results"]
    assert any(i["title"] == "ОСАГО" for i in wide)
    assert api.get(REMINDERS, {"days": "x"}).status_code == 400


def test_reminder_uses_latest_done_service_per_kind(fco):
    company, _, api = fco
    v = vehicle(company)
    today = services_today(company)
    for done, due in (
        ("2026-01-01", today - timedelta(days=100)),
        ("2026-06-01", today + timedelta(days=200)),
    ):
        api.post(
            SERVICES,
            {
                "vehicle": v.pk,
                "title": "ТО",
                "kind": "maintenance",
                "status": "done",
                "done_date": done,
                "next_due_date": str(due),
            },
            format="json",
        )
    assert api.get(REMINDERS).json()["count"] == 0  # старое просроченное закрыто новым ТО


def services_today(company):
    with tenant_context(company.id):
        return services.company_today()


# --- права, модуль, изоляция ---


def test_module_and_isolation(make_company):
    a, _, api_a = make_company("A", modules=["logistics", "fleet"])
    _, _, api_b = make_company("B", modules=["logistics", "fleet"])
    v = vehicle(a)
    api_a.post(SERVICES, {"vehicle": v.pk, "title": "ТО"}, format="json")
    assert api_b.get(SERVICES).json()["count"] == 0
    assert api_b.post(SERVICES, {"vehicle": v.pk, "title": "ТО"}, format="json").status_code == 400
    set_company_modules(a, ["logistics"])
    for url in (MILEAGE, SERVICES, FUEL, REMINDERS):
        r = api_a.get(url)
        assert r.status_code == 403 and r.json()["code"] == "module_disabled", url
    set_company_modules(a, ["logistics", "fleet"])
    with tenant_context(a.id):
        assert ServiceRecord.objects.count() == 1 and FuelFill.objects.count() == 0


def test_delete_vehicle_hides_operations(fco):
    company, _, api = fco
    v = vehicle(company)
    api.post(SERVICES, {"vehicle": v.pk, "title": "ТО"}, format="json")
    api.delete(f"/api/vehicles/{v.pk}/")
    assert api.get(SERVICES).json()["count"] == 0
