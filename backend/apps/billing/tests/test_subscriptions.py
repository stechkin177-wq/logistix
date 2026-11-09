"""T4: смена тарифа, продление, цена периода, предупреждения о лимитах, бесплатный период."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.billing import limits, plans, subscriptions
from apps.billing.models import Plan, Subscription, SubscriptionPeriod
from apps.billing.plans import PlanError
from apps.core.models import User
from apps.core.module_services import disable_module, enable_module, enabled_module_codes
from apps.core.services import create_company_with_defaults
from apps.core.tenancy import tenant_context
from apps.fleet.models import Vehicle

pytestmark = pytest.mark.django_db

PLATFORM = "/api/platform/subscriptions/"


def new_plan(code, **extra):
    content = {k: extra.pop(k) for k in ("modules", "features", "limits") if k in extra}
    plan = plans.create_plan(code=code, name=code.upper(), **extra)
    if content:
        plan = plans.update_plan(plan, **content)
    return plans.publish(plan)


@pytest.fixture
def co(make_company):
    company, admin, api = make_company("T4", modules=["logistics", "fleet", "drivers"])
    plan = company.subscription.plan
    plans.update_plan(plan, modules=list({*plan.modules, "fleet", "drivers", "analytics"}))
    return company, admin, api


# --- бесплатный период и цена настраиваются данными ---


def test_free_period_length_and_price_are_plan_data(admin_user):
    free = new_plan("free7", free_period_days=7)
    plans.set_default(free)
    owner = User.objects.create_user(email="o@t4.kz", password="x")
    company = create_company_with_defaults("A", owner, ["logistics"])
    sub = company.subscription
    assert sub.is_free_period and sub.plan.code == "free7"
    assert abs((sub.ends_at - sub.starts_at) - timedelta(days=7)) < timedelta(seconds=5)
    period = subscriptions.current_period(sub)
    assert (period.price, period.is_free, period.reason) == (0, True, "start")
    # нулевой бесплатный период и ненулевая цена: сразу первый оплачиваемый период
    paid = plans.update_plan(new_plan("paid1", price="2500"), billing_type="yearly")
    plans.set_default(plans.publish(paid))
    owner2 = User.objects.create_user(email="o2@t4.kz", password="x")
    company2 = create_company_with_defaults("B", owner2, ["logistics"])
    sub2 = company2.subscription
    assert not sub2.is_free_period and sub2.plan.code == "paid1"
    assert subscriptions.current_period(sub2).price == Decimal("2500")
    assert sub2.ends_at > timezone.now() + timedelta(days=360)


def test_free_period_and_warn_percent_validation_and_admin_edit():
    plan = plans.create_plan(code="v1", name="V1")
    ok = plans.update_plan(plan, free_period_days=30, limit_warn_percent=70)
    assert (ok.free_period_days, ok.limit_warn_percent) == (30, 70)
    for bad in ({"free_period_days": -1}, {"free_period_days": "5"}, {"limit_warn_percent": 101}):
        with pytest.raises(PlanError):
            plans.update_plan(plan, **bad)


def test_no_logic_depends_on_plan_names_prices_or_count(co):
    """Бесплатные тарифы можно архивировать: компании остаются, линейка меняется целиком."""
    company, _, _ = co
    old = company.subscription.plan
    replacement = plans.set_default(new_plan("brand-new", price="100"))
    plans.archive(old)  # бесплатный стартовый тариф в архиве
    assert replacement.is_default and Plan.objects.get(pk=old.pk).status == "archived"
    company.subscription.refresh_from_db()
    assert company.subscription.plan_id == old.pk  # подписка работает на архивном тарифе
    owner = User.objects.create_user(email="n@t4.kz", password="x")
    created = create_company_with_defaults("N", owner, ["logistics"])
    assert created.subscription.plan.code == "brand-new"


# --- смена тарифа ---


def test_change_plan_never_touches_company_modules_or_reenables_manual_off(co):
    company, admin, api = co
    disable_module(company, "documents", admin, "не нужны")
    before = set(enabled_module_codes(company.id))
    roomy = new_plan(
        "roomy", modules=["logistics", "finance", "documents", "fleet", "drivers", "gps"]
    )
    subscriptions.change_plan(company, roomy, user=admin)
    assert set(enabled_module_codes(company.id)) == before  # ничего не включилось и не выключилось
    assert "documents" not in enabled_module_codes(company.id)
    # новые возможности доступны сразу: модуль можно включить, функция проверяется по тарифу
    enable_module(company, "gps", admin)
    assert "gps" in enabled_module_codes(company.id)


def test_upgrade_makes_features_and_limits_available_immediately(co):
    company, admin, api = co
    plans.update_plan(company.subscription.plan, limits={"max_vehicles": 1})
    api.post("/api/vehicles/", {"plate": "A1"}, format="json")
    assert api.post("/api/vehicles/", {"plate": "A2"}, format="json").status_code == 402
    big = new_plan(
        "big", modules=["logistics", "finance", "documents", "fleet", "drivers"],
        features={"multi_branch": True}, limits={"max_vehicles": 50},
    )  # fmt: skip
    subscriptions.change_plan(company, big, user=admin)
    assert api.post("/api/vehicles/", {"plate": "A2"}, format="json").status_code == 201
    assert api.get("/api/session/").json()["features"] == {"multi_branch": True}


def test_downgrade_over_limits_keeps_data_access_edit_and_blocks_only_new(co):
    company, admin, api = co
    for i in range(4):
        assert api.post("/api/vehicles/", {"plate": f"D{i}"}, format="json").status_code == 201
    tiny = new_plan(
        "tiny", modules=["logistics", "finance", "documents", "fleet", "drivers"],
        limits={"max_vehicles": 2},
    )  # fmt: skip
    preview = subscriptions.preview_change(company, tiny)
    assert [r["code"] for r in preview["limits_exceeded"]] == ["max_vehicles"]
    assert (
        preview["limits_exceeded"][0]["usage"] == 4
        and preview["limits_exceeded"][0]["new_limit"] == 2
    )
    subscriptions.change_plan(company, tiny, user=admin)
    with tenant_context(company.id):
        assert Vehicle.objects.count() == 4  # данные на месте
    listing = api.get("/api/vehicles/").json()
    assert listing["count"] == 4  # просмотр сохранён
    first = listing["results"][0]["id"]
    assert (
        api.patch(f"/api/vehicles/{first}/", {"notes": "правка"}, format="json").status_code == 200
    )
    assert api.get(f"/api/vehicles/{first}/fuel-stats/").status_code == 200  # и расчёты/выгрузки
    assert api.post("/api/vehicles/", {"plate": "NEW"}, format="json").status_code == 402
    assert api.delete(f"/api/vehicles/{first}/").status_code == 204  # можно сокращать самому
    usage = api.get("/api/billing/usage/").json()
    row = next(r for r in usage["results"] if r["code"] == "max_vehicles")
    assert (row["usage"], row["limit"], row["state"]) == (3, 2, "exceeded")
    assert any(w["code"] == "max_vehicles" for w in usage["warnings"])


def test_downgrade_removing_module_closes_access_keeps_data(co):
    company, admin, api = co
    api.post("/api/vehicles/", {"plate": "M1"}, format="json")
    no_fleet = new_plan("nofleet", modules=["logistics", "finance", "documents"])
    preview = subscriptions.preview_change(company, no_fleet)
    assert "fleet" in preview["lost_modules"] and "drivers" in preview["lost_modules"]
    subscriptions.change_plan(company, no_fleet, user=admin)
    assert api.get("/api/vehicles/").status_code == 403
    with tenant_context(company.id):
        assert Vehicle.objects.count() == 1
    assert "fleet" in enabled_module_codes(company.id)  # CompanyModule не менялся
    subscriptions.change_plan(company, Plan.objects.get(code="start"), user=admin)


def test_change_plan_rules_and_validation(co):
    company, _, _ = co
    archived = plans.archive(new_plan("old-one"))
    with pytest.raises(PlanError) as e:
        subscriptions.change_plan(company, archived)
    assert e.value.detail["code"] == "plan_archived"
    with pytest.raises(PlanError):
        subscriptions.change_plan(company, company.subscription.plan, period="later")
    same = subscriptions.change_plan(company, company.subscription.plan)  # без изменений
    assert same.plan_id == company.subscription.plan_id


# --- цена периода ---


def test_price_change_does_not_touch_paid_period_applies_on_renewal(co):
    company, admin, _ = co
    plan = plans.update_plan(company.subscription.plan, price="1000", billing_type="monthly")
    sub = company.subscription
    sub.is_free_period = False
    sub.ends_at = timezone.now() + timedelta(days=10)
    sub.save()
    SubscriptionPeriod.objects.filter(subscription=sub).update(price=Decimal("1000"), is_free=False)
    plans.update_plan(plan, price="5000")  # администратор поднял цену
    periods = list(sub.periods.all())
    assert [p.price for p in periods] == [Decimal("1000")]  # оплаченный период не изменился
    old_end = sub.ends_at
    renewed = subscriptions.renew(company, user=admin)
    prices = [p.price for p in renewed.periods.all()]
    assert prices == [Decimal("1000"), Decimal("5000")]  # новая цена — только у продления
    last = renewed.periods.last()
    assert last.reason == "renewal" and last.starts_at == old_end  # продолжение с конца периода
    assert renewed.ends_at > old_end


def test_renew_continues_from_end_or_now_and_validates(co):
    company, admin, _ = co
    plans.update_plan(company.subscription.plan, billing_type="monthly", price="10")
    sub = company.subscription
    end = datetime(2030, 1, 31, 12, 0, tzinfo=UTC)
    Subscription.objects.filter(pk=sub.pk).update(ends_at=end, is_free_period=False)
    renewed = subscriptions.renew(company, user=admin)
    assert renewed.ends_at == datetime(2030, 2, 28, 12, 0, tzinfo=UTC)  # конец февраля, без сбоя
    twice = subscriptions.renew(company, periods=2, user=admin)
    assert twice.ends_at == datetime(2030, 4, 28, 12, 0, tzinfo=UTC)
    assert twice.periods.last().price == Decimal("20")
    Subscription.objects.filter(pk=sub.pk).update(ends_at=timezone.now() - timedelta(days=40))
    expired = subscriptions.renew(company, user=admin)
    assert expired.ends_at > timezone.now()  # просроченная подписка продлевается с этого момента
    for bad in (0, 25, "1", True):
        with pytest.raises(PlanError):
            subscriptions.renew(company, periods=bad)


def test_lifetime_not_renewable_and_restart_applies_new_price(co):
    company, admin, _ = co
    life = new_plan("life", billing_type="lifetime", price="9")
    subscriptions.change_plan(company, life, period="restart", user=admin)
    company.subscription.refresh_from_db()
    assert company.subscription.ends_at is None and not company.subscription.is_free_period
    last = company.subscription.periods.last()
    assert (last.reason, last.price, last.plan_code) == ("plan_change", Decimal("9"), "life")
    with pytest.raises(PlanError) as e:
        subscriptions.renew(company)
    assert e.value.detail["code"] == "lifetime_not_renewable"


def test_keep_period_leaves_end_and_price_until_renewal(co):
    company, admin, _ = co
    sub = company.subscription
    ends = sub.ends_at
    other = new_plan("other", price="777")
    subscriptions.change_plan(company, other, user=admin)  # period=keep по умолчанию
    sub.refresh_from_db()
    assert sub.plan.code == "other" and sub.ends_at == ends and sub.is_free_period is True
    assert [p.price for p in sub.periods.all()] == [Decimal("0")]


def test_change_plan_is_audited(co):
    from apps.core.audit.models import AuditLog

    company, admin, _ = co
    subscriptions.change_plan(company, new_plan("audited"), user=admin)
    with tenant_context(company.id):
        log = AuditLog.objects.filter(object_type="billing.subscription").latest("id")
    assert log.changes["plan"][1] == "audited" and log.changes["period"] == "keep"


# --- предупреждения владельцу ---


def test_limit_states_near_reached_exceeded(co):
    company, _, api = co
    plans.update_plan(company.subscription.plan, limits={"max_vehicles": 10}, limit_warn_percent=80)
    for i in range(7):
        api.post("/api/vehicles/", {"plate": f"W{i}"}, format="json")
    row = lambda: next(  # noqa: E731
        r for r in api.get("/api/billing/usage/").json()["results"] if r["code"] == "max_vehicles"
    )
    assert row()["state"] == "ok"  # 7 из 10 — ниже порога 80%
    api.post("/api/vehicles/", {"plate": "W7"}, format="json")
    assert row()["state"] == "near" and row()["usage"] == 8
    for i in (8, 9):
        api.post("/api/vehicles/", {"plate": f"W{i}"}, format="json")
    assert row()["state"] == "reached"
    plans.update_plan(company.subscription.plan, limits={"max_vehicles": 5})
    assert row()["state"] == "exceeded" and row()["exceeded"] is True
    warnings = api.get("/api/billing/usage/").json()["warnings"]
    assert [w["code"] for w in warnings] == ["max_vehicles"]
    plans.update_plan(company.subscription.plan, limits={}, limit_warn_percent=0)
    assert row()["state"] == "ok"


def test_state_function_edges():
    assert limits.state_of(None, 99, 80) == "ok"
    assert limits.state_of(0, 0, 80) == "reached"
    assert limits.state_of(10, 8, 0) == "ok"  # предупреждение заранее выключено
    assert limits.state_of(10, 10, 80) == "reached" and limits.state_of(10, 11, 80) == "exceeded"


# --- API администратора ---


@pytest.fixture
def platform_api(admin_client, admin_user):
    User.objects.filter(pk=admin_user.pk).update(is_platform_admin=True)
    return admin_client


def test_platform_api_preview_change_renew(platform_api, company):
    api = platform_api
    target = new_plan("api-target", price="50", free_period_days=3)
    url = f"{PLATFORM}{company.id}/"
    assert api.get(url).json()["current_period"]["is_free"] is True
    preview = api.get(f"{url}change-plan/preview/", {"plan": "api-target"}).json()
    assert preview["to_plan"] == "api-target" and "limits_exceeded" in preview
    assert api.get(f"{url}change-plan/preview/", {"plan": "ghost"}).status_code == 400
    r = api.post(f"{url}change-plan/", {"plan": "api-target", "period": "restart"}, format="json")
    assert r.status_code == 200 and r.json()["plan"] == "api-target"
    assert r.json()["current_period"]["price"] == "50.00" and not r.json()["is_free_period"]
    renewed = api.post(f"{url}renew/", {"periods": 2}, format="json").json()
    assert (
        renewed["periods"][-1]["reason"] == "renewal"
        and renewed["periods"][-1]["price"] == "100.00"
    )
    assert api.post(f"{url}renew/", {"periods": 99}, format="json").status_code == 400
    assert api.post(f"{url}change-plan/", {"plan": "x"}, format="json").status_code == 400
    assert api.get(f"{PLATFORM}999999/").status_code == 404
    assert target.pk


def test_platform_subscription_api_requires_platform_admin(admin_client, company):
    assert admin_client.get(f"{PLATFORM}{company.id}/").status_code == 403
    assert admin_client.post(f"{PLATFORM}{company.id}/renew/").status_code == 403
