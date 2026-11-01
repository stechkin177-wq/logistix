from datetime import UTC, datetime, timedelta
from decimal import Decimal  # noqa: F401  (цены в коде не хранятся)

import pytest
import time_machine
from rest_framework.exceptions import APIException

from apps.billing.models import Plan, Subscription
from apps.billing.permissions import ModuleRequired, SubscriptionGate
from apps.billing.services import LimitExceeded, check_limit, effective_status
from apps.core.api.auth import issue_tokens
from apps.core.models import Company, Membership, Role, User
from apps.core.services import create_company_with_defaults
from apps.core.tenancy import set_current_company

pytestmark = [pytest.mark.django_db, pytest.mark.urls("apps.billing.tests.urls")]

PASSWORD = "s3cret-pass"
T = datetime(2027, 3, 1, 12, 0, 0, tzinfo=UTC)
D = timedelta(days=1)
S = timedelta(seconds=1)


@pytest.fixture(autouse=True)
def _reset_tenant():
    set_current_company(None)
    yield
    set_current_company(None)


def make_user(email, **kw):
    return User.objects.create_user(email=email, password=PASSWORD, **kw)


def client_for(api_client, user, company):
    tokens = issue_tokens(user, company.id)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return api_client


def set_sub(company, **fields):
    Subscription.objects.filter(company=company).update(**fields)


@pytest.fixture
def owner_a():
    return make_user("owner-a@x.kz")


@pytest.fixture
def owner_b():
    return make_user("owner-b@x.kz")


@pytest.fixture
def company_a(owner_a):
    return create_company_with_defaults("A", owner_a, ["forwarding"])


@pytest.fixture
def company_b(owner_b):
    return create_company_with_defaults("B", owner_b, ["forwarding", "fleet"])


@pytest.fixture
def client_a(api_client, owner_a, company_a):
    return client_for(api_client, owner_a, company_a)


def sub_obj(billing_type="monthly", status="active", ends_at=T):
    plan = Plan(code="x", name="x", billing_type=billing_type)
    return Subscription(plan=plan, status=status, starts_at=T - 30 * D, ends_at=ends_at)


# --- effective_status ---


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (T - S, "active"),
        (T, "active"),
        (T + S, "grace"),
        (T + 10 * D, "grace"),
        (T + 14 * D, "grace"),
        (T + 14 * D + S, "readonly"),
        (T + 30 * D, "readonly"),
        (T + 44 * D, "readonly"),
        (T + 44 * D + S, "blocked"),
        (T + 60 * D, "blocked"),
    ],
)
def test_effective_status_boundaries(now, expected):
    assert effective_status(sub_obj(), now) == expected


def test_effective_status_trial_before_end_then_grace():
    sub = sub_obj(status="trial")
    assert effective_status(sub, T) == "trial"
    assert effective_status(sub, T + S) == "grace"


def test_effective_status_stored_grace_or_readonly_future_end_is_active():
    assert effective_status(sub_obj(status="grace"), T - D) == "active"
    assert effective_status(sub_obj(status="readonly"), T - D) == "active"


def test_effective_status_stored_blocked_always_wins():
    assert effective_status(sub_obj(status="blocked"), T - 100 * D) == "blocked"
    assert effective_status(sub_obj(status="blocked", billing_type="lifetime"), T) == "blocked"
    assert effective_status(sub_obj(status="blocked", ends_at=None), T) == "blocked"


def test_effective_status_lifetime_and_no_end_always_active():
    far = T + 5000 * D
    assert effective_status(sub_obj(billing_type="lifetime"), far) == "active"
    assert effective_status(sub_obj(billing_type="lifetime", ends_at=T - D), far) == "active"
    assert effective_status(sub_obj(ends_at=None), far) == "active"
    assert effective_status(sub_obj(ends_at=None, status="trial"), far) == "trial"


# --- планы и подписка при создании компании ---


def test_default_plans_seeded():
    plans = {p.code: p for p in Plan.objects.all()}
    assert set(plans) == {"start", "business", "lifetime"}
    assert [plans[c].billing_type for c in ("start", "business", "lifetime")] == [
        "monthly",
        "yearly",
        "lifetime",
    ]
    assert plans["start"].limits == {
        "max_users": 5,
        "max_vehicles": 5,
        "max_orders_per_month": 200,
        "max_ocr_per_month": 50,
    }
    assert plans["business"].limits["max_users"] == 50
    assert plans["lifetime"].limits == {
        "max_users": None,
        "max_vehicles": None,
        "max_orders_per_month": None,
        "max_ocr_per_month": None,
    }
    for plan in plans.values():
        assert plan.modules == ["forwarding", "fleet"]
        assert plan.is_active
    assert plans["start"].options == {"white_label": False, "custom_domain": False}
    assert plans["business"].options == {"white_label": True, "custom_domain": True}
    assert plans["lifetime"].options == {"white_label": True, "custom_domain": True}


def test_create_company_creates_free_year_subscription(owner_a):
    with time_machine.travel(T, tick=False):
        company = create_company_with_defaults("New", owner_a, ["forwarding"])
    sub = Subscription.objects.get(company=company)
    assert sub.plan.code == "start"
    assert sub.status == "active"
    assert sub.is_free_period is True
    assert sub.starts_at == T
    assert sub.ends_at == T + timedelta(days=365)


def test_create_company_subscription_is_in_same_transaction(owner_a):
    Plan.objects.filter(code="start").delete()
    before = Company.objects.count()
    with pytest.raises(Plan.DoesNotExist):
        create_company_with_defaults("New", owner_a, ["forwarding"])
    assert Company.objects.count() == before
    assert not Membership.objects.filter(user=owner_a).exists()
    assert not Role.all_objects.filter(company__name="New").exists()


# --- SubscriptionGate ---


def test_active_company_passes(client_a):
    assert client_a.get("/api/roles/").status_code == 200
    assert client_a.get("/api/auth/me/").status_code == 200


def test_grace_allows_writes(client_a, company_a):
    set_sub(company_a, ends_at=datetime.now(UTC) - 5 * D)
    r = client_a.post("/api/roles/", {"name": "R1", "permissions": []}, format="json")
    assert r.status_code == 201


def test_readonly_blocks_writes_allows_reads(client_a, company_a):
    set_sub(company_a, ends_at=datetime.now(UTC) - 20 * D)
    assert client_a.get("/api/roles/").status_code == 200
    r = client_a.post("/api/roles/", {"name": "R1", "permissions": []}, format="json")
    assert r.status_code == 403
    assert r.json()["code"] == "subscription_readonly"
    assert r.json()["detail"]
    assert client_a.patch("/api/users/1/", {}, format="json").json()["code"] == (
        "subscription_readonly"
    )


def test_readonly_checked_before_role_permission(api_client, company_a):
    viewer = make_user("viewer@x.kz")
    Membership.objects.create(
        user=viewer,
        company=company_a,
        role=Role.all_objects.get(company=company_a, name="Наблюдатель"),
    )
    set_sub(company_a, ends_at=datetime.now(UTC) - 20 * D)
    client_for(api_client, viewer, company_a)
    r = api_client.post("/api/roles/", {"name": "R1", "permissions": []}, format="json")
    assert r.status_code == 403
    assert r.json()["code"] == "subscription_readonly"


def test_readonly_boundary_with_time_machine(api_client, owner_a, company_a):
    ends = T + 365 * D
    set_sub(company_a, ends_at=ends)
    last_grace = ends + 14 * D
    with time_machine.travel(last_grace, tick=False):
        client = client_for(api_client, owner_a, company_a)
        assert (
            client.post("/api/roles/", {"name": "R1", "permissions": []}, format="json").status_code
            == 201
        )
    with time_machine.travel(last_grace + S, tick=False):
        client = client_for(api_client, owner_a, company_a)
        r = client.post("/api/roles/", {"name": "R2", "permissions": []}, format="json")
        assert r.status_code == 403
        assert r.json()["code"] == "subscription_readonly"
        assert client.get("/api/roles/").status_code == 200
    with time_machine.travel(ends + 44 * D, tick=False):
        client = client_for(api_client, owner_a, company_a)
        assert client.get("/api/roles/").status_code == 200
    with time_machine.travel(ends + 44 * D + S, tick=False):
        client = client_for(api_client, owner_a, company_a)
        r = client.get("/api/roles/")
        assert r.status_code == 403
        assert r.json()["code"] == "subscription_blocked"


def test_blocked_denies_everything_including_reads(client_a, company_a):
    set_sub(company_a, status="blocked")
    for url in ("/api/roles/", "/api/users/", "/api/auth/me/", "/api/billing/subscription/"):
        r = client_a.get(url)
        assert r.status_code == 403, url
        assert r.json()["code"] == "subscription_blocked", url
    assert client_a.post("/api/roles/", {}, format="json").json()["code"] == "subscription_blocked"


def test_existing_token_stops_working_immediately(client_a, company_a):
    assert client_a.get("/api/roles/").status_code == 200
    set_sub(company_a, status="blocked")
    r = client_a.get("/api/roles/")
    assert r.status_code == 403
    assert r.json()["code"] == "subscription_blocked"
    set_sub(company_a, status="active")
    assert client_a.get("/api/roles/").status_code == 200


def test_no_subscription_is_blocked(client_a, company_a):
    Subscription.objects.filter(company=company_a).delete()
    r = client_a.get("/api/roles/")
    assert r.status_code == 403
    assert r.json()["code"] == "subscription_blocked"


def test_platform_admin_is_not_exempt(api_client):
    admin = make_user("pa@x.kz", is_platform_admin=True)
    company = create_company_with_defaults("PA", admin, ["forwarding"])
    set_sub(company, status="blocked")
    client = client_for(api_client, admin, company)
    r = client.get("/api/roles/")
    assert r.status_code == 403
    assert r.json()["code"] == "subscription_blocked"
    set_sub(company, ends_at=datetime.now(UTC) - 20 * D, status="active")
    assert client.post("/api/roles/", {}, format="json").json()["code"] == "subscription_readonly"


def test_gate_is_default_permission_class():
    from django.conf import settings

    assert (
        "apps.billing.permissions.SubscriptionGate"
        in (settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"])
    )
    assert SubscriptionGate


def test_public_endpoints_unaffected(api_client, company_a, owner_a):
    set_sub(company_a, status="blocked")
    assert api_client.get("/api/health/").status_code == 200
    refresh = issue_tokens(owner_a, company_a.id)["refresh"]
    assert (
        api_client.post("/api/auth/refresh/", {"refresh": refresh}, format="json").status_code
        == 200
    )


# --- вход и переключение компании ---


def test_login_refused_when_only_company_blocked(api_client, owner_a, company_a):
    set_sub(company_a, status="blocked")
    r = api_client.post(
        "/api/auth/login/", {"login": "owner-a@x.kz", "password": PASSWORD}, format="json"
    )
    assert r.status_code == 403
    assert r.json()["code"] == "subscription_blocked"


def test_login_refused_when_expired_beyond_readonly(api_client, owner_a, company_a):
    set_sub(company_a, ends_at=datetime.now(UTC) - 45 * D)
    r = api_client.post(
        "/api/auth/login/", {"login": "owner-a@x.kz", "password": PASSWORD}, format="json"
    )
    assert r.status_code == 403
    assert r.json()["code"] == "subscription_blocked"


def test_login_picks_first_non_blocked_company(api_client, owner_a, company_a):
    other = create_company_with_defaults("Other", make_user("o2@x.kz"), ["forwarding"])
    Membership.objects.create(
        user=owner_a, company=other, role=Role.all_objects.get(company=other, name="Наблюдатель")
    )
    set_sub(company_a, status="blocked")
    r = api_client.post(
        "/api/auth/login/", {"login": "owner-a@x.kz", "password": PASSWORD}, format="json"
    )
    assert r.status_code == 200
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.json()['access']}")
    assert api_client.get("/api/auth/me/").json()["company_id"] == other.id


def test_login_readonly_company_allowed(api_client, owner_a, company_a):
    set_sub(company_a, ends_at=datetime.now(UTC) - 20 * D)
    r = api_client.post(
        "/api/auth/login/", {"login": "owner-a@x.kz", "password": PASSWORD}, format="json"
    )
    assert r.status_code == 200


def test_switch_into_blocked_company_refused(api_client, owner_a, company_a):
    other = create_company_with_defaults("Other", make_user("o2@x.kz"), ["forwarding"])
    Membership.objects.create(
        user=owner_a, company=other, role=Role.all_objects.get(company=other, name="Наблюдатель")
    )
    set_sub(other, status="blocked")
    client = client_for(api_client, owner_a, company_a)
    r = client.post("/api/auth/switch-company/", {"company_id": other.id}, format="json")
    assert r.status_code == 403
    assert r.json()["code"] == "subscription_blocked"


def test_can_switch_out_of_blocked_or_readonly_company(api_client, owner_a, company_a):
    other = create_company_with_defaults("Other", make_user("o2@x.kz"), ["forwarding"])
    Membership.objects.create(
        user=owner_a, company=other, role=Role.all_objects.get(company=other, name="Наблюдатель")
    )
    client = client_for(api_client, owner_a, company_a)
    for fields in ({"status": "blocked"}, {"ends_at": datetime.now(UTC) - 20 * D}):
        set_sub(company_a, status="active", ends_at=datetime.now(UTC) + 30 * D)
        set_sub(company_a, **fields)
        r = client.post("/api/auth/switch-company/", {"company_id": other.id}, format="json")
        assert r.status_code == 200, fields


# --- модули ---


def test_module_required_denies_forwarding_only_company(client_a):
    r = client_a.get("/api/_probe/fleet/")
    assert r.status_code == 403
    assert r.json()["code"] == "module_disabled"


def test_module_required_allows_company_with_module(api_client, owner_b, company_b):
    client = client_for(api_client, owner_b, company_b)
    assert client.get("/api/_probe/fleet/").status_code == 200


def test_module_required_denies_when_plan_lacks_module(api_client, owner_b, company_b):
    Plan.objects.filter(code="start").update(modules=["forwarding"])
    client = client_for(api_client, owner_b, company_b)
    r = client.get("/api/_probe/fleet/")
    assert r.status_code == 403
    assert r.json()["code"] == "module_disabled"


def test_module_required_still_gated_by_subscription(api_client, owner_b, company_b):
    set_sub(company_b, ends_at=datetime.now(UTC) - 20 * D)
    client = client_for(api_client, owner_b, company_b)
    assert client.get("/api/_probe/fleet/").status_code == 200
    assert client.post("/api/_probe/fleet/").json()["code"] == "subscription_readonly"
    set_sub(company_b, status="blocked")
    assert client.get("/api/_probe/fleet/").json()["code"] == "subscription_blocked"


def test_module_required_unknown_module_is_error():
    with pytest.raises(ValueError):
        ModuleRequired("bogus")


# --- лимиты ---


def test_check_limit_boundary(company_a):
    check_limit(company_a, "max_users", 4)
    with pytest.raises(LimitExceeded) as exc:
        check_limit(company_a, "max_users", 5)
    assert exc.value.status_code == 402
    assert exc.value.get_codes() == "limit_exceeded"
    assert isinstance(exc.value, APIException)
    with pytest.raises(LimitExceeded):
        check_limit(company_a, "max_users", 6)


def test_check_limit_null_is_unlimited(company_a):
    set_sub(company_a, plan=Plan.objects.get(code="lifetime"))
    check_limit(company_a, "max_users", 10**9)


def test_check_limit_unknown_key(company_a):
    with pytest.raises(ValueError):
        check_limit(company_a, "max_dragons", 0)


def test_check_limit_without_subscription_raises(company_a):
    Subscription.objects.filter(company=company_a).delete()
    with pytest.raises(LimitExceeded):
        check_limit(company_a, "max_users", 0)


def test_check_limit_uses_own_company_plan(company_a, company_b):
    set_sub(company_b, plan=Plan.objects.get(code="lifetime"))
    check_limit(company_b, "max_users", 1000)
    with pytest.raises(LimitExceeded):
        check_limit(company_a, "max_users", 5)


def add_user_via_api(client, n):
    role = client.get("/api/roles/").json()
    role_id = next(r["id"] for r in role if r["name"] == "Наблюдатель")
    return client.post(
        "/api/users/",
        {"login": f"u{n}@x.kz", "password": PASSWORD, "role": role_id},
        format="json",
    )


def test_sixth_user_on_start_refused_with_402(client_a):
    for n in range(4):  # владелец + 4 = 5
        assert add_user_via_api(client_a, n).status_code == 201
    r = add_user_via_api(client_a, 99)
    assert r.status_code == 402
    assert r.json()["code"] == "limit_exceeded"
    assert not User.objects.filter(email="u99@x.kz").exists()


def test_deactivated_members_do_not_count(client_a, company_a):
    ids = []
    for n in range(4):
        ids.append(add_user_via_api(client_a, n).json()["id"])
    assert add_user_via_api(client_a, 50).status_code == 402
    r = client_a.patch(f"/api/users/{ids[0]}/", {"is_active": False}, format="json")
    assert r.status_code == 200
    assert add_user_via_api(client_a, 51).status_code == 201
    # реактивация поверх лимита тоже отказ
    r = client_a.patch(f"/api/users/{ids[0]}/", {"is_active": True}, format="json")
    assert r.status_code == 402
    assert r.json()["code"] == "limit_exceeded"


def test_user_limit_isolated_between_companies(client_a, api_client, owner_b, company_b):
    for n in range(4):
        add_user_via_api(client_a, n)
    assert add_user_via_api(client_a, 77).status_code == 402
    client_b = client_for(type(api_client)(), owner_b, company_b)
    assert add_user_via_api(client_b, 1).status_code == 201


# --- API ---


def test_subscription_endpoint(client_a, company_a):
    with time_machine.travel(datetime.now(UTC), tick=False):
        r = client_a.get("/api/billing/subscription/")
    assert r.status_code == 200
    data = r.json()
    assert data["plan"]["code"] == "start"
    assert set(data["plan"]) == {"code", "name", "billing_type", "limits", "modules", "options"}
    assert data["plan"]["limits"]["max_users"] == 5
    assert data["status"] == "active"
    assert data["is_free_period"] is True
    assert data["days_left"] == 365
    assert data["starts_at"] and data["ends_at"]


def test_subscription_endpoint_reachable_in_grace_and_readonly_not_blocked(client_a, company_a):
    set_sub(company_a, ends_at=datetime.now(UTC) - 20 * D)
    r = client_a.get("/api/billing/subscription/")
    assert r.status_code == 200
    assert r.json()["status"] == "readonly"
    assert r.json()["days_left"] == 0
    set_sub(company_a, status="blocked")
    assert client_a.get("/api/billing/subscription/").status_code == 403


def test_subscription_endpoint_lifetime_days_left_null(client_a, company_a):
    set_sub(company_a, plan=Plan.objects.get(code="lifetime"), ends_at=None)
    r = client_a.get("/api/billing/subscription/")
    assert r.json()["days_left"] is None
    assert r.json()["status"] == "active"


def test_subscription_endpoint_company_isolation(
    api_client, owner_a, company_a, owner_b, company_b
):
    set_sub(company_b, plan=Plan.objects.get(code="business"))
    set_sub(company_a, ends_at=datetime.now(UTC) - 20 * D)
    a = client_for(type(api_client)(), owner_a, company_a).get("/api/billing/subscription/").json()
    b = client_for(type(api_client)(), owner_b, company_b).get("/api/billing/subscription/").json()
    assert a["plan"]["code"] == "start"
    assert a["status"] == "readonly"
    assert b["plan"]["code"] == "business"
    assert b["status"] == "active"


def test_plans_endpoint_lists_active_without_prices(client_a):
    Plan.objects.filter(code="business").update(is_active=False)
    r = client_a.get("/api/billing/plans/")
    assert r.status_code == 200
    data = r.json()
    assert [p["code"] for p in data] == ["start", "lifetime"]
    for p in data:
        assert set(p) == {"code", "name", "billing_type", "limits", "modules", "options"}


def test_billing_requires_auth(api_client):
    assert api_client.get("/api/billing/subscription/").status_code == 401
    assert api_client.get("/api/billing/plans/").status_code == 401


def test_gate_fails_closed_for_authenticated_user_without_membership(api_client):
    make_user("nomember@x.kz")
    r = api_client.get("/api/_probe/nomembership/")
    assert r.status_code == 403 and r.json()["code"] == "subscription_blocked"


def test_gate_still_ignores_anonymous_requests(api_client):
    assert api_client.get("/api/health/").status_code == 200
    assert api_client.get("/api/_probe/nomembership/").status_code in (401, 403)
