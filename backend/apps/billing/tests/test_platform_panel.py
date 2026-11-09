"""T5: журнал изменений, список компаний, признак администратора платформы."""

import pytest

from apps.billing import plans, subscriptions
from apps.billing.models import BillingEvent
from apps.core.models import User

pytestmark = pytest.mark.django_db

ADMIN = "/api/platform/plans/"


@pytest.fixture
def platform_api(admin_client, admin_user):
    User.objects.filter(pk=admin_user.pk).update(is_platform_admin=True)
    return admin_client


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
    assert all(actor == admin_user.email for _, actor in got)
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


def test_session_exposes_platform_admin_flag(admin_client, admin_user):
    assert admin_client.get("/api/session/").json()["user"]["is_platform_admin"] is False
    User.objects.filter(pk=admin_user.pk).update(is_platform_admin=True)
    assert admin_client.get("/api/session/").json()["user"]["is_platform_admin"] is True
