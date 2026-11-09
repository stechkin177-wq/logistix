"""T3: лимиты как данные тарифа; серверная проверка создания; понижение/повышение тарифа."""

import pytest

from apps.billing import limits, plans
from apps.billing.models import Plan
from apps.billing.plans import PlanError
from apps.core.models import User
from apps.core.tenancy import tenant_context
from apps.drivers.models import Driver
from apps.fleet.models import Vehicle
from apps.forwarding.models import Client

pytestmark = pytest.mark.django_db

ADMIN = "/api/platform/plans/"


def set_limits(company, **values):
    plan = company.subscription.plan
    plans.update_plan(plan, limits={**plan.limits, **values})


@pytest.fixture
def co(make_company):
    company, _, api = make_company("Lim", modules=["logistics", "fleet", "drivers"])
    plan = company.subscription.plan
    plans.update_plan(plan, modules=list({*plan.modules, "fleet", "drivers"}))
    return company, api


# --- значения лимитов — данные тарифа ---


def test_limits_are_validated_data_with_unlimited_option():
    plan = plans.create_plan(code="l1", name="L1")
    ok = plans.update_plan(plan, limits={"max_vehicles": 3, "max_drivers": None, "max_users": 0})
    assert ok.limits == {"max_vehicles": 3, "max_drivers": None, "max_users": 0}
    for bad in (
        {"max_dragons": 1},
        {"max_vehicles": -1},
        {"max_vehicles": "5"},
        {"max_vehicles": 2.5},
        {"max_vehicles": True},
        {"max_vehicles": 10**10},
        [1],
    ):
        with pytest.raises(PlanError) as e:
            plans.update_plan(plan, limits=bad)
        assert e.value.status_code == 400, bad
    assert plans.update_plan(plan, limits={}).limits == {}  # пустой набор - нигде нет лимита


def test_absent_and_null_mean_unlimited(co):
    company, api = co
    set_limits(company, max_vehicles=None)
    for i in range(7):
        assert api.post("/api/vehicles/", {"plate": f"U{i}"}, format="json").status_code == 201
    plan = company.subscription.plan
    plans.update_plan(plan, limits={})  # ключа нет вовсе
    assert api.post("/api/vehicles/", {"plate": "U9"}, format="json").status_code == 201


# --- серверная проверка при создании ---


def test_vehicle_and_driver_limits_enforced_on_server(co):
    company, api = co
    set_limits(company, max_vehicles=2, max_drivers=1)
    for plate in ("V1", "V2"):
        assert api.post("/api/vehicles/", {"plate": plate}, format="json").status_code == 201
    r = api.post("/api/vehicles/", {"plate": "V3"}, format="json")
    assert r.status_code == 402 and r.json()["code"] == "limit_exceeded"
    assert (r.json()["limit_code"], r.json()["limit"], r.json()["usage"]) == ("max_vehicles", 2, 2)
    assert api.post("/api/drivers/", {"full_name": "А"}, format="json").status_code == 201
    assert api.post("/api/drivers/", {"full_name": "Б"}, format="json").status_code == 402


def test_limit_applies_to_any_creation_path_not_only_the_api(co):
    company, _ = co
    set_limits(company, max_clients=1)
    with tenant_context(company.id):
        Client.objects.create(name="Первый")
        with pytest.raises(Exception) as e:  # прямое создание через ORM тоже проверяется
            Client.objects.create(name="Второй")
        assert getattr(e.value, "status_code", None) == 402


def test_deleted_objects_do_not_count_and_zero_blocks_everything(co):
    company, api = co
    set_limits(company, max_vehicles=1)
    created = api.post("/api/vehicles/", {"plate": "D1"}, format="json").json()
    assert api.post("/api/vehicles/", {"plate": "D2"}, format="json").status_code == 402
    api.delete(f"/api/vehicles/{created['id']}/")  # в корзину - место освободилось
    assert api.post("/api/vehicles/", {"plate": "D2"}, format="json").status_code == 201
    set_limits(company, max_vehicles=0)
    assert api.post("/api/vehicles/", {"plate": "D3"}, format="json").status_code == 402


def test_users_limit_enforced_through_same_mechanism(co):
    company, api = co
    from apps.core.models import Role

    set_limits(company, max_users=1)  # уже есть владелец
    with tenant_context(company.id):
        role = Role.objects.get(name="Менеджер")
    r = api.post(
        "/api/users/",
        {"login": "n@lim.kz", "full_name": "Н", "password": "Str0ng-pass-91", "role": role.id},
        format="json",
    )
    assert r.status_code == 402 and r.json()["code"] == "limit_exceeded"


def test_monthly_limit_counts_only_current_month(co):
    from datetime import timedelta

    from django.utils import timezone

    company, _ = co
    set_limits(company, max_documents_per_month=None)
    with tenant_context(company.id):
        assert limits.usage(company.id, "max_orders_per_month") == 0
        from apps.forwarding.models import Order

        Order.objects.count()  # модель доступна
    assert limits.BY_CODE["max_orders_per_month"]["scope"] == limits.MONTH
    start = limits._month_start(company.id)
    assert start.day == 1 and timezone.now() - start < timedelta(days=32)


# --- понижение и повышение тарифа ---


def test_downgrade_keeps_data_and_blocks_only_new_objects(co):
    company, api = co
    set_limits(company, max_vehicles=5)
    for i in range(4):
        assert api.post("/api/vehicles/", {"plate": f"G{i}"}, format="json").status_code == 201
    set_limits(company, max_vehicles=2)  # тариф понижен ниже фактического использования
    with tenant_context(company.id):
        assert Vehicle.objects.count() == 4  # данные не удалены
    assert api.get("/api/vehicles/").json()["count"] == 4
    first = api.get("/api/vehicles/").json()["results"][0]["id"]
    assert api.patch(f"/api/vehicles/{first}/", {"notes": "ok"}, format="json").status_code == 200
    assert api.post("/api/vehicles/", {"plate": "NEW"}, format="json").status_code == 402
    usage = {r["code"]: r for r in api.get("/api/billing/usage/").json()["results"]}
    assert usage["max_vehicles"]["exceeded"] is True and usage["max_vehicles"]["usage"] == 4


def test_upgrade_lifts_restriction_automatically(co):
    company, api = co
    set_limits(company, max_drivers=1)
    api.post("/api/drivers/", {"full_name": "А"}, format="json")
    assert api.post("/api/drivers/", {"full_name": "Б"}, format="json").status_code == 402
    set_limits(company, max_drivers=10)  # повышение — ничего вручную делать не нужно
    assert api.post("/api/drivers/", {"full_name": "Б"}, format="json").status_code == 201
    set_limits(company, max_drivers=None)
    assert api.post("/api/drivers/", {"full_name": "В"}, format="json").status_code == 201
    with tenant_context(company.id):
        assert Driver.objects.count() == 3


def test_switching_company_to_other_plan_applies_its_limits(co):
    company, api = co
    set_limits(company, max_vehicles=1)
    api.post("/api/vehicles/", {"plate": "S1"}, format="json")
    assert api.post("/api/vehicles/", {"plate": "S2"}, format="json").status_code == 402
    roomy = plans.publish(
        plans.create_plan(
            code="roomy", name="Roomy", modules=["logistics", "fleet"], limits={"max_vehicles": 9}
        )
    )
    sub = company.subscription
    sub.plan = roomy
    sub.save()
    assert api.post("/api/vehicles/", {"plate": "S2"}, format="json").status_code == 201


def test_no_subscription_or_unmeasured_limit_does_not_block_creation(co):
    company, _ = co
    set_limits(company, max_ocr_per_month=0)  # объявлен, но пока не измеряется
    limits.check(company.id, "max_ocr_per_month")  # не бросает
    assert limits.usage(company.id, "max_ocr_per_month") is None
    from apps.billing.models import Subscription

    Subscription.objects.filter(company=company).delete()
    limits.check(company.id, "max_vehicles")  # без подписки проверка пропускается (шлюз закроет)
    with pytest.raises(ValueError):
        limits.check(company.id, "ghost")


# --- API ---


@pytest.fixture
def platform_api(admin_client, admin_user):
    User.objects.filter(pk=admin_user.pk).update(is_platform_admin=True)
    return admin_client


def test_admin_api_manages_limits_and_serves_catalog(platform_api):
    api = platform_api
    catalog = api.get("/api/platform/catalog/").json()["limits"]
    codes = {x["code"] for x in catalog}
    assert {"max_users", "max_vehicles", "max_drivers", "max_orders_per_month"} <= codes
    assert next(x for x in catalog if x["code"] == "max_ocr_per_month")["enforced"] is False
    assert api.post(ADMIN, {"code": "lim", "name": "Lim"}, format="json").status_code == 201
    r = api.patch(
        f"{ADMIN}lim/", {"limits": {"max_vehicles": 3, "max_drivers": None}}, format="json"
    )
    assert r.status_code == 200 and r.json()["limits"] == {"max_vehicles": 3, "max_drivers": None}
    bad = api.patch(f"{ADMIN}lim/", {"limits": {"max_vehicles": -5}}, format="json")
    assert bad.status_code == 400
    assert api.patch(f"{ADMIN}lim/", {"limits": {"zzz": 1}}, format="json").status_code == 400


def test_usage_endpoint_for_company(co):
    company, api = co
    set_limits(company, max_vehicles=2)
    api.post("/api/vehicles/", {"plate": "Q1"}, format="json")
    rows = {r["code"]: r for r in api.get("/api/billing/usage/").json()["results"]}
    assert rows["max_vehicles"] == {
        "code": "max_vehicles", "name": "Техника", "unit": "ед.", "scope": "total",
        "limit": 2, "usage": 1, "enforced": True, "exceeded": False,
    }  # fmt: skip
    assert rows["max_ocr_per_month"]["usage"] is None


# --- совместимость публичного API: options -> features ---


def test_public_plan_keeps_legacy_options_derived_from_features(admin_client):
    plans.update_plan(
        Plan.objects.get(code="business"), features={"white_label": True, "custom_domain": False}
    )
    data = {p["code"]: p for p in admin_client.get("/api/billing/plans/").json()}
    assert data["business"]["features"] == {"white_label": True}
    assert data["business"]["options"] == {"white_label": True, "custom_domain": False}
    assert data["start"]["options"] == {"white_label": False, "custom_domain": False}
    sub = admin_client.get("/api/billing/subscription/").json()["plan"]
    assert "options" in sub and "features" in sub  # и в подписке компании
