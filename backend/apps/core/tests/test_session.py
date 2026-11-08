from datetime import timedelta

import pytest
from django.utils import timezone

from apps.billing.models import Plan, Subscription
from apps.core.api.auth import issue_tokens
from apps.core.models import Membership, Role, User

pytestmark = pytest.mark.django_db

URL = "/api/session/"


def set_sub(company, **fields):
    Subscription.objects.filter(company=company).update(**fields)


def test_unauthenticated_gets_401(api_client):
    assert api_client.get(URL).status_code == 401


def test_admin_session_shape(make_company):
    company, admin, client = make_company("Alpha")
    data = client.get(URL).json()
    assert data["user"] == {
        "id": admin.pk,
        "email": admin.email,
        "phone": admin.phone,
        "full_name": admin.full_name,
    }
    assert data["company"] == {
        "id": company.id,
        "name": "Alpha",
        "timezone": company.timezone,
        "language": company.language,
    }
    assert data["companies"] == [{"id": company.id, "name": "Alpha"}]
    assert data["role"]["name"] == "Администратор"
    assert data["modules"] == ["forwarding", "logistics", "finance", "documents"]
    assert "users.view" in data["permissions"] and "orders.update" in data["permissions"]
    sub = data["subscription"]
    assert sub["status"] in ("active", "trial")
    assert sub["plan_code"] == "start"
    assert sub["is_free_period"] is True
    assert isinstance(sub["days_left"], int) and sub["days_left"] > 0


def test_manager_gets_own_permissions(make_company):
    company, _, _ = make_company()
    manager = User.objects.create_user(email="mgr@x.kz", password="s3cret-pass")
    role = Role.all_objects.get(company=company, name="Менеджер")
    Membership.objects.create(user=manager, company=company, role=role)
    from rest_framework.test import APIClient

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(manager, company.id)['access']}")
    data = client.get(URL).json()
    assert data["role"] == {"id": role.id, "name": "Менеджер"}
    assert sorted(data["permissions"]) == sorted(role.permissions)
    assert "users.view" not in data["permissions"]
    assert "clients.view" in data["permissions"]


def test_tenants_are_isolated(make_company):
    a, admin_a, client_a = make_company("Alpha")
    b, admin_b, client_b = make_company("Beta")
    data = client_b.get(URL).json()
    assert data["company"]["id"] == b.id and data["company"]["name"] == "Beta"
    assert data["user"]["email"] == admin_b.email
    assert data["companies"] == [{"id": b.id, "name": "Beta"}]
    text = str(data)
    assert "Alpha" not in text and admin_a.email not in text
    assert client_a.get(URL).json()["company"]["id"] == a.id


def test_companies_lists_only_active_memberships_of_user(make_company):
    a, admin_a, client_a = make_company("Alpha")
    b, _, _ = make_company("Beta")
    c, _, _ = make_company("Gamma")
    Membership.objects.create(
        user=admin_a, company=b, role=Role.all_objects.get(company=b, name="Менеджер")
    )
    Membership.objects.create(
        user=admin_a,
        company=c,
        role=Role.all_objects.get(company=c, name="Менеджер"),
        is_active=False,
    )
    ids = [x["id"] for x in client_a.get(URL).json()["companies"]]
    assert ids == [a.id, b.id]


def test_fleet_only_company_has_no_forwarding(make_company):
    _, _, client = make_company("Fleet", modules=["fleet"])
    assert client.get(URL).json()["modules"] == ["fleet"]


def test_modules_are_intersected_with_plan(make_company):
    company, _, client = make_company("Both", modules=["forwarding", "fleet"])
    plan = Plan.objects.create(
        code="fwd-only", name="Fwd", billing_type="monthly", modules=["forwarding"]
    )
    set_sub(company, plan=plan)
    assert client.get(URL).json()["modules"] == ["forwarding"]


def test_readonly_company_still_gets_200(make_company):
    company, _, client = make_company()
    set_sub(company, ends_at=timezone.now() - timedelta(days=20))
    resp = client.get(URL)
    assert resp.status_code == 200
    assert resp.json()["subscription"]["status"] == "readonly"
    assert resp.json()["subscription"]["days_left"] == 0


def test_grace_status_reported(make_company):
    company, _, client = make_company()
    set_sub(company, ends_at=timezone.now() - timedelta(days=3))
    sub = client.get(URL).json()["subscription"]
    assert sub["status"] == "grace"
    assert sub["days_left"] == 0
    assert sub["grace_days_left"] == 11  # 14 дней льготы минус 3 прошедших


def test_grace_days_left_is_null_outside_grace(admin_client):
    assert admin_client.get(URL).json()["subscription"]["grace_days_left"] is None


def test_blocked_company_gets_403(make_company):
    company, _, client = make_company()
    set_sub(company, status=Subscription.BLOCKED)
    resp = client.get(URL)
    assert resp.status_code == 403
    assert resp.json()["code"] == "subscription_blocked"


def test_query_count_is_bounded(make_company, django_assert_max_num_queries):
    _, _, client = make_company()
    with django_assert_max_num_queries(9):  # +1 запрос: оформление компании
        assert client.get(URL).status_code == 200


# --- оформление компании в сессии ---


def test_branding_defaults_without_row_and_no_row_created(make_company):
    from apps.core.models import CompanyBranding

    company, _, client = make_company()
    data = client.get(URL).json()["branding"]
    assert set(data) == {"app_name", "logo_url", "primary_color", "theme"}
    assert data["logo_url"] is None
    assert not CompanyBranding.objects.filter(company=company).exists()


def test_branding_of_own_company_only(make_company):
    from apps.core.models import CompanyBranding

    a, _, client_a = make_company("Alpha")
    b, _, client_b = make_company("Beta")
    CompanyBranding.objects.create(
        company=a, app_name="Альфа-Логистик", primary_color="#AA0000", theme="dark"
    )
    CompanyBranding.objects.create(company=b, app_name="Бета", primary_color="#00BB00")
    data_b = client_b.get(URL).json()["branding"]
    assert data_b["app_name"] == "Бета" and data_b["primary_color"] == "#00BB00"
    assert "Альфа" not in str(client_b.get(URL).json()) and "#AA0000" not in str(data_b)
    assert client_a.get(URL).json()["branding"]["app_name"] == "Альфа-Логистик"


def test_dispatcher_without_company_view_gets_company_branding(make_company):
    from rest_framework.test import APIClient

    from apps.core.models import CompanyBranding

    company, _, _ = make_company()
    CompanyBranding.objects.create(company=company, app_name="Мой бренд", primary_color="#123456")
    user = User.objects.create_user(email="disp@x.kz", password="s3cret-pass")
    role = Role.all_objects.get(company=company, name="Диспетчер")
    Membership.objects.create(user=user, company=company, role=role)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    assert "company.view" not in role.permissions
    assert client.get("/api/company/branding/").status_code == 403
    data = client.get(URL).json()["branding"]
    assert data["app_name"] == "Мой бренд" and data["primary_color"] == "#123456"
