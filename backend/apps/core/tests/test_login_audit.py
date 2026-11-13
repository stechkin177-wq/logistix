"""Журнал входов: успешные и неудачные попытки, право audit.view, срок хранения."""

import io
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core import audit
from apps.core.api.auth import issue_tokens
from apps.core.audit.models import AuditLog
from apps.core.audit.retention import set_login_retention_days
from apps.core.models import Membership, Role, User
from apps.core.tenancy import tenant_context

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ng-pass-91"


def login_rows(company, **filters):
    with tenant_context(company.id):
        rows = AuditLog.objects.filter(action__in=audit.LOGIN_ACTIONS, **filters)
        return list(rows.order_by("id"))


def post_login(client, login, password):
    return client.post(
        "/api/auth/login/",
        {"login": login, "password": password},
        format="json",
        HTTP_USER_AGENT="TestBrowser/1.0",
    )


def test_successful_login_is_logged_with_device_and_no_secrets(make_company):
    company, admin, _ = make_company()
    r = post_login(APIClient(), admin.email, "s3cret-pass")
    assert r.status_code == 200
    (row,) = login_rows(company)
    assert row.action == "login" and row.user_id == admin.pk
    assert row.changes == {"user_agent": "TestBrowser/1.0"}
    assert "s3cret-pass" not in str(row.changes)


def test_failed_login_of_known_user_is_logged_and_response_is_same_401(make_company):
    company, admin, _ = make_company()
    bad = post_login(APIClient(), admin.email, "wrong-password")
    unknown = post_login(APIClient(), "nobody@fixture.kz", "wrong-password")
    # ответ для известного и неизвестного логина одинаков: журнал не раскрывает, кто существует
    assert bad.status_code == unknown.status_code == 401
    assert bad.json() == unknown.json()
    (row,) = login_rows(company)
    assert row.action == "login_failed"
    assert row.changes["reason"] == "bad_credentials"
    assert "wrong-password" not in str(row.changes)


def test_unknown_login_writes_nothing(make_company):
    company, _, _ = make_company()
    post_login(APIClient(), "nobody@fixture.kz", "x")
    assert login_rows(company) == []


def test_failed_login_of_inactive_user_has_reason(make_company):
    company, admin, _ = make_company()
    User.objects.filter(pk=admin.pk).update(is_active=False)
    assert post_login(APIClient(), admin.email, "s3cret-pass").status_code == 401
    (row,) = login_rows(company)
    assert row.changes["reason"] == "inactive"


def test_audit_api_needs_audit_view_not_company_view(make_company):
    company, admin, _ = make_company()
    user = User.objects.create_user(email="viewer@fixture.kz", password=PASSWORD)
    with tenant_context(company.id):
        role = Role.objects.create(name="Только настройки", permissions=["company.view"])
    Membership.objects.create(user=user, company=company, role=role)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    assert client.get("/api/audit/").status_code == 403
    with tenant_context(company.id):
        role.permissions = ["audit.view"]
        role.save()
    assert client.get("/api/audit/").status_code == 200


def test_observer_role_has_no_audit_view_by_default(make_company):
    company, _, _ = make_company()
    with tenant_context(company.id):
        observer = Role.objects.get(name="Наблюдатель")
        admin_role = Role.objects.get(name="Администратор")
    assert "audit.view" not in observer.permissions
    assert "audit.view" in admin_role.permissions


def test_audit_actions_filter_returns_only_login_events(make_company):
    company, admin, client = make_company()
    post_login(APIClient(), admin.email, "s3cret-pass")
    post_login(APIClient(), admin.email, "bad")
    with tenant_context(company.id):
        audit.log("update", admin, admin, {"x": [1, 2]}, object_type="core.thing", object_id=1)
    data = client.get("/api/audit/", {"actions": "login,login_failed"}).json()
    assert {x["action"] for x in data["results"]} == {"login", "login_failed"}
    assert client.get("/api/audit/", {"actions": "login,bogus"}).status_code == 400


def _old_login(company, user, action, days):
    with tenant_context(company.id):
        row = audit.log(action, user, user, {}, object_type="core.user", object_id=user.pk)
        AuditLog.objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(days=days))
        return row.pk


def test_purge_uses_company_retention_and_touches_only_login_events(make_company):
    a_company, a_user, _ = make_company("A")
    b_company, b_user, _ = make_company("B")
    with tenant_context(b_company.id):
        set_login_retention_days(365)
    old_a = _old_login(a_company, a_user, "login", 100)
    fresh_a = _old_login(a_company, a_user, "login_failed", 10)
    old_b = _old_login(b_company, b_user, "login", 100)  # у B срок год - остаётся
    with tenant_context(a_company.id):
        other = audit.log(
            "update", a_user, a_user, {"n": [1, 2]}, object_type="core.thing", object_id=1
        )
        AuditLog.objects.filter(pk=other.pk).update(created_at=timezone.now() - timedelta(days=400))

    dry = io.StringIO()
    call_command("purge_login_audit", "--dry-run", stdout=dry)
    assert "найдено: 1" in dry.getvalue()
    with tenant_context(a_company.id):
        assert AuditLog.objects.filter(pk=old_a).exists()  # сухой прогон ничего не удаляет

    call_command("purge_login_audit", stdout=io.StringIO())
    with tenant_context(a_company.id):
        assert not AuditLog.objects.filter(pk=old_a).exists()
        assert AuditLog.objects.filter(pk=fresh_a).exists()
        assert AuditLog.objects.filter(pk=other.pk).exists()  # не событие входа: не трогается
    with tenant_context(b_company.id):
        assert AuditLog.objects.filter(pk=old_b).exists()


def test_retention_default_and_limits(make_company):
    company, _, client = make_company()
    assert client.get("/api/company/settings/").json()["login_audit_retention_days"] == 90
    ok = client.patch("/api/company/settings/", {"login_audit_retention_days": 180}, format="json")
    assert ok.status_code == 200 and ok.json()["login_audit_retention_days"] == 180
    for bad in (7, 5000):
        payload = {"login_audit_retention_days": bad}
        r = client.patch("/api/company/settings/", payload, format="json")
        assert r.status_code == 400
