"""A6: API модулей компании и профилей деятельности; A5: права и аудит."""

import pytest
from rest_framework.test import APIClient

from apps.billing.models import Plan
from apps.core.api.auth import issue_tokens
from apps.core.audit.models import AuditLog
from apps.core.models import Membership, Role, User
from apps.core.module_services import enabled_module_codes
from apps.core.tenancy import set_current_company, tenant_context
from apps.finance.models import CompanyFinancialSettings

pytestmark = pytest.mark.django_db

URL = "/api/company/modules/"
ALL_PLAN = [
    "forwarding", "fleet", "finance", "documents", "drivers", "driver_app", "gps", "ocr",
    "notifications", "analytics",
]  # fmt: skip


@pytest.fixture
def wide_plan(db):
    Plan.objects.filter(code="start").update(modules=ALL_PLAN)


def member_client(company, name, permissions):
    user = User.objects.create_user(email=f"{name}@modapi.kz", password="x")
    with tenant_context(company.id):
        role = Role.objects.create(name=f"Роль {name}", permissions=permissions)
    Membership.objects.create(user=user, company=company, role=role, is_active=True)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    set_current_company(None)
    return user, api


def by_code(response):
    return {m["code"]: m for m in response.json()["modules"]}


def test_permission_required_for_every_endpoint(make_company):
    company, _, _ = make_company("Perm", modules=["forwarding"])
    _, nobody = member_client(company, "nobody", ["company.view", "company.update"])
    for method, path in [
        ("get", URL),
        ("post", f"{URL}documents/enable/"),
        ("post", f"{URL}documents/disable/"),
        ("post", f"{URL}apply-profile/"),
        ("get", "/api/activity-profiles/"),
    ]:
        assert getattr(nobody, method)(path).status_code == 403, path
    anonymous = APIClient()
    assert anonymous.get(URL).status_code == 401


def test_list_shape_and_states(make_company, wide_plan):
    company, _, api = make_company("List", modules=["forwarding"])
    response = api.get(URL)
    assert response.status_code == 200
    body = response.json()
    assert body["plan_code"] == "start"
    modules = by_code(response)
    assert list(modules)[0] == "core" and len(modules) == 11
    core = modules["core"]
    assert core["enabled"] and core["is_core"] and not core["can_disable"]
    fwd = modules["forwarding"]
    assert fwd["enabled"] and fwd["dependents"] == ["finance"]
    assert fwd["blocker"]["code"] == "module_has_dependents"
    assert "Финансы" in fwd["blocker"]["detail"]  # русский текст
    assert modules["finance"]["requires"] == ["core", "forwarding"]
    assert modules["documents"]["can_disable"]
    assert modules["fleet"]["can_enable"] and not modules["fleet"]["enabled"]
    assert modules["gps"]["blocker"]["code"] == "module_requires"
    assert modules["gps"]["blocker"]["modules"] == ["fleet"]
    for field in ("name", "description", "status", "available_in_plan", "effective", "enhances"):
        assert field in fwd


def test_list_reports_plan_availability(make_company):
    company, _, api = make_company("Plan", modules=["forwarding"])
    Plan.objects.filter(code="start").update(
        modules=["logistics", "forwarding", "finance", "documents"]
    )
    modules = by_code(api.get(URL))
    assert modules["fleet"]["available_in_plan"] is False
    assert modules["fleet"]["blocker"]["code"] == "module_not_in_plan"
    assert "тарифе" in modules["fleet"]["blocker"]["detail"]


def test_enable_and_disable_with_reason_and_audit(make_company, wide_plan):
    company, admin, api = make_company("Aud", modules=["forwarding"])
    resp = api.post(f"{URL}fleet/enable/", {"reason": "Появился автопарк"}, format="json")
    assert resp.status_code == 200 and by_code(resp)["fleet"]["enabled"]
    assert "fleet" in enabled_module_codes(company.id)
    company.refresh_from_db()
    assert company.modules == enabled_module_codes(company.id)
    resp = api.post(f"{URL}documents/disable/", {"reason": "Не используем"}, format="json")
    assert resp.status_code == 200 and not by_code(resp)["documents"]["enabled"]
    with tenant_context(company.id):
        entries = list(AuditLog.objects.filter(object_type="core.companymodule").order_by("id"))
    assert [e.changes["module_code"] for e in entries] == ["fleet", "documents"]
    assert entries[0].changes["enabled"] == [None, True]  # первое включение
    assert entries[1].changes["enabled"] == [True, False]
    assert entries[1].changes["reason"] == "Не используем"
    assert all(e.user == admin for e in entries)


def test_error_texts_in_russian_with_codes(make_company, wide_plan):
    company, _, api = make_company("Err", modules=["forwarding"])
    r = api.post(f"{URL}forwarding/disable/", {"reason": "x"}, format="json")
    assert r.status_code == 409
    assert r.json()["code"] == "module_has_dependents" and r.json()["modules"] == ["finance"]
    assert "зависят" in r.json()["detail"]
    r = api.post(f"{URL}gps/enable/", {}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "module_requires"
    assert "Сначала включите" in r.json()["detail"]
    r = api.post(f"{URL}core/disable/", {}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "module_core"
    r = api.post(f"{URL}bogus/enable/", {}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "module_unknown"
    Plan.objects.filter(code="start").update(
        modules=["logistics", "forwarding", "finance", "documents"]
    )
    r = api.post(f"{URL}fleet/enable/", {}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "module_not_in_plan"
    assert "тарифе" in r.json()["detail"]
    CompanyFinancialSettings.all_objects.filter(company=company).update(engine="shadow")
    r = api.post(f"{URL}finance/disable/", {"reason": "x"}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "module_protected"


def test_cascade_flag(make_company, wide_plan):
    company, _, api = make_company("Casc", modules=["forwarding"])
    r = api.post(f"{URL}forwarding/disable/", {"reason": "всё", "cascade": True}, format="json")
    assert r.status_code == 200
    state = by_code(r)
    assert not state["forwarding"]["enabled"] and not state["finance"]["enabled"]
    assert state["documents"]["enabled"]


def test_double_submit_is_harmless(make_company, wide_plan):
    company, _, api = make_company("Dbl", modules=["forwarding"])
    first = api.post(f"{URL}fleet/enable/", {"reason": "a"}, format="json")
    second = api.post(f"{URL}fleet/enable/", {"reason": "a"}, format="json")
    assert first.status_code == second.status_code == 200
    with tenant_context(company.id):
        assert (
            AuditLog.objects.filter(
                object_type="core.companymodule", changes__module_code="fleet"
            ).count()
            == 1
        )
    again = api.post(f"{URL}fleet/disable/", {"reason": "b"}, format="json")
    again2 = api.post(f"{URL}fleet/disable/", {"reason": "b"}, format="json")
    assert again.status_code == again2.status_code == 200


def test_reason_validation(make_company, wide_plan):
    _, _, api = make_company("Rsn", modules=["forwarding"])
    r = api.post(f"{URL}fleet/enable/", {"reason": "x" * 501}, format="json")
    assert r.status_code == 400


def test_activity_profiles_list(make_company, wide_plan):
    _, _, api = make_company("Prof", modules=["forwarding"])
    data = api.get("/api/activity-profiles/").json()
    names = {p["name"]: p for p in data}
    assert set(names) == {"Экспедитор", "Перевозчик", "Экспедитор и перевозчик"}
    assert names["Перевозчик"]["modules"] == ["logistics", "finance", "fleet", "drivers", "documents"]
    assert names["Экспедитор"]["already_enabled"] == [
        "logistics",
        "forwarding",
        "finance",
        "documents",
    ]
    Plan.objects.filter(code="start").update(
        modules=["logistics", "forwarding", "finance", "documents"]
    )
    data = {p["name"]: p for p in api.get("/api/activity-profiles/").json()}
    assert data["Перевозчик"]["unavailable_modules"] == ["fleet", "drivers"]


def test_apply_profile_enables_missing_and_keeps_others(make_company, wide_plan):
    company, _, api = make_company("App", modules=["fleet"])
    r = api.post(f"{URL}apply-profile/", {"profile": "forwarder"}, format="json")
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["enabled"] == ["logistics", "forwarding", "finance", "documents"]
    assert result["disabled"] == [] and result["skipped"] == []
    assert set(enabled_module_codes(company.id)) == {
        "fleet",
        "logistics",
        "forwarding",
        "finance",
        "documents",
    }


def test_apply_profile_skips_unavailable_by_plan_and_reports(make_company):
    company, _, api = make_company("Skip", modules=["forwarding"])
    Plan.objects.filter(code="start").update(
        modules=["logistics", "forwarding", "finance", "documents"]
    )
    r = api.post(f"{URL}apply-profile/", {"profile": "carrier"}, format="json")
    assert r.status_code == 200
    skipped = {s["code"]: s for s in r.json()["result"]["skipped"]}
    assert set(skipped) == {"fleet", "drivers"}
    assert all(s["error_code"] == "module_not_in_plan" for s in skipped.values())
    assert set(enabled_module_codes(company.id)) == {
        "logistics",
        "forwarding",
        "finance",
        "documents",
    }


def test_apply_profile_without_replace_does_not_disable(make_company, wide_plan):
    company, _, api = make_company("NoRep", modules=["forwarding", "fleet"])
    r = api.post(f"{URL}apply-profile/", {"profile": "forwarder"}, format="json")
    assert r.json()["result"]["disabled"] == []
    assert "fleet" in enabled_module_codes(company.id)


def test_apply_profile_replace_disables_the_rest(make_company, wide_plan):
    company, _, api = make_company("Rep", modules=["forwarding", "fleet"])
    r = api.post(f"{URL}apply-profile/", {"profile": "forwarder", "replace": True}, format="json")
    assert r.status_code == 200
    assert r.json()["result"]["disabled"] == ["fleet"]
    assert set(enabled_module_codes(company.id)) == {
        "logistics",
        "forwarding",
        "finance",
        "documents",
    }
    company.refresh_from_db()
    assert company.modules == enabled_module_codes(company.id)


def test_apply_profile_replace_is_atomic_when_protected(make_company, wide_plan, monkeypatch):
    from apps.core import module_services

    company, _, api = make_company("RepProt", modules=["forwarding", "fleet"])
    # профиль «Перевозчик» не содержит forwarding; защита его отключения откатывает всё
    monkeypatch.setitem(module_services._DISABLE_GUARDS, "forwarding", [lambda c: "защита"])
    before = set(enabled_module_codes(company.id))
    r = api.post(f"{URL}apply-profile/", {"profile": "carrier", "replace": True}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "module_protected"
    assert set(enabled_module_codes(company.id)) == before


def test_apply_unknown_profile(make_company):
    _, _, api = make_company("NoProf", modules=["forwarding"])
    assert api.post(f"{URL}apply-profile/", {"profile": "zzz"}, format="json").status_code == 404
    assert api.post(f"{URL}apply-profile/", {}, format="json").status_code == 400


def test_role_with_permission_gets_access_and_others_do_not(make_company, wide_plan):
    company, _, admin_api = make_company("Role", modules=["forwarding"])
    _, user_api = member_client(company, "granted", ["company.manage_modules"])
    assert user_api.get(URL).status_code == 200
    assert user_api.post(f"{URL}fleet/enable/", {"reason": "ok"}, format="json").status_code == 200
    _, other_api = member_client(company, "plain", ["company.view"])
    assert other_api.get(URL).status_code == 403


def test_company_isolation(make_company, wide_plan):
    a, _, api_a = make_company("IsoA", modules=["forwarding"])
    b, _, api_b = make_company("IsoB", modules=["forwarding", "fleet"])
    api_a.post(f"{URL}documents/disable/", {"reason": "A"}, format="json")
    assert "documents" in enabled_module_codes(b.id)
    assert by_code(api_b.get(URL))["documents"]["enabled"]
    assert not by_code(api_a.get(URL))["documents"]["enabled"]
    assert not by_code(api_a.get(URL))["fleet"]["enabled"]


def test_readonly_subscription_blocks_changes(make_company, wide_plan):
    from datetime import timedelta

    from django.utils import timezone

    from apps.billing.models import Subscription

    company, _, api = make_company("RO", modules=["forwarding"])
    Subscription.objects.filter(company=company).update(
        status=Subscription.READONLY, ends_at=timezone.now() - timedelta(days=60)
    )
    assert api.get(URL).status_code in (200, 403)
    assert api.post(f"{URL}fleet/enable/", {}, format="json").status_code == 403
