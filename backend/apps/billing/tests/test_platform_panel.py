"""T5: журнал изменений, список компаний, признак администратора платформы."""

import pytest

from apps.billing import plans, subscriptions
from apps.billing.models import BillingEvent
from apps.core.models import User

pytestmark = pytest.mark.django_db

ADMIN = "/api/platform/plans/"


def events_of(kind=None, key=None):
    qs = BillingEvent.objects.all()
    if kind:
        qs = qs.filter(kind=kind)
    if key:
        qs = qs.filter(key=key)
    return list(qs.order_by("id"))


def test_every_plan_change_is_logged_with_diff_and_actor(platform_api, admin_user):
    api = platform_api
    api.post(ADMIN, {"code": "hist", "name": "Hist", "price": "10"}, format="json")
    api.patch(
        f"{ADMIN}hist/",
        {"price": "20", "modules": ["logistics"], "limits": {"max_vehicles": 3}},
        format="json",
    )
    api.post(f"{ADMIN}hist/publish/")
    api.post(f"{ADMIN}hist/unpublish/")
    api.post(f"{ADMIN}hist/archive/")
    api.post(f"{ADMIN}hist/restore/")
    api.delete(f"{ADMIN}hist/")
    got = [(e.action, e.actor) for e in events_of("plan", "hist")]
    assert [a for a, _ in got] == [
        "create", "update", "publish", "unpublish", "archive", "restore", "delete",
    ]  # fmt: skip
    owner = User.objects.get(platform_role="owner").email
    assert all(actor == owner for _, actor in got)
    update = events_of("plan", "hist")[1]
    assert update.changes["price"] == ["10.00", "20.00"]
    assert update.changes["modules"] == [[], ["logistics"]]
    assert update.changes["limits"] == [{}, {"max_vehicles": 3}]
    assert "name" not in update.changes  # только изменившееся


def test_default_and_reorder_logged_and_noop_update_not_logged(platform_api):
    api = platform_api
    api.post(f"{ADMIN}business/publish/")
    api.post(f"{ADMIN}business/set-default/")
    api.post(f"{ADMIN}reorder/", {"codes": ["lifetime", "business"]}, format="json")
    api.patch(f"{ADMIN}business/", {"name": "Бизнес+"}, format="json")
    api.patch(f"{ADMIN}business/", {"name": "Бизнес+"}, format="json")  # без изменений
    actions = [e.action for e in events_of("plan")]
    assert "set_default" in actions and "reorder" in actions
    assert actions.count("update") == 1


def test_subscription_changes_are_logged(platform_api, company, admin_user):
    target = plans.publish(plans.create_plan(code="logged", name="L", price="5"))
    subscriptions.change_plan(company, target, period="restart", user=admin_user)
    subscriptions.renew(company, user=admin_user)
    rows = events_of("subscription", str(company.id))
    assert [e.action for e in rows] == ["change_plan", "renew"]
    assert rows[0].changes["plan"][1] == "logged" and rows[0].changes["period"] == "restart"


def test_history_api_filters_and_requires_platform_admin(platform_api, admin_client):
    api = platform_api
    api.post(ADMIN, {"code": "h1", "name": "H1"}, format="json")
    api.post(ADMIN, {"code": "h2", "name": "H2"}, format="json")
    data = api.get("/api/platform/history/", {"kind": "plan", "key": "h1"}).json()
    assert data["count"] == 1 and data["results"][0]["action"] == "create"
    assert api.get("/api/platform/history/", {"kind": "x"}).status_code == 400
    newest = api.get("/api/platform/history/").json()["results"][0]
    assert newest["key"] == "h2"  # новые сверху


def test_history_forbidden_for_regular_user(admin_client):
    assert admin_client.get("/api/platform/history/").status_code == 403
    assert admin_client.get("/api/platform/companies/").status_code == 403


def test_companies_list_search_and_status(platform_api, make_company, company):
    make_company("Альфа-Логистик")
    make_company("Бета")
    api = platform_api
    rows = api.get("/api/platform/companies/", {"q": "альфа"}).json()
    assert rows["count"] == 1 and rows["results"][0]["name"] == "Альфа-Логистик"
    row = rows["results"][0]
    assert {"id", "plan", "plan_name", "status", "is_free_period", "ends_at"} <= set(row)
    assert api.get("/api/platform/companies/").json()["count"] >= 3


def test_session_exposes_platform_role(admin_client, admin_user):
    assert admin_client.get("/api/session/").json()["user"]["platform_role"] == ""
    User.objects.filter(pk=admin_user.pk).update(platform_role="admin")
    assert admin_client.get("/api/session/").json()["user"]["platform_role"] == "admin"


def test_companies_bin_search_and_filters(platform_api, make_company, company):
    from apps.billing.models import Subscription
    from apps.core.models import Company

    c = make_company("Гамма")[0]
    Company.objects.filter(pk=c.pk).update(bin="123456789012")
    api = platform_api
    got = api.get("/api/platform/companies/", {"q": "3456"}).json()
    assert got["count"] == 1 and got["results"][0]["bin"] == "123456789012"
    assert api.get("/api/platform/companies/", {"q": "1234-5678"}).json()["count"] == 1
    plan_code = c.subscription.plan.code
    by_plan = api.get("/api/platform/companies/", {"plan": plan_code}).json()
    assert by_plan["count"] >= 1
    assert api.get("/api/platform/companies/", {"plan": "no-such"}).json()["count"] == 0
    assert api.get("/api/platform/companies/", {"state": "active"}).json()["count"] >= 1
    Subscription.objects.filter(company=c).update(status=Subscription.BLOCKED)
    off = api.get("/api/platform/companies/", {"state": "inactive"}).json()
    assert [r["name"] for r in off["results"]] == ["Гамма"]
    assert api.get("/api/platform/companies/", {"state": "zzz"}).status_code == 400


def test_history_search_by_login_or_company_id(platform_api, company):
    api = platform_api
    BillingEvent.objects.create(
        kind="subscription", key=str(company.pk), action="renew", actor="x@y.kz"
    )
    BillingEvent.objects.create(kind="plan", key="start", action="update", actor="boss@z.kz")
    by_login = api.get("/api/platform/history/", {"q": "boss"}).json()["results"]
    assert [e["key"] for e in by_login] == ["start"]
    by_id = api.get("/api/platform/history/", {"q": str(company.pk)}).json()["results"]
    assert any(e["action"] == "renew" for e in by_id)


def test_platform_dashboard_shape_and_access(platform_api, admin_client, make_company, company):
    make_company("Дельта")
    assert admin_client.get("/api/platform/dashboard/").status_code == 403
    d = platform_api.get("/api/platform/dashboard/").json()
    assert d["companies"]["total"] >= 2 and d["subscriptions"]["total"] >= 2
    assert set(d["subscriptions"]["by_status"]) == {
        "trial",
        "active",
        "grace",
        "readonly",
        "blocked",
    }
    assert sum(d["subscriptions"]["by_status"].values()) == d["subscriptions"]["total"]
    assert len(d["revenue"]["by_month"]) == 12 and d["revenue"]["currency"] == "KZT"
    assert d["revenue"]["by_month"][-1]["new"] >= 2  # компании созданы в этом месяце
    assert sum(p["subscriptions"] for p in d["plans"]) == d["subscriptions"]["total"]
    assert {"logins_7d", "changes_7d", "recent"} <= set(d["activity"])
    assert d["users"]["memberships"] >= 2
