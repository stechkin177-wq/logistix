"""GET/PATCH /api/company/settings/ (Task 13)."""

import itertools
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.models import Subscription
from apps.core.api.auth import issue_tokens
from apps.core.audit.models import AuditLog
from apps.core.models import Company, Membership, Role, User
from apps.core.tenancy import tenant_context

pytestmark = pytest.mark.django_db

URL = "/api/company/settings/"
_n = itertools.count(1)


@pytest.fixture
def two(make_company):
    return make_company("Co A"), make_company("Co B")


def api_with_role(company, role_name):
    user = User.objects.create_user(email=f"cs{next(_n)}@x.kz", password="pw-pw-pw-1")
    with tenant_context(company.id):
        role = Role.objects.get(name=role_name)
    Membership.objects.create(user=user, company=company, role=role)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    return api


def test_get_shape_and_defaults(admin_client, company):
    r = admin_client.get(URL)
    assert r.status_code == 200
    assert r.data == {
        "name": "Fixture Co",
        "accounting_start": None,
        "timezone": "Asia/Almaty",
        "language": "ru",
        "login_audit_retention_days": 90,
    }


def test_patch_updates_fields(admin_client, company):
    r = admin_client.patch(
        URL,
        {
            "name": "  Новое имя ",
            "accounting_start": "2026-01-01",
            "timezone": "Europe/Moscow",
            "language": "kk",
        },
        format="json",
    )
    assert r.status_code == 200, r.content
    company.refresh_from_db()
    assert company.name == "Новое имя" and str(company.accounting_start) == "2026-01-01"
    assert company.timezone == "Europe/Moscow" and company.language == "kk"
    assert admin_client.get(URL).data["accounting_start"] == "2026-01-01"
    r = admin_client.patch(URL, {"accounting_start": None}, format="json")
    assert r.status_code == 200 and r.data["accounting_start"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"timezone": "Mars/Base"},
        {"timezone": ""},
        {"timezone": "../etc/passwd"},
        {"timezone": "/etc/localtime"},
        {"language": "en"},
        {"name": "  "},
        {"accounting_start": "вчера"},
    ],
)
def test_invalid_values_rejected(admin_client, company, payload):
    assert admin_client.patch(URL, payload, format="json").status_code == 400
    company.refresh_from_db()
    assert company.timezone == "Asia/Almaty" and company.language == "ru"


def test_permissions(company):
    observer = api_with_role(company, "Наблюдатель")  # company.view
    manager = api_with_role(company, "Менеджер")  # без company.*
    assert observer.get(URL).status_code == 200
    assert observer.patch(URL, {"language": "kk"}, format="json").status_code == 403
    assert manager.get(URL).status_code == 403
    assert manager.patch(URL, {"language": "kk"}, format="json").status_code == 403


def test_requires_auth(api_client):
    assert api_client.get(URL).status_code in (401, 403)


def test_isolation(two):
    (a, _, api_a), (b, _, api_b) = two
    r = api_a.patch(URL, {"name": "Только A", "timezone": "Asia/Aqtobe"}, format="json")
    assert r.status_code == 200
    assert api_b.get(URL).data["name"] == "Co B"
    assert api_b.get(URL).data["timezone"] == "Asia/Almaty"
    assert api_a.get(URL).data["name"] == "Только A"
    b.refresh_from_db()
    assert b.name == "Co B"


def test_changes_are_audited(admin_client, company):
    admin_client.patch(URL, {"timezone": "Asia/Aqtobe"}, format="json")
    admin_client.patch(URL, {"timezone": "Asia/Aqtobe"}, format="json")  # без изменений
    with tenant_context(company.id):
        rows = list(AuditLog.objects.filter(object_type="core.company", action="update"))
    assert len(rows) == 1
    assert rows[0].changes == {"timezone": ["Asia/Almaty", "Asia/Aqtobe"]}
    assert rows[0].object_id == str(company.pk)


def test_readonly_subscription_blocks_patch(company, admin_client):
    Subscription.objects.filter(company=company).update(ends_at=timezone.now() - timedelta(days=20))
    assert admin_client.get(URL).status_code == 200
    r = admin_client.patch(URL, {"name": "x"}, format="json")
    assert r.status_code == 403 and r.data["code"] == "subscription_readonly"
    assert Company.objects.get(pk=company.pk).name == "Fixture Co"
