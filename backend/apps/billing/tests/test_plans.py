"""T1: тарифы как данные - модель, правила управления, API администратора платформы."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.billing import plans
from apps.billing.models import Plan, Subscription
from apps.billing.plans import PlanError
from apps.core.models import User
from apps.core.services import create_company_with_defaults

pytestmark = pytest.mark.django_db

ADMIN = "/api/platform/plans/"


def code_of(exc):
    return exc.value.detail["code"]


def make_plan(code="p1", **extra):
    return plans.create_plan(code=code, name=extra.pop("name", code.upper()), **extra)


# --- модель и данные по умолчанию ---


def test_seeded_plans_have_order_default_and_free_price():
    start = Plan.objects.get(code="start")
    assert start.is_default and start.status == "active"
    assert [p.code for p in Plan.objects.all()][:3] == ["start", "business", "lifetime"]
    assert start.price == 0 and start.currency == "KZT"


def test_db_enforces_price_default_and_archive_rules():
    with pytest.raises(IntegrityError), transaction.atomic():
        Plan.objects.create(code="neg", name="n", billing_type="monthly", price=Decimal("-1"))
    with pytest.raises(IntegrityError), transaction.atomic():  # второй тариф по умолчанию
        Plan.objects.create(code="d2", name="d", billing_type="monthly", is_default=True)
    with pytest.raises(IntegrityError), transaction.atomic():  # архивный не может быть активным
        Plan.objects.create(
            code="arch", name="a", billing_type="monthly", is_active=True,
            archived_at=timezone.now(),
        )  # fmt: skip


# --- создание и правка ---


def test_create_is_draft_goes_to_end_and_validates():
    last = Plan.objects.order_by("-sort_order").first().sort_order
    plan = make_plan("Free_1", description="  Для малых компаний  ", price="0", currency="usd")
    assert plan.code == "free_1" and plan.status == "draft" and plan.currency == "USD"
    assert plan.sort_order == last + 10 and plan.description == "Для малых компаний"
    for bad in (
        {"code": "Не код"},
        {"code": "ok", "name": "  "},
        {"code": "ok2", "name": "x", "price": "-5"},
        {"code": "ok3", "name": "x", "price": "1.234"},
        {"code": "ok4", "name": "x", "currency": "тенге"},
        {"code": "ok5", "name": "x", "billing_type": "weekly"},
        {"code": "ok6", "name": "x", "limits": {"a": 1}},  # лимиты - этап T3, не здесь
    ):
        with pytest.raises(PlanError) as e:
            plans.create_plan(**bad)
        assert e.value.status_code == 400, bad
    with pytest.raises(PlanError) as e:
        make_plan("free_1")
    assert code_of(e) == "plan_code_taken"


def test_update_changes_content_but_not_code_or_existing_subscriptions(make_company):
    company, _, _ = make_company("Sub")
    plan = company.subscription.plan
    before = (company.subscription.plan_id, company.subscription.ends_at)
    updated = plans.update_plan(plan, name="Новое имя", price="1500.50", currency="KZT")
    assert updated.price == Decimal("1500.50") and updated.name == "Новое имя"
    company.subscription.refresh_from_db()
    assert (company.subscription.plan_id, company.subscription.ends_at) == before
    with pytest.raises(PlanError):
        plans.update_plan(plan, code="other")
    with pytest.raises(PlanError):
        plans.update_plan(plan, is_default=False)


# --- публикация, архив, по умолчанию, удаление ---


def test_publish_unpublish_archive_restore_flow():
    plan = make_plan("flow")
    assert plans.publish(plan).status == "active"
    assert plans.unpublish(plan).status == "draft"
    plans.publish(plan)
    assert plans.archive(plan).status == "archived"
    with pytest.raises(PlanError) as e:
        plans.publish(plan)
    assert code_of(e) == "plan_archived"
    assert plans.restore(plan).status == "draft"


def test_default_plan_rules_and_switch():
    start = Plan.objects.get(code="start")
    other = plans.publish(make_plan("other"))
    for action in (plans.archive, plans.unpublish, plans.delete_plan):
        with pytest.raises(PlanError) as e:
            action(start)
        assert code_of(e) == "plan_is_default"
    draft = make_plan("draft")
    with pytest.raises(PlanError) as e:
        plans.set_default(draft)
    assert code_of(e) == "plan_not_published"
    plans.set_default(other)
    assert list(Plan.objects.filter(is_default=True)) == [other]
    plans.archive(start)  # теперь можно


def test_archived_plan_keeps_working_subscriptions_and_delete_is_refused(make_company):
    company, _, _ = make_company("Keep")
    plan = company.subscription.plan
    plans.set_default(plans.publish(make_plan("next")))
    plans.archive(plan)
    company.subscription.refresh_from_db()
    assert company.subscription.plan_id == plan.pk  # подписка не тронута
    with pytest.raises(PlanError) as e:
        plans.delete_plan(plan)
    assert code_of(e) == "plan_has_subscriptions"
    unused = make_plan("unused")
    plans.delete_plan(unused)
    assert not Plan.objects.filter(code="unused").exists()


def test_reorder_is_data_and_unlisted_go_after():
    a, b, c = (make_plan(code) for code in ("a1", "b1", "c1"))
    ordered = plans.reorder(["c1", "a1"])
    assert [p.code for p in ordered][:2] == ["c1", "a1"]
    codes = list(Plan.objects.values_list("code", flat=True))
    assert codes.index("c1") < codes.index("a1") < codes.index("start")
    with pytest.raises(PlanError):
        plans.reorder(["a1", "a1"])
    with pytest.raises(PlanError):
        plans.reorder(["нет"])
    assert b.pk and c.pk and a.pk


# --- новые компании получают тариф по умолчанию (данные, не код) ---


def test_new_company_gets_default_plan_not_a_hardcoded_code(admin_user):
    free = plans.publish(make_plan("free"))
    Plan.objects.filter(pk=free.pk).update(modules=["logistics", "finance", "documents"])
    plans.set_default(free)
    user = User.objects.create_user(email="owner@t1.kz", password="x")
    company = create_company_with_defaults("T1", user, ["logistics"])
    assert company.subscription.plan.code == "free"
    assert company.subscription.ends_at > timezone.now() + timedelta(days=300)


def test_no_default_plan_blocks_company_creation(admin_user):
    Plan.objects.update(is_default=False)
    user = User.objects.create_user(email="owner2@t1.kz", password="x")
    with pytest.raises(PlanError) as e:
        create_company_with_defaults("T2", user, ["logistics"])
    assert code_of(e) == "no_default_plan"


# --- публичный список ---


def test_public_list_hides_drafts_and_archived_and_follows_order(admin_client):
    plans.publish(make_plan("shown", price="990", description="Описание"))
    make_plan("hidden-draft")
    plans.archive(plans.publish(make_plan("hidden-archived")))
    Plan.objects.filter(code="shown").update(sort_order=1)
    data = admin_client.get("/api/billing/plans/").json()
    codes = [p["code"] for p in data]
    assert codes[0] == "shown" and "hidden-draft" not in codes and "hidden-archived" not in codes
    first = data[0]
    assert first["price"] == "990.00" and first["currency"] == "KZT"
    assert first["description"] == "Описание"


# --- API администратора платформы ---


@pytest.fixture
def platform_api(admin_client, admin_user):
    User.objects.filter(pk=admin_user.pk).update(is_platform_admin=True)
    return admin_client


def test_admin_api_requires_platform_admin(admin_client):
    for method, url in (("get", ADMIN), ("post", ADMIN), ("get", f"{ADMIN}start/")):
        assert getattr(admin_client, method)(url).status_code == 403, url


def test_admin_api_full_cycle(platform_api):
    api = platform_api
    listing = api.get(ADMIN).json()
    assert [p["code"] for p in listing][:3] == ["start", "business", "lifetime"]
    assert listing[0]["is_default"] and listing[0]["subscriptions_count"] >= 1
    r = api.post(ADMIN, {"code": "gold", "name": "Золото", "price": "5000", "currency": "usd"})
    assert r.status_code == 201, r.content
    assert r.json()["status"] == "draft" and r.json()["currency"] == "USD"
    assert api.post(ADMIN, {"code": "gold", "name": "Ещё"}).status_code == 409
    assert api.post(ADMIN, {"code": "x y", "name": "x"}).status_code == 400
    assert (
        api.patch(f"{ADMIN}gold/", {"price": "6000", "name": "Золото 2"}, format="json").json()[
            "price"
        ]
        == "6000.00"
    )
    assert api.patch(f"{ADMIN}gold/", {"code": "z"}, format="json").status_code == 400
    assert api.post(f"{ADMIN}gold/publish/").json()["status"] == "active"
    assert api.post(f"{ADMIN}gold/set-default/").json()["is_default"] is True
    assert api.post(f"{ADMIN}gold/archive/").status_code == 409  # тариф по умолчанию
    assert api.post(f"{ADMIN}start/set-default/").status_code == 200
    assert api.post(f"{ADMIN}gold/archive/").json()["status"] == "archived"
    assert api.post(f"{ADMIN}gold/restore/").json()["status"] == "draft"
    assert api.delete(f"{ADMIN}gold/").status_code == 204
    assert api.delete(f"{ADMIN}start/").status_code == 409
    order = api.post(f"{ADMIN}reorder/", {"codes": ["lifetime", "business"]}, format="json")
    assert [p["code"] for p in order.json()][:2] == ["lifetime", "business"]
    assert api.post(f"{ADMIN}reorder/", {"codes": "x"}, format="json").status_code == 400
    assert api.get(f"{ADMIN}nope/").status_code == 404


def test_admin_api_works_even_if_own_subscription_is_blocked(platform_api, company):
    Subscription.objects.filter(company=company).update(status=Subscription.BLOCKED)
    assert platform_api.get(ADMIN).status_code == 200  # управление тарифами не зависит от подписки
