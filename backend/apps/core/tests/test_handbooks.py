from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.models import Subscription
from apps.core.api.auth import issue_tokens
from apps.core.handbooks.defaults import DEFAULTS
from apps.core.handbooks.models import Handbook, HandbookValue
from apps.core.handbooks.services import seed_handbooks
from apps.core.models import Membership, Role, User
from apps.core.tenancy import tenant_context
from apps.core.tests.models import HandbookUsage

pytestmark = pytest.mark.django_db

CODES = [
    "order_status",
    "consignment_status",
    "trip_status",
    "currency",
    "client_type",
    "carrier_type",
    "packaging",
    "loading_method",
    "country",
    "payment_delay_condition",
    "transport_condition",
]
STATUS_CODES = ["order_status", "consignment_status", "trip_status"]


def values_of(company, code):
    with tenant_context(company.id):
        return list(Handbook.objects.get(code=code).values.order_by("order"))


def value_id(company, code, name):
    with tenant_context(company.id):
        return HandbookValue.objects.get(handbook__code=code, name=name).id


# --- наборы по умолчанию ---


def test_defaults_has_exactly_the_required_codes():
    assert sorted(DEFAULTS) == sorted(CODES)
    for spec in DEFAULTS.values():
        assert spec["name"] and spec["group"] and spec["values"]


def test_order_status_seeded_in_order(company):
    vals = values_of(company, "order_status")
    assert [v.name for v in vals] == [
        "Новый",
        "В работе",
        "На погрузке",
        "В пути",
        "На выгрузке",
        "Завершён",
        "Отменён",
    ]
    assert [v.order for v in vals] == [1, 2, 3, 4, 5, 6, 7]
    assert [v.name for v in vals if v.is_initial] == ["Новый"]
    assert [v.name for v in vals if v.is_final] == ["Завершён", "Отменён"]


@pytest.mark.parametrize("code", STATUS_CODES)
def test_status_handbooks_have_exactly_one_initial(company, code):
    assert sum(v.is_initial for v in values_of(company, code)) == 1


def test_other_seeded_contents(company):
    assert [v.name for v in values_of(company, "consignment_status")] == [
        "Принят",
        "На складе",
        "В пути",
        "Доставлен",
        "Выдан",
    ]
    assert [v.name for v in values_of(company, "trip_status")] == [
        "Планируется",
        "Ожидает выезда",
        "В пути",
        "Выгрузка",
        "Завершён",
        "Отменён",
    ]
    assert [(v.name, v.code) for v in values_of(company, "currency")] == [
        ("Тенге", "KZT"),
        ("Российский рубль", "RUB"),
        ("Доллар США", "USD"),
        ("Евро", "EUR"),
    ]
    countries = {v.code: v.name for v in values_of(company, "country")}
    assert len(countries) == 20
    assert countries["KZ"] == "Казахстан" and countries["UA"] == "Украина"
    assert [v.name for v in values_of(company, "transport_condition")] == ["FCA", "DAP", "CPT"]
    for code in ("client_type", "carrier_type"):
        assert [v.name for v in values_of(company, code)] == [
            "Юридическое лицо",
            "ИП",
            "Физическое лицо",
        ]


def test_seed_is_idempotent(company):
    with tenant_context(company.id):
        before = (Handbook.objects.count(), HandbookValue.objects.count())
    seed_handbooks(company)
    seed_handbooks(company)
    with tenant_context(company.id):
        assert (Handbook.objects.count(), HandbookValue.objects.count()) == before
    assert before[0] == 11


def test_seed_leaves_no_tenant_context(company):
    from apps.core.tenancy import get_current_company_id

    seed_handbooks(company)
    assert get_current_company_id() is None


def test_companies_get_independent_copies(make_company):
    a, _, client_a = make_company("A")
    b, _, _ = make_company("B")
    vid = value_id(a, "packaging", "Паллета")
    assert (
        client_a.patch(
            f"/api/handbook-values/{vid}/", {"name": "Поддон"}, format="json"
        ).status_code
        == 200
    )
    assert "Паллета" in [v.name for v in values_of(b, "packaging")]
    assert "Поддон" in [v.name for v in values_of(a, "packaging")]


def test_unique_code_per_handbook(company):
    with tenant_context(company.id):
        hb = Handbook.objects.get(code="currency")
        with pytest.raises(IntegrityError), transaction.atomic():
            HandbookValue.objects.create(handbook=hb, name="Другой тенге", code="KZT", order=9)
        # пустые коды не конфликтуют
        HandbookValue.objects.create(handbook=hb, name="x", order=9)
        HandbookValue.objects.create(handbook=hb, name="y", order=10)


# --- чтение ---


def test_list_handbooks(admin_client):
    r = admin_client.get("/api/handbooks/")
    assert r.status_code == 200
    rows = {h["code"]: h for h in r.json()}
    assert sorted(rows) == sorted(CODES)
    assert rows["order_status"]["values_count"] == 7
    assert rows["currency"]["name"] and rows["currency"]["group"]
    assert set(rows["country"]) == {"code", "name", "group", "values_count"}


def test_get_by_code_query_and_path(admin_client):
    r = admin_client.get("/api/handbooks/?code=order_status")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == "order_status"
    assert [v["name"] for v in body["values"]][:2] == ["Новый", "В работе"]
    assert [v["order"] for v in body["values"]] == [1, 2, 3, 4, 5, 6, 7]
    assert admin_client.get("/api/handbooks/order_status/").json() == body
    assert admin_client.get("/api/handbooks/?code=nope").status_code == 404
    assert admin_client.get("/api/handbooks/nope/").status_code == 404


def test_handbooks_cannot_be_created_or_changed_via_api(admin_client):
    assert (
        admin_client.post("/api/handbooks/", {"code": "x", "name": "x"}, format="json").status_code
        == 405
    )
    assert admin_client.delete("/api/handbooks/order_status/").status_code == 405
    assert (
        admin_client.patch("/api/handbooks/order_status/", {"name": "x"}, format="json").status_code
        == 405
    )


def test_values_list_filters(admin_client):
    r = admin_client.get("/api/handbook-values/?handbook=currency")
    assert [v["code"] for v in r.json()] == ["KZT", "RUB", "USD", "EUR"]
    assert r.json()[0]["handbook"] == "currency"
    vid = r.json()[1]["id"]
    admin_client.patch(f"/api/handbook-values/{vid}/", {"is_active": False}, format="json")
    r = admin_client.get("/api/handbook-values/?handbook=currency&is_active=true")
    assert [v["code"] for v in r.json()] == ["KZT", "USD", "EUR"]
    r = admin_client.get("/api/handbook-values/?handbook=currency&is_active=false")
    assert [v["code"] for v in r.json()] == ["RUB"]


# --- изоляция ---


def test_isolation_list_and_detail(make_company):
    a, _, client_a = make_company("A")
    b, _, client_b = make_company("B")
    a_ids = {v["id"] for v in client_a.get("/api/handbook-values/").json()}
    b_ids = {v["id"] for v in client_b.get("/api/handbook-values/").json()}
    assert a_ids and b_ids and not a_ids & b_ids
    some_a = next(iter(a_ids))
    assert client_b.get(f"/api/handbook-values/{some_a}/").status_code == 404
    assert (
        client_b.patch(f"/api/handbook-values/{some_a}/", {"name": "x"}, format="json").status_code
        == 404
    )
    assert client_b.delete(f"/api/handbook-values/{some_a}/").status_code == 404


def test_value_handbook_must_belong_to_company(make_company):
    a, _, client_a = make_company("A")
    with tenant_context(a.id):
        Handbook.objects.filter(code="packaging").update(code="packaging_a_only")
    _, _, client_b = make_company("B")
    r = client_b.post(
        "/api/handbook-values/", {"handbook": "packaging_a_only", "name": "x"}, format="json"
    )
    assert r.status_code == 400
    r = client_b.post("/api/handbook-values/", {"handbook": "nope", "name": "x"}, format="json")
    assert r.status_code == 400


# --- CRUD значений ---


def test_create_value_appends_order(admin_client):
    r = admin_client.post(
        "/api/handbook-values/", {"handbook": "packaging", "name": "Контейнер"}, format="json"
    )
    assert r.status_code == 201
    assert r.json()["order"] == 6 and r.json()["is_active"] is True
    assert r.json()["handbook"] == "packaging"


def test_create_value_duplicate_code_is_400(admin_client):
    r = admin_client.post(
        "/api/handbook-values/",
        {"handbook": "currency", "name": "Ещё тенге", "code": "KZT"},
        format="json",
    )
    assert r.status_code == 400


def test_update_cannot_move_value_to_other_handbook(admin_client, company):
    vid = value_id(company, "packaging", "Паллета")
    r = admin_client.patch(f"/api/handbook-values/{vid}/", {"handbook": "currency"}, format="json")
    assert r.status_code == 400


def test_update_name_and_order(admin_client, company):
    vid = value_id(company, "packaging", "Паллета")
    r = admin_client.patch(
        f"/api/handbook-values/{vid}/", {"name": "Поддон", "order": 10}, format="json"
    )
    assert r.status_code == 200 and r.json()["name"] == "Поддон" and r.json()["order"] == 10


# --- удаление ---


def test_unused_value_can_be_deleted(admin_client, company):
    vid = value_id(company, "packaging", "Бочка")
    assert admin_client.delete(f"/api/handbook-values/{vid}/").status_code == 204
    assert not HandbookValue.all_objects.filter(pk=vid).exists()


def test_used_value_cannot_be_deleted_only_deactivated(admin_client, company):
    vid = value_id(company, "packaging", "Бочка")
    HandbookUsage.all_objects.create(company=company, value_id=vid)
    r = admin_client.delete(f"/api/handbook-values/{vid}/")
    assert r.status_code == 409
    assert "деактивируйте" in r.json()["detail"].lower()
    assert HandbookValue.all_objects.filter(pk=vid).exists()
    r = admin_client.patch(f"/api/handbook-values/{vid}/", {"is_active": False}, format="json")
    assert r.status_code == 200 and r.json()["is_active"] is False


# --- инвариант начального статуса ---


@pytest.mark.parametrize("code", STATUS_CODES)
def test_initial_status_cannot_be_deactivated_or_deleted(admin_client, company, code):
    vid = next(v.id for v in values_of(company, code) if v.is_initial)
    r = admin_client.patch(f"/api/handbook-values/{vid}/", {"is_active": False}, format="json")
    assert r.status_code == 400
    assert admin_client.delete(f"/api/handbook-values/{vid}/").status_code == 400
    assert HandbookValue.all_objects.get(pk=vid).is_active is True


def test_cannot_unset_the_only_initial(admin_client, company):
    vid = value_id(company, "order_status", "Новый")
    r = admin_client.patch(f"/api/handbook-values/{vid}/", {"is_initial": False}, format="json")
    assert r.status_code == 400


def test_cannot_add_second_initial(admin_client, company):
    vid = value_id(company, "order_status", "В работе")
    r = admin_client.patch(f"/api/handbook-values/{vid}/", {"is_initial": True}, format="json")
    assert r.status_code == 400
    r = admin_client.post(
        "/api/handbook-values/",
        {"handbook": "order_status", "name": "Черновик", "is_initial": True},
        format="json",
    )
    assert r.status_code == 400
    assert sum(v.is_initial for v in values_of(company, "order_status")) == 1


def test_make_initial_swaps_atomically(admin_client, company):
    vid = value_id(company, "order_status", "В работе")
    r = admin_client.post(f"/api/handbook-values/{vid}/make-initial/")
    assert r.status_code == 200
    initials = [v.name for v in values_of(company, "order_status") if v.is_initial]
    assert initials == ["В работе"]


def test_inactive_value_cannot_become_initial(admin_client, company):
    vid = value_id(company, "order_status", "В работе")
    admin_client.patch(f"/api/handbook-values/{vid}/", {"is_active": False}, format="json")
    assert admin_client.post(f"/api/handbook-values/{vid}/make-initial/").status_code == 400
    assert sum(v.is_initial for v in values_of(company, "order_status")) == 1


def test_non_status_handbook_may_have_no_initial(admin_client, company):
    vid = value_id(company, "packaging", "Бочка")
    assert (
        admin_client.patch(
            f"/api/handbook-values/{vid}/", {"is_active": False}, format="json"
        ).status_code
        == 200
    )


# --- права и подписка ---


def client_with_role(company, role_name, email):
    user = User.objects.create_user(email=email, password="s3cret-pass")
    Membership.objects.create(
        user=user, company=company, role=Role.all_objects.get(company=company, name=role_name)
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    return client


def test_manager_can_view_but_not_edit(company):
    client = client_with_role(company, "Менеджер", "mgr@x.kz")
    assert client.get("/api/handbooks/").status_code == 200
    assert client.get("/api/handbook-values/?handbook=currency").status_code == 200
    vid = value_id(company, "packaging", "Паллета")
    assert (
        client.patch(f"/api/handbook-values/{vid}/", {"name": "x"}, format="json").status_code
        == 403
    )
    assert (
        client.post(
            "/api/handbook-values/", {"handbook": "packaging", "name": "x"}, format="json"
        ).status_code
        == 403
    )
    assert client.delete(f"/api/handbook-values/{vid}/").status_code == 403
    assert client.post(f"/api/handbook-values/{vid}/make-initial/").status_code == 403


def test_readonly_subscription_blocks_writes(admin_client, company):
    Subscription.objects.filter(company=company).update(ends_at=timezone.now() - timedelta(days=20))
    assert admin_client.get("/api/handbooks/").status_code == 200
    r = admin_client.post(
        "/api/handbook-values/", {"handbook": "packaging", "name": "x"}, format="json"
    )
    assert r.status_code == 403 and r.json()["code"] == "subscription_readonly"
