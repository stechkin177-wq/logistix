from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.test import RequestFactory
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from apps.billing.models import Plan, Subscription
from apps.core.middleware import TenantContextMiddleware
from apps.core.models import Company, Membership, User
from apps.core.tenancy import get_current_company_id, set_current_company

pytestmark = pytest.mark.django_db

PASSWORD = "s3cret-pass"


@pytest.fixture(autouse=True)
def _reset_tenant():
    set_current_company(None)
    yield
    set_current_company(None)


def company_with_subscription(name):
    """Компания с действующей подпиской (шлюз подписки требует её для входа)."""
    company = Company.objects.create(name=name)
    Subscription.objects.create(
        company=company,
        plan=Plan.objects.get(code="start"),
        starts_at=timezone.now(),
        ends_at=timezone.now() + timedelta(days=365),
    )
    return company


@pytest.fixture
def company_a():
    return company_with_subscription("A")


@pytest.fixture
def company_b():
    return company_with_subscription("B")


@pytest.fixture
def user(company_a):
    u = User.objects.create_user(
        email="Ivan@Example.COM", phone="8 700 111 22 33", password=PASSWORD, full_name="Иван"
    )
    Membership.objects.create(user=u, company=company_a)
    return u


def login(client, login_value, password=PASSWORD):
    return client.post(
        "/api/auth/login/", {"login": login_value, "password": password}, format="json"
    )


def auth(client, token):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")


# --- модель ---


def test_user_normalises_email_and_phone(user):
    user.refresh_from_db()
    assert user.email == "ivan@example.com"
    assert user.phone == "+77001112233"


def test_user_needs_email_or_phone():
    with pytest.raises(ValidationError):
        User(full_name="x").full_clean(exclude=["password"])
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.bulk_create([User(full_name="x", password="!")])


def test_blank_email_stored_as_null_and_phone_only_user_ok():
    u1 = User.objects.create_user(phone="7001112233", password=PASSWORD, email="")
    u2 = User.objects.create_user(phone="7002223344", password=PASSWORD, email="")
    assert u1.email is None and u2.email is None


def test_phone_unique_after_normalisation(user):
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user(phone="+7(700)1112233", password=PASSWORD)


def test_invalid_phone_rejected_on_create():
    with pytest.raises(ValueError):
        User.objects.create_user(phone="12345", password=PASSWORD)


def test_membership_unique(user, company_a):
    with pytest.raises(IntegrityError), transaction.atomic():
        Membership.objects.create(user=user, company=company_a)


def test_create_superuser():
    su = User.objects.create_superuser(email="Root@x.kz", password=PASSWORD)
    assert su.is_superuser and su.is_staff and su.email == "root@x.kz"
    assert User.objects.get_by_natural_key("ROOT@x.kz") == su


# --- вход ---


def test_login_by_email(api_client, user, company_a):
    r = login(api_client, "IVAN@example.com")
    assert r.status_code == 200
    assert r.data["companies"] == [{"id": company_a.id, "name": "A"}]
    assert AccessToken(r.data["access"])["company_id"] == company_a.id
    assert r.data["refresh"]


@pytest.mark.parametrize("value", ["8 700 111 22 33", "+7(700)1112233", "7001112233"])
def test_login_by_phone(api_client, user, company_a, value):
    r = login(api_client, value)
    assert r.status_code == 200
    assert AccessToken(r.data["access"])["company_id"] == company_a.id


def test_login_invalid_phone_is_400(api_client, user):
    r = login(api_client, "12345")
    assert r.status_code == 400


def test_login_wrong_password_and_unknown_user_same_error(api_client, user):
    r1 = login(api_client, "ivan@example.com", "bad")
    r2 = login(api_client, "nobody@example.com", "bad")
    assert r1.status_code == r2.status_code == 401
    assert r1.data == r2.data
    assert "Неверный логин или пароль" in str(r1.data["detail"])


def test_login_user_without_membership_gets_no_token(api_client):
    User.objects.create_user(email="lone@x.kz", password=PASSWORD)
    r = login(api_client, "lone@x.kz")
    assert r.status_code == 403
    assert "access" not in r.data


def test_login_inactive_membership_or_user_gets_no_token(api_client, user):
    Membership.objects.filter(user=user).update(is_active=False)
    assert login(api_client, "ivan@example.com").status_code == 403
    Membership.objects.filter(user=user).update(is_active=True)
    User.objects.filter(pk=user.pk).update(is_active=False)
    assert login(api_client, "ivan@example.com").status_code == 401


# --- аутентификация / компания ---


def test_me_sets_company_context_and_resets_after(api_client, user, company_a):
    r = login(api_client, "ivan@example.com")
    auth(api_client, r.data["access"])
    me = api_client.get("/api/auth/me/")
    assert me.status_code == 200
    assert me.data["company_id"] == company_a.id
    assert me.data["context_company_id"] == company_a.id
    assert get_current_company_id() is None


def test_unauthenticated_is_401(api_client):
    assert api_client.get("/api/auth/me/").status_code == 401


def test_token_without_company_rejected(api_client, user):
    from rest_framework_simplejwt.tokens import RefreshToken

    token = RefreshToken.for_user(user).access_token
    auth(api_client, str(token))
    assert api_client.get("/api/auth/me/").status_code == 401


def test_deactivated_membership_stops_working(api_client, user):
    r = login(api_client, "ivan@example.com")
    auth(api_client, r.data["access"])
    assert api_client.get("/api/auth/me/").status_code == 200
    Membership.objects.filter(user=user).update(is_active=False)
    assert api_client.get("/api/auth/me/").status_code == 401
    assert get_current_company_id() is None


def test_deactivated_user_stops_working(api_client, user):
    r = login(api_client, "ivan@example.com")
    auth(api_client, r.data["access"])
    User.objects.filter(pk=user.pk).update(is_active=False)
    assert api_client.get("/api/auth/me/").status_code == 401


def test_refresh_token_carries_company(api_client, user, company_a):
    r = login(api_client, "ivan@example.com")
    r2 = api_client.post("/api/auth/refresh/", {"refresh": r.data["refresh"]}, format="json")
    assert r2.status_code == 200
    assert AccessToken(r2.data["access"])["company_id"] == company_a.id


# --- switch-company ---


def test_switch_company_ok(api_client, user, company_b):
    Membership.objects.create(user=user, company=company_b)
    r = login(api_client, "ivan@example.com")
    auth(api_client, r.data["access"])
    s = api_client.post("/api/auth/switch-company/", {"company_id": company_b.id}, format="json")
    assert s.status_code == 200
    assert AccessToken(s.data["access"])["company_id"] == company_b.id
    auth(api_client, s.data["access"])
    assert api_client.get("/api/auth/me/").data["company_id"] == company_b.id


def test_switch_company_foreign_company_403(api_client, user, company_b):
    r = login(api_client, "ivan@example.com")
    auth(api_client, r.data["access"])
    s = api_client.post("/api/auth/switch-company/", {"company_id": company_b.id}, format="json")
    assert s.status_code == 403
    assert "access" not in s.data


def test_switch_company_inactive_membership_403(api_client, user, company_b):
    Membership.objects.create(user=user, company=company_b, is_active=False)
    r = login(api_client, "ivan@example.com")
    auth(api_client, r.data["access"])
    s = api_client.post("/api/auth/switch-company/", {"company_id": company_b.id}, format="json")
    assert s.status_code == 403


def test_switch_company_nonexistent_403_and_bad_input_400(api_client, user):
    r = login(api_client, "ivan@example.com")
    auth(api_client, r.data["access"])
    assert (
        api_client.post(
            "/api/auth/switch-company/", {"company_id": 99999}, format="json"
        ).status_code
        == 403
    )
    assert api_client.post("/api/auth/switch-company/", {}, format="json").status_code == 400


# --- middleware ---


def test_middleware_resets_after_normal_response():
    def view(request):
        set_current_company(42)
        return HttpResponse("ok")

    mw = TenantContextMiddleware(view)
    mw(RequestFactory().get("/"))
    assert get_current_company_id() is None


def test_middleware_resets_after_exception():
    def view(request):
        set_current_company(42)
        raise RuntimeError("boom")

    mw = TenantContextMiddleware(view)
    with pytest.raises(RuntimeError):
        mw(RequestFactory().get("/"))
    assert get_current_company_id() is None


def test_middleware_no_leak_between_requests():
    seen = []

    def view(request):
        seen.append(get_current_company_id())
        set_current_company(7)
        return HttpResponse("ok")

    mw = TenantContextMiddleware(view)
    mw(RequestFactory().get("/"))
    mw(RequestFactory().get("/"))
    assert seen == [None, None]
