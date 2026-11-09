"""T5-A: единый вход, платформенный контекст, роли владельца/администратора платформы."""

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.billing.models import BillingEvent, Subscription
from apps.core.models import Membership, User
from conftest import TEST_PASSWORD

pytestmark = pytest.mark.django_db

LOGIN = "/api/auth/login/"
PLANS = "/api/platform/plans/"


def login(email, password=TEST_PASSWORD):
    client = APIClient()
    r = client.post(LOGIN, {"login": email, "password": password}, format="json")
    if r.status_code == 200:
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.json()['access']}")
    return client, r


def as_token(access):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client


def test_owner_logs_in_without_membership_and_lands_in_platform(make_platform_client):
    _, owner = make_platform_client("owner")
    assert not Membership.objects.filter(user=owner).exists()
    client, r = login(owner.email)
    assert r.status_code == 200
    body = r.json()
    assert body["context"] == "platform" and body["platform_role"] == "owner"
    assert body["companies"] == []
    s = client.get("/api/platform/session/")
    assert s.status_code == 200
    data = s.json()
    assert data["context"] == "platform" and data["user"]["platform_role"] == "owner"
    assert "platform.plans.manage" in data["permissions"]


def test_user_without_company_or_role_still_cannot_log_in():
    User.objects.create_user(email="nobody@x.kz", password=TEST_PASSWORD)
    _, r = login("nobody@x.kz")
    assert r.status_code == 403


def test_ordinary_company_user_gets_company_context_and_no_platform(make_company):
    _, admin, _ = make_company()
    client, r = login(admin.email)
    assert r.json()["context"] == "company"
    assert client.get("/api/session/").status_code == 200
    for url in ("/api/platform/session/", PLANS, "/api/platform/companies/",
                "/api/platform/history/", "/api/platform/catalog/"):
        resp = client.get(url)
        assert resp.status_code == 403, url
        assert resp.json()["code"] == "platform_context_required"


def test_superuser_does_not_get_platform_rights(make_company):
    _, admin, _ = make_company()
    User.objects.filter(pk=admin.pk).update(is_superuser=True, is_staff=True)
    client, r = login(admin.email)
    assert r.json()["context"] == "company"
    assert client.get(PLANS).status_code == 403
    su = User.objects.create_superuser(email="su@x.kz", password=TEST_PASSWORD)
    assert su.platform_role == "" and su.is_platform_admin is False
    assert su.is_superuser is True
    _, r2 = login("su@x.kz")
    assert r2.status_code == 403  # ни роли, ни компании


def test_company_admin_cannot_switch_to_platform(make_company):
    _, _, client = make_company()
    r = client.post("/api/auth/switch-company/", {"context": "platform"}, format="json")
    assert r.status_code == 403


def test_platform_token_does_not_open_company_data(make_platform_client, make_company):
    make_company()
    client, _ = make_platform_client("owner")
    for url in ("/api/session/", "/api/roles/", "/api/users/", "/api/billing/usage/"):
        r = client.get(url)
        assert r.status_code == 403, url
        assert r.json()["code"] == "company_context_required"


def test_platform_admin_is_independent_of_tariffs_and_modules(make_platform_client, make_company):
    company, _, _ = make_company()
    Subscription.objects.filter(company=company).update(status="blocked")
    client, _ = make_platform_client("owner")
    assert client.get(PLANS).status_code == 200
    assert client.get(f"/api/platform/subscriptions/{company.pk}/").status_code == 200
    assert client.get("/api/platform/session/").status_code == 200


def test_roles_owner_full_admin_limited(make_platform_client, make_company):
    company, _, _ = make_company()
    owner, _ = make_platform_client("owner")
    admin, _ = make_platform_client("admin")
    # чтение доступно обоим
    for c in (owner, admin):
        assert c.get(PLANS).status_code == 200
        assert c.get("/api/platform/history/").status_code == 200
    # тарифы меняет только владелец
    body = {"code": "zz", "name": "ZZ", "price": "1", "currency": "KZT", "billing_type": "monthly"}
    assert admin.post(PLANS, body, format="json").status_code == 403
    assert owner.post(PLANS, body, format="json").status_code == 201
    # подписки: оба; блокировка компании: только владелец
    url = f"/api/platform/subscriptions/{company.pk}"
    assert admin.post(f"{url}/renew/", {"periods": 1}, format="json").status_code == 200
    assert admin.post(f"{url}/block/", {"reason": "x"}, format="json").status_code == 403
    assert owner.post(f"{url}/block/", {"reason": ""}, format="json").status_code == 400
    r = owner.post(f"{url}/block/", {"reason": "неоплата"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "blocked"
    ev = BillingEvent.objects.filter(kind="company", key=str(company.pk), action="block").get()
    assert ev.changes["reason"] == "неоплата" and ev.user is not None
    assert admin.post(f"{url}/unblock/", {"reason": "x"}, format="json").status_code == 403
    r = owner.post(f"{url}/unblock/", {"reason": "оплачено"}, format="json")
    assert r.status_code == 200 and r.json()["status"] != "blocked"


def test_role_is_checked_live_removed_role_loses_access(make_platform_client):
    client, user = make_platform_client("owner")
    assert client.get(PLANS).status_code == 200
    User.objects.filter(pk=user.pk).update(platform_role="")
    assert client.get(PLANS).status_code == 401  # платформенный доступ закрыт сразу
    assert client.get("/api/platform/session/").status_code == 401


def test_context_switching_keeps_isolation(make_company):
    company_a, admin, _ = make_company("A")
    company_b, _, _ = make_company("B")
    User.objects.filter(pk=admin.pk).update(platform_role="owner")
    Membership.objects.filter(user=admin).update(is_active=True)
    client, r = login(admin.email)
    assert r.json()["context"] == "platform"  # роль -> сначала Центр управления
    assert [c["id"] for c in r.json()["companies"]] == [company_a.id]
    # в свою компанию: токен компании, платформенные права не действуют
    sw = client.post("/api/auth/switch-company/", {"company_id": company_a.id}, format="json")
    assert sw.status_code == 200 and sw.json()["context"] == "company"
    in_company = as_token(sw.json()["access"])
    assert in_company.get("/api/session/").json()["company"]["id"] == company_a.id
    assert in_company.get(PLANS).status_code == 403
    # чужая компания недоступна
    bad = client.post("/api/auth/switch-company/", {"company_id": company_b.id}, format="json")
    assert bad.status_code == 403
    # обратно в платформу
    back = in_company.post("/api/auth/switch-company/", {"context": "platform"}, format="json")
    assert back.status_code == 200 and back.json()["context"] == "platform"
    plat = as_token(back.json()["access"])
    assert plat.get(PLANS).status_code == 200
    assert plat.get("/api/session/").status_code == 403
    me = plat.get("/api/auth/me/").json()
    assert me["context"] == "platform" and me["company_id"] is None


def test_switch_requires_exactly_one_target(make_company):
    _, _, client = make_company()
    assert client.post("/api/auth/switch-company/", {}, format="json").status_code == 400
    r = client.post("/api/auth/switch-company/", {"company_id": 1, "context": "platform"},
                    format="json")
    assert r.status_code == 400


def test_platform_logins_and_switches_are_journaled(make_platform_client):
    _, owner = make_platform_client("owner")
    login(owner.email, "wrong-password")
    login(owner.email)
    actions = list(
        BillingEvent.objects.filter(kind="auth", key=str(owner.pk))
        .order_by("id").values_list("action", flat=True)
    )
    assert actions == ["login_failed", "login"]
    ev = BillingEvent.objects.filter(kind="auth", action="login_failed").get()
    assert "ip" in ev.changes and "password" not in str(ev.changes)


def test_refresh_keeps_platform_context(make_platform_client):
    _, owner = make_platform_client("owner")
    _, r = login(owner.email)
    ref = APIClient().post("/api/auth/refresh/", {"refresh": r.json()["refresh"]}, format="json")
    assert ref.status_code == 200
    assert as_token(ref.json()["access"]).get("/api/platform/session/").status_code == 200


def test_commands_create_owner_and_set_role(monkeypatch):
    monkeypatch.setenv("PLATFORM_OWNER_PASSWORD", "very-long-pass-1")
    call_command("create_platform_owner", "Boss@Example.kz")
    boss = User.objects.get(email="boss@example.kz")
    assert boss.platform_role == "owner" and not Membership.objects.filter(user=boss).exists()
    plain = User.objects.create_user(email="p@x.kz", password=TEST_PASSWORD)
    call_command("set_platform_role", "p@x.kz", "admin")
    plain.refresh_from_db()
    assert plain.platform_role == "admin"
    call_command("set_platform_role", "p@x.kz", "none")
    plain.refresh_from_db()
    assert plain.platform_role == ""
    assert BillingEvent.objects.filter(kind="auth", action="platform_role").count() == 2
