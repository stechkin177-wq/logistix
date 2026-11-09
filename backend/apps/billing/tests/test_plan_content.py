"""T2: модули и функции тарифа как данные; разделение профиля и тарифа; сохранность данных."""

import pytest
from django.http import JsonResponse
from rest_framework.test import APIRequestFactory

from apps.billing import features, plans
from apps.billing.models import Plan
from apps.billing.plans import PlanError
from apps.core.models import ActivityProfile
from apps.core.module_services import (
    apply_profile,
    disable_module,
    enable_module,
    enabled_module_codes,
    set_company_modules,
)
from apps.core.tenancy import tenant_context
from apps.fleet.models import Vehicle

pytestmark = pytest.mark.django_db

ADMIN = "/api/platform/plans/"


def make(code="c1", **content):
    plan = plans.create_plan(code=code, name=code.upper())
    return plans.update_plan(plan, **content) if content else plan


# --- состав тарифа: модули ---


def test_modules_are_data_with_real_dependencies_only():
    plan = make("m1", modules=["logistics", "finance", "documents", "fleet"])
    assert plan.modules == ["logistics", "finance", "documents", "fleet"]
    for bad in (["finance"], ["forwarding"], ["driver_app", "drivers"], ["gps"]):
        with pytest.raises(PlanError) as e:  # зависимость не в тарифе
            plans.update_plan(plan, modules=bad)
        assert e.value.detail["code"] == "plan_modules_incomplete", bad
    with pytest.raises(PlanError):
        plans.update_plan(plan, modules=["nope"])
    with pytest.raises(PlanError):
        plans.update_plan(plan, modules=["core"])  # core всегда включён и в тариф не входит
    with pytest.raises(PlanError):
        plans.update_plan(plan, modules="logistics")
    # documents не зависит от finance, fleet не зависит от forwarding: искусственных связей нет
    assert plans.update_plan(plan, modules=["documents"]).modules == ["documents"]
    assert plans.update_plan(plan, modules=["fleet", "gps"]).modules == ["fleet", "gps"]


def test_create_with_content_and_drafts_are_not_offered():
    plan = plans.create_plan(
        code="c2", name="C2", modules=["logistics", "documents"], features={"white_label": True}
    )
    assert plan.modules == ["logistics", "documents"] and plan.features == {"white_label": True}
    assert plan.status == "draft"


# --- состав тарифа: функции ---


def test_features_catalog_validation_and_levels():
    plan = make("f1", modules=["logistics", "analytics"])
    ok = {"analytics_level": "extended", "api_access": "limited", "white_label": True}
    assert plans.update_plan(plan, features=ok).features == ok
    # выключенные функции не хранятся
    cleaned = plans.update_plan(plan, features={"white_label": False, "automation": None})
    assert cleaned.features == {}
    for bad in (
        {"unknown": True},
        {"white_label": "yes"},
        {"analytics_level": "gigantic"},
        {"multi_branch": 1},
        "white_label",
    ):
        with pytest.raises(PlanError) as e:
            plans.update_plan(plan, features=bad)
        assert e.value.status_code == 400, bad


def test_feature_of_module_outside_plan_is_rejected_and_dropped_with_module():
    plan = make("f2", modules=["logistics"])
    with pytest.raises(PlanError):  # аналитика не входит в тариф
        plans.update_plan(plan, features={"analytics_level": "basic"})
    plan = plans.update_plan(
        plan, modules=["logistics", "analytics"], features={"analytics_level": "full"}
    )
    plan = plans.update_plan(plan, modules=["logistics"])  # модуль убран - функция уходит с ним
    assert plan.features == {}


# --- профиль и тариф не связаны жёстко ---


def test_plan_change_never_touches_company_modules_or_reenables_manual_off(make_company):
    company, admin, _ = make_company("Sep", modules=["logistics", "fleet"])
    disable_module(company, "documents", admin, "не нужны")  # решение владельца
    plan = company.subscription.plan
    before = set(enabled_module_codes(company.id))
    # администратор расширяет и сужает тариф
    wide = list({*plan.modules, "drivers", "documents", "analytics"})
    plans.update_plan(plan, modules=wide)
    plans.update_plan(plan, modules=[m for m in wide if m != "fleet"])
    plans.update_plan(plan, modules=wide)
    assert set(enabled_module_codes(company.id)) == before  # CompanyModule — источник истины
    assert "documents" not in enabled_module_codes(company.id)  # вручную отключённый не включился


def test_profile_recommends_but_plan_decides(make_company):
    company, admin, _ = make_company("Prof", modules=["logistics"])
    plan = company.subscription.plan
    plans.update_plan(plan, modules=["logistics", "finance", "documents"])
    profile = ActivityProfile.objects.get(code="carrier")  # рекомендует fleet и drivers
    result = apply_profile(company, profile, admin)
    skipped = {s["code"]: s["error_code"] for s in result["skipped"]}
    assert skipped == {"fleet": "module_not_in_plan", "drivers": "module_not_in_plan"}
    # администратор добавил модуль в тариф: компания включает его сама, профиль не менялся
    plans.update_plan(plan, modules=["logistics", "finance", "documents", "fleet"])
    assert "fleet" not in enabled_module_codes(company.id)
    enable_module(company, "fleet", admin)  # дополнительный модуль в рамках тарифа
    assert "fleet" in enabled_module_codes(company.id)


def test_removing_module_from_plan_closes_access_but_keeps_data(make_company):
    company, admin, api = make_company("Keep", modules=["logistics", "fleet"])
    plan = company.subscription.plan
    plans.update_plan(plan, modules=list({*plan.modules, "fleet"}))
    with tenant_context(company.id):
        Vehicle.objects.create(plate="K1")
    assert api.get("/api/vehicles/").json()["count"] == 1
    plans.update_plan(plan, modules=[m for m in plan.modules if m != "fleet"])
    r = api.get("/api/vehicles/")
    assert r.status_code == 403 and r.json()["code"] == "module_disabled"  # серверная проверка
    assert "fleet" not in api.get("/api/session/").json()["modules"]
    with tenant_context(company.id):
        assert Vehicle.objects.count() == 1  # данные на месте
    plans.update_plan(plan, modules=list({*plan.modules, "fleet"}))
    assert api.get("/api/vehicles/").json()["count"] == 1  # доступ вернулся без дублей
    assert "fleet" in enabled_module_codes(company.id)  # и CompanyModule не терялся


def test_company_can_disable_and_reenable_inside_plan(make_company):
    company, admin, _ = make_company("Own", modules=["logistics", "fleet"])
    plans.update_plan(
        company.subscription.plan, modules=list({*company.subscription.plan.modules, "fleet"})
    )
    disable_module(company, "fleet", admin, "пауза")
    assert "fleet" not in enabled_module_codes(company.id)
    enable_module(company, "fleet", admin, "вернули")
    assert "fleet" in enabled_module_codes(company.id)
    set_company_modules(company, ["logistics"])  # прямое задание набора тоже не трогает тариф
    assert "fleet" in company.subscription.plan.modules


# --- серверная проверка функций ---


def test_has_feature_requires_plan_and_enabled_owner_module(make_company):
    company, admin, _ = make_company("Feat", modules=["logistics"])
    plan = company.subscription.plan
    plans.update_plan(
        plan,
        modules=list({*plan.modules, "analytics"}),
        features={"analytics_level": "extended", "white_label": True, "priority_support": True},
    )
    cid = company.id
    assert features.has_feature(cid, "white_label") and features.has_feature(
        cid, "priority_support"
    )
    assert not features.has_feature(cid, "multi_branch")
    # функция модуля, который компания не включила, недоступна
    assert not features.has_feature(cid, "analytics_level")
    enable_module(company, "analytics", admin)
    assert features.has_feature(cid, "analytics_level", "basic")
    assert features.has_feature(cid, "analytics_level", "extended")
    assert not features.has_feature(cid, "analytics_level", "full")
    assert features.company_features(cid) == {
        "white_label": True, "priority_support": True, "analytics_level": "extended"
    }  # fmt: skip
    with pytest.raises(ValueError):
        features.has_feature(cid, "ghost")
    with pytest.raises(ValueError):
        features.has_feature(cid, "analytics_level", "ultra")


def test_feature_required_permission_blocks_on_server(make_company):
    company, _, api = make_company("Perm", modules=["logistics"])
    request = APIRequestFactory().get("/")
    request.membership = type("M", (), {"company_id": company.id})()
    perm = features.FeatureRequired("priority_support")()
    with pytest.raises(features.FeatureUnavailable):
        perm.has_permission(request, None)
    plans.update_plan(company.subscription.plan, features={"priority_support": True})
    assert perm.has_permission(request, None) is True
    request.membership = None
    assert perm.has_permission(request, None) is False
    with pytest.raises(ValueError):
        features.FeatureRequired("ghost")
    assert JsonResponse and api  # используются фикстуры


def test_session_exposes_company_features(make_company):
    company, _, api = make_company("Sess", modules=["logistics"])
    assert api.get("/api/session/").json()["features"] == {}
    plans.update_plan(company.subscription.plan, features={"white_label": True})
    assert api.get("/api/session/").json()["features"] == {"white_label": True}


# --- API администратора платформы ---


def test_admin_api_sets_modules_and_features_and_serves_catalog(platform_api):
    api = platform_api
    catalog = api.get("/api/platform/catalog/").json()
    codes = {m["code"] for m in catalog["modules"]}
    assert {"logistics", "forwarding", "finance", "fleet", "drivers", "gps"} <= codes
    assert next(m for m in catalog["modules"] if m["code"] == "finance")["requires"] == [
        "logistics"
    ]
    assert {f["code"] for f in catalog["features"]} >= {"white_label", "analytics_level"}
    assert api.post(ADMIN, {"code": "t2", "name": "T2"}, format="json").status_code == 201
    r = api.patch(
        f"{ADMIN}t2/",
        {"modules": ["logistics", "fleet"], "features": {"multi_branch": True}},
        format="json",
    )
    assert r.status_code == 200, r.content
    assert r.json()["modules"] == ["logistics", "fleet"] and r.json()["features"] == {
        "multi_branch": True
    }
    bad = api.patch(f"{ADMIN}t2/", {"modules": ["finance"]}, format="json")
    assert bad.status_code == 400 and bad.json()["code"] == "plan_modules_incomplete"
    assert api.patch(f"{ADMIN}t2/", {"features": {"x": True}}, format="json").status_code == 400


def test_catalog_requires_platform_admin(admin_client):
    assert admin_client.get("/api/platform/catalog/").status_code == 403


def test_seeded_options_moved_to_features():
    business = Plan.objects.get(code="business")
    assert (
        business.features.get("white_label") is True
        and business.features.get("custom_domain") is True
    )
    assert "white_label" not in business.options
    assert Plan.objects.get(code="start").features == {}
