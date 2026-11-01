import threading
from datetime import datetime, timedelta
from datetime import timezone as dt_tz

import pytest
import time_machine
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from apps.billing.models import Subscription
from apps.core import trash
from apps.core.audit.models import AuditLog
from apps.core.handbooks.models import HandbookValue
from apps.core.models import LegalEntity, Membership, Role, User
from apps.core.numbering.models import NumberingRule
from apps.core.numbering.services import next_number
from apps.core.tenancy import tenant_context
from apps.forwarding.models import (
    Client,
    Consignment,
    ConsignmentPoint,
    Contact,
    Order,
    OrderStatusHistory,
)
from apps.forwarding.orders.services import change_status, create_order
from apps.forwarding.tests.test_parties import client_with_role

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=dt_tz.utc)
ORDERS = "/api/orders/"
CONSIGNMENTS = "/api/consignments/"


@pytest.fixture(autouse=True)
def frozen():
    with time_machine.travel(NOW, tick=False):
        yield


# --- помощники ---


def hv(company, handbook, name=None, **filters):
    """Значение справочника компании (по названию или коду)."""
    with tenant_context(company.id):
        qs = HandbookValue.objects.filter(handbook__code=handbook)
        if name:
            filters["name"] = name
        return qs.get(**filters)


def status_id(company, name):
    return hv(company, "order_status", name).pk


def make_client(company, name="ТОО Клиент"):
    with tenant_context(company.id):
        return Client.objects.create(name=name)


def make_contact(company, client, name="Контакт", **extra):
    with tenant_context(company.id):
        return Contact.objects.create(client=client, name=name, **extra)


def point(kind, city, **extra):
    base = {
        "kind": kind,
        "window_from": "2026-06-02T09:00:00Z",
        "window_to": "2026-06-02T18:00:00Z",
        "city": city,
    }
    return {**base, **extra}


def cargo(name="Мука", load="Шымкент", unload="Алматы", **extra):
    return {
        "name": name,
        "weight_kg": "1500.50",
        "volume_m3": "12.00",
        "pallets": 4,
        **extra,
        "points": [point("load", load), point("unload", unload)],
    }


def order_payload(client, **extra):
    return {"client": client.pk, **extra}


def new_order(api, client, **extra):
    r = api.post(ORDERS, order_payload(client, **extra), format="json")
    assert r.status_code == 201, r.content
    return r.data


def make_order(company, client=None, user=None, **extra):
    """Заказ без API (через сервис)."""
    client = client or make_client(company)
    with tenant_context(company.id):
        user = user or Membership.objects.filter(company=company).first().user
        return create_order({"client": client, **extra}, user)


def audit_rows(company, **filters):
    with tenant_context(company.id):
        return list(AuditLog.objects.filter(**filters).order_by("id"))


@pytest.fixture
def two(make_company):
    return make_company("Co A"), make_company("Co B")


# --- справочник: коды статусов ---


def test_order_status_codes_in_defaults():
    from apps.core.handbooks.defaults import DEFAULTS

    codes = {v["name"]: v.get("code") for v in DEFAULTS["order_status"]["values"]}
    assert codes["Завершён"] == "completed" and codes["Отменён"] == "cancelled"
    assert codes["Новый"] is None


# --- создание ---


def test_create_order_with_consignment_and_points(admin_client, company, admin_user):
    client = make_client(company)
    contact = make_contact(company, client)
    r = admin_client.post(
        ORDERS,
        order_payload(
            client,
            contact=contact.pk,
            client_ref="PO-77",
            contract_number="Д-1",
            client_rate="250000.00",
            delivery_days=5,
            payment_delay_days=14,
            comment="хрупкое",
            consignments=[cargo()],
        ),
        format="json",
    )
    assert r.status_code == 201, r.content
    d = r.data
    assert d["number"] == "ORD-2026-00001"
    assert d["status_name"] == "Новый" and d["status"] == status_id(company, "Новый")
    assert d["route"] == "Шымкент → Алматы"
    assert d["client"] == client.pk and d["client_name"] == "ТОО Клиент"
    assert d["contact"] == contact.pk and d["client_ref"] == "PO-77"
    assert d["client_rate"] == "250000.00" and d["comment"] == "хрупкое"
    assert d["manager"] == admin_user.pk and d["forwarder"] is None
    assert d["extra_managers"] == [] and d["completed_at"] is None
    assert d["currency"] == hv(company, "currency", code="KZT").pk
    with tenant_context(company.id):
        assert d["legal_entity"] == LegalEntity.objects.get(is_default=True).pk
    assert d["has_carrier"] is False and d["created_by"] == admin_user.pk
    [c] = d["consignments"]
    assert c["name"] == "Мука" and c["weight_kg"] == "1500.50" and c["pallets"] == 4
    assert c["status_name"] == "Принят"
    assert [p["kind"] for p in c["points"]] == ["load", "unload"]
    assert c["points"][0]["city"] == "Шымкент"
    [h] = d["history"]
    assert h["from_status"] is None and h["to_status"] == d["status"]
    assert h["user"] == admin_user.pk
    got = admin_client.get(f"{ORDERS}{d['id']}/")
    assert got.status_code == 200 and got.data["route"] == "Шымкент → Алматы"
    with tenant_context(company.id):
        assert OrderStatusHistory.objects.count() == 1
        assert Consignment.objects.get().order_id == d["id"]
        assert ConsignmentPoint.objects.count() == 2


@pytest.mark.parametrize("extra", [{}, {"consignments": []}])
def test_order_without_consignments_is_created_and_read(admin_client, company, extra):
    client = make_client(company)
    d = new_order(admin_client, client, **extra)
    assert d["consignments"] == [] and d["route"] == ""
    got = admin_client.get(f"{ORDERS}{d['id']}/")
    assert got.status_code == 200 and got.data["consignments"] == [] and got.data["route"] == ""
    listing = admin_client.get(ORDERS)
    assert listing.status_code == 200
    assert listing.data["results"][0]["route"] == ""


def test_two_orders_get_distinct_sequential_numbers(admin_client, company):
    client = make_client(company)
    first = new_order(admin_client, client)
    second = new_order(admin_client, client)
    assert (first["number"], second["number"]) == ("ORD-2026-00001", "ORD-2026-00002")


def test_numbers_are_never_reused_after_soft_delete(admin_client, company):
    client = make_client(company)
    first = new_order(admin_client, client)
    assert admin_client.delete(f"{ORDERS}{first['id']}/").status_code == 204
    assert new_order(admin_client, client)["number"] == "ORD-2026-00002"
    with pytest.raises(IntegrityError), transaction.atomic():
        with tenant_context(company.id):  # то же имя, что у мягко удалённого
            Order.objects.create(client=client, number="ORD-2026-00001", **_db_defaults(company))


def _db_defaults(company):
    return {
        "manager": Membership.objects.filter(company=company).first().user,
        "legal_entity": LegalEntity.objects.get(company=company, is_default=True),
        "currency": hv(company, "currency", code="KZT"),
        "status": hv(company, "order_status", is_initial=True),
    }


def test_number_conflict_is_409_and_rolls_back(admin_client, company):
    client = make_client(company)
    new_order(admin_client, client)
    with tenant_context(company.id):
        NumberingRule.objects.filter(kind="order").update(next_value=1)  # владелец сбросил счётчик
    r = admin_client.post(ORDERS, order_payload(client, consignments=[cargo()]), format="json")
    assert r.status_code == 409 and "нумерац" in str(r.data["detail"]).lower()
    with tenant_context(company.id):
        assert Order.objects.count() == 1 and Consignment.objects.count() == 0
        assert NumberingRule.objects.get(kind="order").next_value == 1


@pytest.mark.parametrize("field", ["number", "status", "completed_at"])
def test_client_cannot_supply_number_status_completed_at(admin_client, company, field):
    client = make_client(company)
    r = admin_client.post(ORDERS, order_payload(client, **{field: "x"}), format="json")
    assert r.status_code == 400 and field in r.data
    with tenant_context(company.id):
        assert Order.objects.count() == 0


def test_patch_rejects_status_number_consignments(admin_client, company):
    client = make_client(company)
    d = new_order(admin_client, client)
    url = f"{ORDERS}{d['id']}/"
    for field, value in [
        ("status", status_id(company, "В работе")),
        ("number", "HACK-1"),
        ("consignments", [cargo()]),
        ("completed_at", "2026-01-01T00:00:00Z"),
    ]:
        r = admin_client.patch(url, {field: value}, format="json")
        assert r.status_code == 400 and field in r.data, field
    after = admin_client.get(url).data
    assert after["number"] == d["number"] and after["status"] == d["status"]
    assert after["consignments"] == [] and audit_rows(company, action="update") == []


def test_rate_and_days_validated(admin_client, company):
    client = make_client(company)
    for bad in (
        {"client_rate": "-1"},
        {"delivery_days": -1},
        {"payment_delay_days": -5},
        {"client_rate": "abc"},
    ):
        r = admin_client.post(ORDERS, order_payload(client, **bad), format="json")
        assert r.status_code == 400 and next(iter(bad)) in r.data, bad
    assert admin_client.post(ORDERS, {}, format="json").data.keys() >= {"client"}


def test_db_checks_on_order_and_cargo(company):
    order = make_order(company)
    with pytest.raises(IntegrityError), transaction.atomic(), tenant_context(company.id):
        Order.objects.filter(pk=order.pk).update(client_rate=-1)
    with tenant_context(company.id):
        for field, value in [("weight_kg", -1), ("volume_m3", -1)]:
            with pytest.raises(IntegrityError), transaction.atomic():
                Consignment.objects.create(
                    order=order,
                    name="x",
                    **{"weight_kg": 1, "volume_m3": 1, field: value},
                    status=hv(company, "consignment_status", is_initial=True),
                )


# --- ссылки на чужие/неподходящие объекты ---


def test_foreign_and_wrong_references_are_400(two, admin_user):
    (comp_a, _, api_a), (comp_b, user_b, api_b) = two
    client_b = make_client(comp_b)
    client_a = make_client(comp_a)
    contact_a = make_contact(comp_a, client_a)
    with tenant_context(comp_a.id):
        entity_a = LegalEntity.objects.get(is_default=True)
    cases = {
        "client": client_a.pk,
        "manager": admin_user.pk,
        "forwarder": admin_user.pk,
        "extra_managers": [admin_user.pk],
        "legal_entity": entity_a.pk,
        "currency": hv(comp_a, "currency", code="KZT").pk,
        "transport_condition": hv(comp_a, "transport_condition", "FCA").pk,
        "payment_delay_condition": hv(comp_a, "payment_delay_condition", "С даты счёта").pk,
        "contact": contact_a.pk,
    }
    for field, value in cases.items():
        body = {"client": client_b.pk, field: value} if field != "client" else {"client": value}
        r = api_b.post(ORDERS, body, format="json")
        assert r.status_code == 400 and field in r.data, field
    with tenant_context(comp_b.id):
        assert Order.objects.count() == 0
    # собственный клиент компании B и собственные значения принимаются
    ok = api_b.post(
        ORDERS,
        {"client": client_b.pk, "currency": hv(comp_b, "currency", code="USD").pk},
        format="json",
    )
    assert ok.status_code == 201 and ok.data["manager"] == user_b.pk


def test_contact_of_another_client_same_company_is_400(admin_client, company):
    c1, c2 = make_client(company, "К1"), make_client(company, "К2")
    contact2 = make_contact(company, c2)
    r = admin_client.post(ORDERS, order_payload(c1, contact=contact2.pk), format="json")
    assert r.status_code == 400 and "contact" in r.data
    d = new_order(admin_client, c1, contact=make_contact(company, c1).pk)
    # смена клиента без смены контакта оставила бы чужой контакт
    r = admin_client.patch(f"{ORDERS}{d['id']}/", {"client": c2.pk}, format="json")
    assert r.status_code == 400 and "contact" in r.data
    r = admin_client.patch(
        f"{ORDERS}{d['id']}/", {"client": c2.pk, "contact": contact2.pk}, format="json"
    )
    assert r.status_code == 200 and r.data["client_name"] == "К2"


def test_deleted_client_rejected_but_unchanged_tolerated(admin_client, company):
    client = make_client(company)
    d = new_order(admin_client, client)
    with tenant_context(company.id):
        client.delete()
    assert admin_client.post(ORDERS, order_payload(client), format="json").status_code == 400
    r = admin_client.patch(
        f"{ORDERS}{d['id']}/", {"client": client.pk, "comment": "z"}, format="json"
    )
    assert r.status_code == 200 and r.data["comment"] == "z"


def test_manager_must_be_active_member(admin_client, company):
    client = make_client(company)
    user, _ = client_with_role(company, "Менеджер")
    assert new_order(admin_client, client, manager=user.pk)["manager"] == user.pk
    Membership.objects.filter(user=user, company=company).update(is_active=False)
    r = admin_client.post(ORDERS, order_payload(client, manager=user.pk), format="json")
    assert r.status_code == 400 and "manager" in r.data
    loner = User.objects.create_user(email="loner@x.kz", password="x")
    r = admin_client.post(ORDERS, order_payload(client, forwarder=loner.pk), format="json")
    assert r.status_code == 400 and "forwarder" in r.data


def test_forwarder_and_extra_managers(admin_client, company, admin_user):
    client = make_client(company)
    u1, _ = client_with_role(company, "Менеджер")
    u2, _ = client_with_role(company, "Диспетчер")
    d = new_order(admin_client, client, forwarder=u1.pk, extra_managers=[u1.pk, u2.pk])
    assert d["forwarder"] == u1.pk and sorted(d["extra_managers"]) == sorted([u1.pk, u2.pk])
    r = admin_client.patch(f"{ORDERS}{d['id']}/", {"extra_managers": [u2.pk]}, format="json")
    assert r.status_code == 200 and r.data["extra_managers"] == [u2.pk]
    row = audit_rows(company, action="update", object_type="forwarding.order")[-1]
    assert row.changes["extra_managers"] == [sorted([u1.pk, u2.pk]), [u2.pk]]


@pytest.mark.parametrize(
    ("field", "handbook", "wrong_handbook"),
    [
        ("currency", "currency", "transport_condition"),
        ("transport_condition", "transport_condition", "currency"),
        ("payment_delay_condition", "payment_delay_condition", "currency"),
    ],
)
def test_handbook_value_must_be_active_and_of_right_handbook(
    admin_client, company, field, handbook, wrong_handbook
):
    client = make_client(company)
    with tenant_context(company.id):
        wrong = HandbookValue.objects.filter(handbook__code=wrong_handbook).first().pk
        good = HandbookValue.objects.filter(handbook__code=handbook).first()
    r = admin_client.post(ORDERS, order_payload(client, **{field: wrong}), format="json")
    assert r.status_code == 400 and field in r.data
    d = new_order(admin_client, client, **{field: good.pk})
    with tenant_context(company.id):
        HandbookValue.objects.filter(pk=good.pk).update(is_active=False)
    r = admin_client.post(ORDERS, order_payload(client, **{field: good.pk}), format="json")
    assert r.status_code == 400 and field in r.data
    # неизменённое отключённое значение при PATCH допустимо
    r = admin_client.patch(f"{ORDERS}{d['id']}/", {"comment": "ok"}, format="json")
    assert r.status_code == 200 and r.data[field] == good.pk
    r = admin_client.patch(f"{ORDERS}{d['id']}/", {field: good.pk}, format="json")
    assert r.status_code == 200


def test_currency_cannot_be_null(admin_client, company):
    d = new_order(admin_client, make_client(company))
    r = admin_client.patch(f"{ORDERS}{d['id']}/", {"currency": None}, format="json")
    assert r.status_code == 400 and "currency" in r.data
    r = admin_client.patch(f"{ORDERS}{d['id']}/", {"transport_condition": None}, format="json")
    assert r.status_code == 200


def test_patch_updates_fields_and_audits(admin_client, company):
    client = make_client(company)
    d = new_order(admin_client, client, client_rate="100.00")
    r = admin_client.patch(
        f"{ORDERS}{d['id']}/", {"client_rate": "175.50", "comment": "новое"}, format="json"
    )
    assert r.status_code == 200 and r.data["client_rate"] == "175.50"
    row = audit_rows(company, action="update", object_type="forwarding.order")[-1]
    assert row.changes == {
        "client_rate": ["100.00", "175.50"],
        "comment": ["", "новое"],
    }
    assert admin_client.patch(f"{ORDERS}{d['id']}/", {"comment": "новое"}, format="json")
    assert len(audit_rows(company, action="update", object_type="forwarding.order")) == 1


# --- груз и точки при создании заказа ---


def test_invalid_second_consignment_creates_nothing(admin_client, company):
    client = make_client(company)
    bad = cargo("Плохой")
    bad["points"] = bad["points"][:1]
    r = admin_client.post(ORDERS, order_payload(client, consignments=[cargo(), bad]), format="json")
    assert r.status_code == 400 and "consignments" in r.data
    with tenant_context(company.id):
        assert Order.objects.count() == 0 and Consignment.objects.count() == 0
        assert OrderStatusHistory.objects.count() == 0
    assert new_order(admin_client, client)["number"] == "ORD-2026-00001"  # номер не сгорел


@pytest.mark.parametrize(
    "points",
    [
        [],
        [point("load", "A")],
        [point("unload", "A")],
        [point("load", "A"), point("load", "B")],
        [point("load", "A"), point("unload", "B"), point("unload", "C")],
        [point("load", "A"), point("transit", "B")],
        [point("load", "A"), point("unload", "")],
        [point("load", "A"), point("unload", "B", window_to="2026-06-01T09:00:00Z")],
        [point("load", "A"), point("unload", "B", lat="91")],
        [point("load", "A"), point("unload", "B", lng="-180.5")],
        [point("load", "A"), {"kind": "unload", "city": "B"}],
    ],
)
def test_points_must_be_exactly_valid_load_and_unload(admin_client, company, points):
    client = make_client(company)
    body = order_payload(client, consignments=[{**cargo(), "points": points}])
    r = admin_client.post(ORDERS, body, format="json")
    assert r.status_code == 400 and "consignments" in r.data, points


def test_point_optional_fields_and_window_to_null(admin_client, company):
    client = make_client(company)
    country = hv(company, "country", code="KZ").pk
    method = hv(company, "loading_method", "Боковая").pk
    pts = [
        point(
            "load",
            "Шымкент",
            window_to=None,
            country=country,
            method=method,
            street="Ул. 1",
            contact="Иван +77001112233",
            postal_code="160000",
            lat="42.3417",
            lng="69.5901",
            note="шлагбаум",
        ),
        point("unload", "Алматы"),
    ]
    d = new_order(admin_client, client, consignments=[{**cargo(), "points": pts}])
    load = d["consignments"][0]["points"][0]
    assert load["window_to"] is None and load["country"] == country and load["method"] == method
    assert load["country_name"] == "Казахстан" and load["method_name"] == "Боковая"
    assert load["lat"] == "42.341700" and load["contact"] == "Иван +77001112233"


def test_cargo_validation(admin_client, company):
    client = make_client(company)
    for bad in (
        {"weight_kg": "-1"},
        {"volume_m3": "-0.5"},
        {"pallets": -1},
        {"name": ""},
        {"packaging": hv(company, "currency", code="KZT").pk},
        {"status": hv(company, "order_status", is_initial=True).pk},
    ):
        r = admin_client.post(
            ORDERS, order_payload(client, consignments=[{**cargo(), **bad}]), format="json"
        )
        assert r.status_code == 400, bad
    ok = new_order(
        admin_client,
        client,
        consignments=[{**cargo(), "packaging": hv(company, "packaging", "Паллета").pk}],
    )
    assert ok["consignments"][0]["packaging_name"] == "Паллета"


def test_route_uses_first_consignment_with_both_points(admin_client, company):
    client = make_client(company)
    d = new_order(
        admin_client,
        client,
        consignments=[cargo("Первый", "Астана", "Тараз"), cargo("Второй", "Омск", "Тверь")],
    )
    assert d["route"] == "Астана → Тараз"
    with tenant_context(company.id):
        first = Consignment.objects.order_by("id").first()
        first.points.filter(kind="unload").delete()  # у первого нет второй точки
    got = admin_client.get(f"{ORDERS}{d['id']}/")
    assert got.data["route"] == "Омск → Тверь"


def test_consignment_point_unique_per_kind(company):
    order = make_order(company, consignments=[_svc_cargo()])
    with tenant_context(company.id):
        cons = Consignment.objects.get(order=order)
        with pytest.raises(IntegrityError), transaction.atomic():
            ConsignmentPoint.objects.create(
                consignment=cons, kind="load", window_from=NOW, city="Дубль"
            )
        with pytest.raises(IntegrityError), transaction.atomic():
            ConsignmentPoint.objects.filter(consignment=cons, kind="load").update(
                window_to=NOW - timedelta(days=1)
            )
        with pytest.raises(IntegrityError), transaction.atomic():
            ConsignmentPoint.objects.filter(consignment=cons, kind="load").update(lat=100)


def _svc_cargo(**extra):
    """Груз в формате сервиса (значения справочников - не нужны, статус по умолчанию)."""
    return {
        "name": "Сервисный",
        "weight_kg": 10,
        "volume_m3": 1,
        "points": [
            {"kind": "load", "window_from": NOW, "city": "Шымкент"},
            {"kind": "unload", "window_from": NOW, "city": "Алматы"},
        ],
        **extra,
    }


# --- смена статуса ---


def status_url(order_id):
    return f"{ORDERS}{order_id}/status/"


def test_status_change_writes_history_and_audit(admin_client, company, admin_user):
    d = new_order(admin_client, make_client(company))
    new, work = status_id(company, "Новый"), status_id(company, "В работе")
    r = admin_client.post(status_url(d["id"]), {"status": work}, format="json")
    assert r.status_code == 200, r.content
    assert r.data["status"] == work and r.data["status_name"] == "В работе"
    assert [h["to_status"] for h in r.data["history"]] == [new, work]
    assert r.data["history"][1]["from_status"] == new
    assert r.data["history"][1]["user"] == admin_user.pk
    row = audit_rows(company, action="update", object_type="forwarding.order")[-1]
    assert row.changes == {"status_id": [new, work]}
    assert row.user_id == admin_user.pk and row.ip == "127.0.0.1"
    assert admin_client.get(f"{ORDERS}{d['id']}/").data["status_name"] == "В работе"


def test_completed_sets_and_reopen_clears_completed_at(admin_client, company):
    d = new_order(admin_client, make_client(company))
    url = status_url(d["id"])
    r = admin_client.post(url, {"status": status_id(company, "Завершён")}, format="json")
    assert r.status_code == 200
    assert parse_datetime(r.data["completed_at"]) == NOW
    row = audit_rows(company, action="update", object_type="forwarding.order")[-1]
    assert set(row.changes) == {"status_id", "completed_at"}
    r = admin_client.post(url, {"status": status_id(company, "В работе")}, format="json")
    assert r.status_code == 200 and r.data["completed_at"] is None
    with tenant_context(company.id):
        assert Order.objects.get(pk=d["id"]).completed_at is None


def test_other_non_completed_statuses_do_not_set_completed_at(admin_client, company):
    d = new_order(admin_client, make_client(company))
    url = status_url(d["id"])
    for name in ("На погрузке", "В пути", "На выгрузке"):
        r = admin_client.post(url, {"status": status_id(company, name)}, format="json")
        assert r.data["completed_at"] is None, name
    admin_client.post(url, {"status": status_id(company, "Завершён")}, format="json")
    r = admin_client.post(url, {"status": status_id(company, "Отменён")}, format="json")
    assert r.status_code == 200 and r.data["completed_at"] is None  # отмена - не завершение


def test_completed_is_determined_by_code_not_name(admin_client, company):
    d = new_order(admin_client, make_client(company))
    with tenant_context(company.id):
        HandbookValue.objects.filter(code="completed").update(name="Готово")
    r = admin_client.post(
        status_url(d["id"]), {"status": status_id(company, "Готово")}, format="json"
    )
    assert r.status_code == 200 and r.data["completed_at"] is not None


def test_same_status_change_is_400(admin_client, company):
    d = new_order(admin_client, make_client(company))
    r = admin_client.post(
        status_url(d["id"]), {"status": status_id(company, "Новый")}, format="json"
    )
    assert r.status_code == 400 and "status" in r.data
    with tenant_context(company.id):
        assert OrderStatusHistory.objects.count() == 1


def test_any_to_any_transitions_are_allowed(admin_client, company):
    d = new_order(admin_client, make_client(company))
    for name in ("Завершён", "Новый", "В пути", "Отменён", "На погрузке"):
        r = admin_client.post(
            status_url(d["id"]), {"status": status_id(company, name)}, format="json"
        )
        assert r.status_code == 200, name


def test_status_value_validation(two):
    (comp_a, _, _), (comp_b, _, api_b) = two
    d = new_order(api_b, make_client(comp_b))
    url = status_url(d["id"])
    bad_values = [
        status_id(comp_a, "В работе"),  # чужая компания
        hv(comp_b, "consignment_status", "На складе").pk,  # не тот справочник
        10**9,
        "abc",
        None,
    ]
    for value in bad_values:
        r = api_b.post(url, {"status": value}, format="json")
        assert r.status_code == 400 and "status" in r.data, value
    assert api_b.post(url, {}, format="json").status_code == 400
    inactive = status_id(comp_b, "В пути")
    with tenant_context(comp_b.id):
        HandbookValue.objects.filter(pk=inactive).update(is_active=False)
    assert api_b.post(url, {"status": inactive}, format="json").status_code == 400
    with tenant_context(comp_b.id):
        assert OrderStatusHistory.objects.count() == 1


def test_service_validates_status_itself(company):
    order = make_order(company)
    with tenant_context(company.id):
        wrong = HandbookValue.objects.get(handbook__code="consignment_status", is_initial=True)
        user = Membership.objects.filter(company=company).first().user
        from rest_framework.exceptions import ValidationError

        with pytest.raises(ValidationError):
            change_status(order, wrong, user)
        with pytest.raises(ValidationError):
            change_status(order, order.status, user)


def test_status_change_requires_orders_update(company, admin_client):
    d = new_order(admin_client, make_client(company))
    work = status_id(company, "В работе")
    for role in ("Наблюдатель", "Механик", "Бухгалтер"):
        _, api = client_with_role(company, role)
        r = api.post(status_url(d["id"]), {"status": work}, format="json")
        assert r.status_code == 403, role
    with tenant_context(company.id):
        role = Role.objects.create(name="Только просмотр", permissions=["orders.view"])
    user = User.objects.create_user(email="viewonly@x.kz", password="x")
    Membership.objects.create(user=user, company=company, role=role)
    from apps.core.api.auth import issue_tokens

    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    assert api.post(status_url(d["id"]), {"status": work}, format="json").status_code == 403
    with tenant_context(company.id):
        order = Order.objects.get(pk=d["id"])
        assert order.status.name == "Новый" and OrderStatusHistory.objects.count() == 1
    assert audit_rows(company, action="update") == []
    _, manager_api = client_with_role(company, "Менеджер")
    assert manager_api.post(status_url(d["id"]), {"status": work}, format="json").status_code == 200


def test_status_endpoint_method_and_foreign_order(two):
    (comp_a, _, api_a), (comp_b, _, api_b) = two
    d = new_order(api_a, make_client(comp_a))
    work = status_id(comp_a, "В работе")
    assert api_b.post(status_url(d["id"]), {"status": work}, format="json").status_code == 404
    assert api_a.get(status_url(d["id"])).status_code == 405
    with tenant_context(comp_a.id):
        assert Order.objects.get(pk=d["id"]).status.name == "Новый"


# --- чтение: список, детали, фильтры ---


def test_history_only_on_detail(admin_client, company):
    d = new_order(admin_client, make_client(company))
    assert "history" in admin_client.get(f"{ORDERS}{d['id']}/").data
    assert "history" not in admin_client.get(ORDERS).data["results"][0]


def test_list_default_order_pagination_and_filters(admin_client, company):
    c1, c2 = make_client(company, "Альфа"), make_client(company, "Бета")
    ids = []
    for i, client in enumerate([c1, c2, c1]):
        d = new_order(admin_client, client, consignments=[cargo(f"Груз-{i}")] if i != 1 else [])
        with tenant_context(company.id):
            Order.objects.filter(pk=d["id"]).update(created_at=NOW + timedelta(hours=i))
        ids.append(d["id"])
    listing = admin_client.get(ORDERS)
    assert [o["id"] for o in listing.data["results"]] == ids[::-1]  # -created_at
    assert listing.data["count"] == 3
    page = admin_client.get(ORDERS, {"page_size": 2})
    assert len(page.data["results"]) == 2 and page.data["next"]
    assert [o["id"] for o in admin_client.get(ORDERS, {"client": c1.pk}).data["results"]] == [
        ids[2],
        ids[0],
    ]
    work = status_id(company, "В работе")
    admin_client.post(status_url(ids[1]), {"status": work}, format="json")
    assert [o["id"] for o in admin_client.get(ORDERS, {"status": work}).data["results"]] == [ids[1]]
    assert admin_client.get(ORDERS, {"q": "ORD-2026-00002"}).data["count"] == 1
    assert admin_client.get(ORDERS, {"q": "ord-2026-0000"}).data["count"] == 3
    assert [o["id"] for o in admin_client.get(ORDERS, {"q": "БЕТА"}).data["results"]] == [ids[1]]
    assert [o["id"] for o in admin_client.get(ORDERS, {"q": "груз-2"}).data["results"]] == [ids[2]]
    assert admin_client.get(ORDERS, {"q": "несуществует"}).data["count"] == 0
    assert admin_client.get(ORDERS, {"q": "%"}).data["count"] == 0  # подстановка не работает
    asc = admin_client.get(ORDERS, {"ordering": "created_at"})
    assert [o["id"] for o in asc.data["results"]] == ids
    for bad in ({"client": "x"}, {"status": "1;"}, {"ordering": "client_rate"}):
        assert admin_client.get(ORDERS, bad).status_code == 400, bad


def test_search_does_not_duplicate_orders(admin_client, company):
    d = new_order(
        admin_client,
        make_client(company),
        consignments=[cargo("Мука А"), cargo("Мука Б")],
    )
    r = admin_client.get(ORDERS, {"q": "мука"})
    assert r.data["count"] == 1 and r.data["results"][0]["id"] == d["id"]


LIST_QUERY_BOUND = (
    10  # измерено: 10 запросов на любой размер списка (auth, подписка, count, заказы + 3 prefetch)
)


def test_list_query_count_is_flat(admin_client, company, django_assert_max_num_queries):
    clients = [make_client(company, f"Клиент {i}") for i in range(5)]
    user = Membership.objects.filter(company=company).first().user
    with tenant_context(company.id):
        for i in range(25):
            create_order(
                {
                    "client": clients[i % 5],
                    "consignments": [_svc_cargo(), _svc_cargo(name="Второй")],
                },
                user,
            )
    with django_assert_max_num_queries(LIST_QUERY_BOUND):
        r = admin_client.get(ORDERS, {"q": "Серв", "ordering": "-created_at"})
    assert r.status_code == 200 and len(r.data["results"]) == 25
    for o in r.data["results"]:
        assert len(o["consignments"]) == 2 and o["route"] == "Шымкент → Алматы"
        assert o["status_name"] == "Новый" and o["client_name"].startswith("Клиент")
        assert len(o["consignments"][0]["points"]) == 2


def test_detail_query_count_is_flat(admin_client, company, django_assert_max_num_queries):
    user = Membership.objects.filter(company=company).first().user
    with tenant_context(company.id):
        order = create_order(
            {"client": make_client(company), "consignments": [_svc_cargo() for _ in range(6)]},
            user,
        )
    with django_assert_max_num_queries(LIST_QUERY_BOUND):
        r = admin_client.get(f"{ORDERS}{order.pk}/")
    assert r.status_code == 200 and len(r.data["consignments"]) == 6


# --- мягкое удаление и корзина ---


def test_delete_is_soft_and_restorable(admin_client, company):
    d = new_order(admin_client, make_client(company), consignments=[cargo()])
    url = f"{ORDERS}{d['id']}/"
    assert admin_client.delete(url).status_code == 204
    assert admin_client.get(url).status_code == 404
    assert admin_client.get(ORDERS).data["count"] == 0
    with tenant_context(company.id):
        assert Order.trash.filter(pk=d["id"]).exists()
        assert Consignment.objects.filter(order_id=d["id"]).exists()  # грузы не удаляются
    t = admin_client.get("/api/trash/").data["results"][0]
    assert (t["code"], t["id"], t["label"]) == ("orders", d["id"], "ORD-2026-00001")
    assert admin_client.post(f"/api/trash/orders/{d['id']}/restore/").status_code == 200
    got = admin_client.get(url)
    assert got.status_code == 200 and len(got.data["consignments"]) == 1
    deleted = audit_rows(company, action="delete", object_type="forwarding.order")
    restored = audit_rows(company, action="restore", object_type="forwarding.order")
    assert len(deleted) == 1 and len(restored) == 1


def test_trash_registered():
    reg = trash.registered()
    assert reg["orders"] == (Order, "orders.view")
    assert reg["consignments"] == (Consignment, "consignments.view")


def test_consignments_of_deleted_order_are_hidden_and_restore_blocked(admin_client, company):
    d = new_order(admin_client, make_client(company), consignments=[cargo(), cargo("Второй")])
    cid = d["consignments"][0]["id"]
    assert admin_client.get(f"{CONSIGNMENTS}{cid}/").status_code == 200
    admin_client.delete(f"{ORDERS}{d['id']}/")
    assert admin_client.get(CONSIGNMENTS).data["count"] == 0
    assert admin_client.get(f"{CONSIGNMENTS}{cid}/").status_code == 404
    assert (
        admin_client.patch(f"{CONSIGNMENTS}{cid}/", {"name": "x"}, format="json").status_code == 404
    )
    assert admin_client.delete(f"{CONSIGNMENTS}{cid}/").status_code == 404
    admin_client.post(f"/api/trash/orders/{d['id']}/restore/")
    assert admin_client.get(CONSIGNMENTS).data["count"] == 2


def test_restore_consignment_with_deleted_order_is_409(admin_client, company):
    d = new_order(admin_client, make_client(company), consignments=[cargo()])
    cid = d["consignments"][0]["id"]
    assert admin_client.delete(f"{CONSIGNMENTS}{cid}/").status_code == 204
    admin_client.delete(f"{ORDERS}{d['id']}/")
    r = admin_client.post(f"/api/trash/consignments/{cid}/restore/")
    assert r.status_code == 409 and "заказ" in r.data["detail"].lower()
    with tenant_context(company.id):
        assert Consignment.trash.filter(pk=cid).exists()
    admin_client.post(f"/api/trash/orders/{d['id']}/restore/")
    assert admin_client.post(f"/api/trash/consignments/{cid}/restore/").status_code == 200
    assert admin_client.get(f"{CONSIGNMENTS}{cid}/").status_code == 200


def test_order_in_trash_hidden_without_permission(company, admin_client):
    d = new_order(admin_client, make_client(company))
    admin_client.delete(f"{ORDERS}{d['id']}/")
    with tenant_context(company.id):
        role = Role.objects.create(name="Корзина", permissions=["trash.view", "trash.update"])
    user = User.objects.create_user(email="trash-o@x.kz", password="x")
    Membership.objects.create(user=user, company=company, role=role)
    from apps.core.api.auth import issue_tokens

    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    assert api.get("/api/trash/").data["results"] == []
    assert api.post(f"/api/trash/orders/{d['id']}/restore/").status_code == 403


# --- API грузов ---


def test_consignment_crud(admin_client, company):
    d = new_order(admin_client, make_client(company))
    body = {**cargo(), "order": d["id"]}
    r = admin_client.post(CONSIGNMENTS, body, format="json")
    assert r.status_code == 201, r.content
    c = r.data
    assert c["order"] == d["id"] and c["order_number"] == d["number"]
    assert c["status_name"] == "Принят" and len(c["points"]) == 2
    assert admin_client.get(f"{ORDERS}{d['id']}/").data["route"] == "Шымкент → Алматы"
    url = f"{CONSIGNMENTS}{c['id']}/"
    r = admin_client.patch(url, {"name": "Сахар", "pallets": 9}, format="json")
    assert r.status_code == 200 and r.data["name"] == "Сахар" and len(r.data["points"]) == 2
    done = hv(company, "consignment_status", "Доставлен").pk
    r = admin_client.patch(url, {"status": done}, format="json")
    assert r.status_code == 200 and r.data["status_name"] == "Доставлен"
    rows = audit_rows(company, object_type="forwarding.consignment")
    assert [x.action for x in rows] == ["create", "update", "update"]
    assert rows[0].changes["points"] == "changed" and rows[1].changes["name"] == ["Мука", "Сахар"]
    assert rows[2].changes == {"status_id": [hv(company, "consignment_status", "Принят").pk, done]}
    assert admin_client.delete(url).status_code == 204
    assert admin_client.get(url).status_code == 404
    assert admin_client.get(f"{ORDERS}{d['id']}/").data["consignments"] == []


def test_consignment_create_needs_order_and_exactly_two_points(admin_client, company, two=None):
    d = new_order(admin_client, make_client(company))
    r = admin_client.post(CONSIGNMENTS, cargo(), format="json")
    assert r.status_code == 400 and "order" in r.data
    for points in ([], [point("load", "A")], [point("unload", "A"), point("unload", "B")]):
        r = admin_client.post(
            CONSIGNMENTS, {**cargo(), "order": d["id"], "points": points}, format="json"
        )
        assert r.status_code == 400 and "points" in r.data, points
    body = {**cargo(), "order": d["id"]}
    del body["points"]
    assert admin_client.post(CONSIGNMENTS, body, format="json").status_code == 400
    with tenant_context(company.id):
        assert Consignment.objects.count() == 0 and ConsignmentPoint.objects.count() == 0


def test_consignment_order_must_be_own_and_not_deleted(two):
    (comp_a, _, api_a), (comp_b, _, api_b) = two
    d_a = new_order(api_a, make_client(comp_a))
    r = api_b.post(CONSIGNMENTS, {**cargo(), "order": d_a["id"]}, format="json")
    assert r.status_code == 400 and "order" in r.data
    api_a.delete(f"{ORDERS}{d_a['id']}/")
    r = api_a.post(CONSIGNMENTS, {**cargo(), "order": d_a["id"]}, format="json")
    assert r.status_code == 400 and "order" in r.data


def test_consignment_patch_points_and_order_immutable(admin_client, company):
    d1 = new_order(admin_client, make_client(company), consignments=[cargo()])
    d2 = new_order(admin_client, make_client(company, "Другой"))
    cid = d1["consignments"][0]["id"]
    url = f"{CONSIGNMENTS}{cid}/"
    r = admin_client.patch(url, {"order": d2["id"]}, format="json")
    assert r.status_code == 400 and "order" in r.data
    assert admin_client.patch(url, {"order": d1["id"]}, format="json").status_code == 200
    r = admin_client.patch(
        url, {"points": [{"kind": "load", "city": "Тараз"}, {"kind": "unload"}]}, format="json"
    )
    assert r.status_code == 200, r.content
    assert r.data["points"][0]["city"] == "Тараз" and r.data["points"][1]["city"] == "Алматы"
    assert admin_client.get(f"{ORDERS}{d1['id']}/").data["route"] == "Тараз → Алматы"
    for bad in ([{"kind": "load"}], [{"kind": "load"}, {"kind": "load"}], []):
        assert admin_client.patch(url, {"points": bad}, format="json").status_code == 400, bad
    r = admin_client.patch(
        url,
        {"points": [{"kind": "load", "window_to": "2026-01-01T00:00:00Z"}, {"kind": "unload"}]},
        format="json",
    )
    assert r.status_code == 400  # окно заканчивается раньше начала
    assert admin_client.get(url).data["points"][0]["city"] == "Тараз"
    last = audit_rows(company, object_type="forwarding.consignment")[-1]
    assert last.changes == {"points": "changed"}


def test_consignment_list_filters(admin_client, company):
    client = make_client(company)
    d1 = new_order(admin_client, client, consignments=[cargo("Мука"), cargo("Сахар")])
    d2 = new_order(admin_client, client, consignments=[cargo("Соль")])
    assert admin_client.get(CONSIGNMENTS).data["count"] == 3
    assert admin_client.get(CONSIGNMENTS, {"order": d1["id"]}).data["count"] == 2
    assert admin_client.get(CONSIGNMENTS, {"order": d2["id"]}).data["count"] == 1
    assert admin_client.get(CONSIGNMENTS, {"q": "МУКА"}).data["count"] == 1
    assert admin_client.get(CONSIGNMENTS, {"order": "x"}).status_code == 400


def test_consignment_list_query_count(admin_client, company, django_assert_max_num_queries):
    user = Membership.objects.filter(company=company).first().user
    with tenant_context(company.id):
        client = make_client(company)
        for _ in range(10):
            create_order({"client": client, "consignments": [_svc_cargo(), _svc_cargo()]}, user)
    with django_assert_max_num_queries(LIST_QUERY_BOUND):
        r = admin_client.get(CONSIGNMENTS)
    assert r.data["count"] == 20


# --- аудит: персональные данные ---


def test_audit_never_logs_contact_data(admin_client, company):
    client = make_client(company)
    contact = make_contact(company, client, phone="87001112233", email="secret@x.kz")
    pts = [
        point("load", "Шымкент", contact="Иван 87009998877"),
        point("unload", "Алматы"),
    ]
    new_order(
        admin_client,
        client,
        contact=contact.pk,
        consignments=[{**cargo(), "points": pts}],
    )
    dump = " ".join(str(r.changes) for r in audit_rows(company))
    for secret in ("87001112233", "+77001112233", "secret@x.kz", "87009998877"):
        assert secret not in dump
    types = {r.object_type for r in audit_rows(company)}
    assert types == {"forwarding.order", "forwarding.consignment"}
    order_row = audit_rows(company, object_type="forwarding.order")[0]
    assert order_row.action == "create" and order_row.changes["number"] == [None, "ORD-2026-00001"]


# --- клиенты: orders_count ---


def test_client_orders_count(admin_client, company):
    c1, c2 = make_client(company, "Один"), make_client(company, "Два")
    o1 = new_order(admin_client, c1)
    new_order(admin_client, c1)
    new_order(admin_client, c2)
    admin_client.delete(f"{ORDERS}{o1['id']}/")  # удалённые не считаются
    rows = {x["name"]: x["orders_count"] for x in admin_client.get("/api/clients/").data["results"]}
    assert rows == {"Один": 1, "Два": 1}
    assert admin_client.get(f"/api/clients/{c1.pk}/").data["orders_count"] == 1
    created = admin_client.post("/api/clients/", {"name": "Новый"}, format="json")
    assert created.data["orders_count"] == 0
    patched = admin_client.patch(f"/api/clients/{c1.pk}/", {"notes": "x"}, format="json")
    assert patched.data["orders_count"] == 1
    assert "orders_count" not in admin_client.get("/api/carriers/").content.decode()


def test_client_list_query_count_with_orders_count(
    admin_client, company, django_assert_max_num_queries
):
    with tenant_context(company.id):
        for i in range(10):
            make_order(company, make_client(company, f"К{i}"))
    with django_assert_max_num_queries(10):
        r = admin_client.get("/api/clients/")
    assert r.data["count"] == 10 and all(x["orders_count"] == 1 for x in r.data["results"])


# --- изоляция компаний ---


def test_orders_isolation_between_companies(two):
    (comp_a, _, api_a), (comp_b, _, api_b) = two
    client_a = make_client(comp_a, "Клиент А")
    d = new_order(api_a, client_a, consignments=[cargo("Секретный груз")])
    url = f"{ORDERS}{d['id']}/"
    assert api_a.get(url).status_code == 200
    assert api_b.get(url).status_code == 404
    assert api_b.patch(url, {"comment": "hack"}, format="json").status_code == 404
    assert api_b.put(url, {"client": client_a.pk}, format="json").status_code == 404
    assert api_b.delete(url).status_code == 404
    assert api_b.get(ORDERS).data["count"] == 0
    for params in (
        {"q": "Секретный"},
        {"q": "ORD"},
        {"q": "Клиент"},
        {"client": client_a.pk},
        {"status": status_id(comp_a, "Новый")},
    ):
        assert api_b.get(ORDERS, params).data["count"] == 0, params
    assert "Секретный" not in api_b.get(ORDERS).content.decode()
    api_a.delete(url)
    assert api_b.get("/api/trash/").data["results"] == []
    assert api_b.post(f"/api/trash/orders/{d['id']}/restore/").status_code == 404
    with tenant_context(comp_a.id):
        assert Order.trash.filter(pk=d["id"]).exists()
    # у компании B своя нумерация
    client_b = make_client(comp_b)
    assert new_order(api_b, client_b)["number"] == "ORD-2026-00001"


def test_consignments_isolation_between_companies(two):
    (comp_a, _, api_a), (comp_b, _, api_b) = two
    d = new_order(api_a, make_client(comp_a), consignments=[cargo("Груз А")])
    cid = d["consignments"][0]["id"]
    url = f"{CONSIGNMENTS}{cid}/"
    assert api_a.get(url).status_code == 200
    assert api_b.get(url).status_code == 404
    assert api_b.patch(url, {"name": "hack"}, format="json").status_code == 404
    assert api_b.put(url, cargo(), format="json").status_code == 404
    assert api_b.delete(url).status_code == 404
    assert api_b.get(CONSIGNMENTS).data["count"] == 0
    assert api_b.get(CONSIGNMENTS, {"order": d["id"]}).data["count"] == 0
    assert api_b.get(CONSIGNMENTS, {"q": "Груз"}).data["count"] == 0
    api_a.delete(url)
    assert api_b.post(f"/api/trash/consignments/{cid}/restore/").status_code == 404
    with tenant_context(comp_a.id):
        assert Consignment.trash.filter(pk=cid).exists()


def test_cargo_references_of_foreign_company_rejected(two):
    (comp_a, _, _), (comp_b, _, api_b) = two
    d = new_order(api_b, make_client(comp_b))
    foreign_pack = hv(comp_a, "packaging", "Паллета").pk
    foreign_country = hv(comp_a, "country", code="KZ").pk
    foreign_method = hv(comp_a, "loading_method", "Боковая").pk
    foreign_status = hv(comp_a, "consignment_status", is_initial=True).pk
    for bad in ({"packaging": foreign_pack}, {"status": foreign_status}):
        r = api_b.post(CONSIGNMENTS, {**cargo(), "order": d["id"], **bad}, format="json")
        assert r.status_code == 400, bad
    for bad in ({"country": foreign_country}, {"method": foreign_method}):
        pts = [point("load", "A", **bad), point("unload", "B")]
        r = api_b.post(CONSIGNMENTS, {**cargo(), "order": d["id"], "points": pts}, format="json")
        assert r.status_code == 400, bad


# --- права, модуль, подписка ---


def test_manager_can_create_and_update_but_not_delete(company, admin_client):
    _, api = client_with_role(company, "Менеджер")
    client = make_client(company)
    r = api.post(ORDERS, order_payload(client, consignments=[cargo()]), format="json")
    assert r.status_code == 201
    url = f"{ORDERS}{r.data['id']}/"
    assert api.get(url).status_code == 200
    assert api.patch(url, {"comment": "m"}, format="json").status_code == 200
    assert api.delete(url).status_code == 403
    assert admin_client.get(url).status_code == 200
    cid = r.data["consignments"][0]["id"]
    assert api.patch(f"{CONSIGNMENTS}{cid}/", {"name": "n"}, format="json").status_code == 200
    assert api.delete(f"{CONSIGNMENTS}{cid}/").status_code == 403


def test_dispatcher_can_create_and_update_but_not_delete(company):
    _, api = client_with_role(company, "Диспетчер")
    client = make_client(company)
    r = api.post(ORDERS, order_payload(client), format="json")
    assert r.status_code == 201
    r2 = api.post(CONSIGNMENTS, {**cargo(), "order": r.data["id"]}, format="json")
    assert r2.status_code == 201
    assert api.patch(f"{ORDERS}{r.data['id']}/", {"comment": "d"}, format="json").status_code == 200
    assert (
        api.post(
            status_url(r.data["id"]), {"status": status_id(company, "В работе")}, format="json"
        ).status_code
        == 200
    )
    assert api.delete(f"{ORDERS}{r.data['id']}/").status_code == 403
    assert api.delete(f"{CONSIGNMENTS}{r2.data['id']}/").status_code == 403


def test_observer_read_only(company):
    order = make_order(company, consignments=[_svc_cargo()])
    with tenant_context(company.id):
        cid = Consignment.objects.get().pk
    _, api = client_with_role(company, "Наблюдатель")
    url = f"{ORDERS}{order.pk}/"
    assert api.get(ORDERS).status_code == 200 and api.get(url).status_code == 200
    assert api.get(CONSIGNMENTS).status_code == 200
    assert api.post(ORDERS, {"client": order.client_id}, format="json").status_code == 403
    assert api.patch(url, {"comment": "x"}, format="json").status_code == 403
    assert api.delete(url).status_code == 403
    assert api.post(CONSIGNMENTS, {**cargo(), "order": order.pk}, format="json").status_code == 403
    assert api.patch(f"{CONSIGNMENTS}{cid}/", {"name": "x"}, format="json").status_code == 403
    assert api.delete(f"{CONSIGNMENTS}{cid}/").status_code == 403


@pytest.mark.parametrize("role", ["Механик", "Водитель"])
def test_roles_without_access_get_403(company, role):
    order = make_order(company)
    with tenant_context(company.id):
        r = Role.objects.get(name=role)
    user = User.objects.create_user(email=f"{role}@x.kz", password="x")
    Membership.objects.create(user=user, company=company, role=r)
    from apps.core.api.auth import issue_tokens

    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    assert api.get(ORDERS).status_code == 403
    assert api.get(f"{ORDERS}{order.pk}/").status_code == 403
    assert api.get(CONSIGNMENTS).status_code == 403


def test_unauthenticated_is_401():
    assert APIClient().get(ORDERS).status_code in (401, 403)
    assert APIClient().get(CONSIGNMENTS).status_code in (401, 403)


def test_module_disabled(make_company):
    _, _, api = make_company("Fleet only", modules=["fleet"])
    for url in (ORDERS, CONSIGNMENTS):
        r = api.get(url)
        assert r.status_code == 403 and r.data["code"] == "module_disabled"
    assert api.post(ORDERS, {"client": 1}, format="json").status_code == 403
    assert api.post(status_url(1), {"status": 1}, format="json").status_code == 403


def test_readonly_subscription_blocks_writes_but_not_reads(company, admin_client):
    d = new_order(admin_client, make_client(company))
    Subscription.objects.filter(company=company).update(ends_at=timezone.now() - timedelta(days=20))
    assert admin_client.get(ORDERS).status_code == 200
    r = admin_client.post(ORDERS, {"client": 1}, format="json")
    assert r.status_code == 403 and r.data["code"] == "subscription_readonly"
    assert (
        admin_client.patch(f"{ORDERS}{d['id']}/", {"comment": "y"}, format="json").status_code
        == 403
    )
    r = admin_client.post(
        status_url(d["id"]), {"status": status_id(company, "В работе")}, format="json"
    )
    assert r.status_code == 403 and r.data["code"] == "subscription_readonly"
    assert (
        admin_client.post(CONSIGNMENTS, {**cargo(), "order": d["id"]}, format="json").status_code
        == 403
    )


def test_blocked_subscription_blocks_reads(company, admin_client):
    Subscription.objects.filter(company=company).update(status=Subscription.BLOCKED)
    r = admin_client.get(ORDERS)
    assert r.status_code == 403 and r.data["code"] == "subscription_blocked"


# --- RLS и параллелизм ---


def test_rls_guard_covers_new_tables():
    from apps.core import rls

    tables = [
        "forwarding_order",
        "forwarding_orderstatushistory",
        "forwarding_consignment",
        "forwarding_consignmentpoint",
    ]
    assert set(tables) <= set(rls.tenant_tables())
    assert rls.tables_missing_rls(tables) == []


def test_order_flows_work_under_app_role(db, api_client):
    from apps.core.services import create_company_with_defaults
    from apps.core.tests.test_rls import app_role, raw
    from conftest import TEST_PASSWORD

    with app_role():
        admin = User.objects.create_user(email="rls-ord@x.kz", password=TEST_PASSWORD)
        company = create_company_with_defaults("RLS Ord", admin, ["forwarding"])
        other = User.objects.create_user(email="rls-ord2@x.kz", password=TEST_PASSWORD)
        create_company_with_defaults("RLS Ord 2", other, ["forwarding"])
        resp = api_client.post(
            "/api/auth/login/", {"login": "rls-ord@x.kz", "password": TEST_PASSWORD}
        )
        assert resp.status_code == 200, resp.content
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
        cl = api_client.post("/api/clients/", {"name": "ТОО Тест"}, format="json")
        assert cl.status_code == 201, cl.content
        created = api_client.post(
            ORDERS, {"client": cl.data["id"], "consignments": [cargo()]}, format="json"
        )
        assert created.status_code == 201, created.content
        oid = created.data["id"]
        assert created.data["number"].startswith("ORD-") and created.data["route"]
        work = status_id(company, "В работе")
        r = api_client.post(status_url(oid), {"status": work}, format="json")
        assert r.status_code == 200, r.content
        r = api_client.post(CONSIGNMENTS, {**cargo("Второй"), "order": oid}, format="json")
        assert r.status_code == 201, r.content
        assert api_client.get(ORDERS, {"q": "второй"}).data["count"] == 1
        assert api_client.get("/api/clients/").data["results"][0]["orders_count"] == 1
        assert api_client.delete(f"{ORDERS}{oid}/").status_code == 204
        assert api_client.get("/api/trash/").data["count"] == 1
        restored = api_client.post(f"/api/trash/orders/{oid}/restore/")
        assert restored.status_code == 200, restored.content
        assert len(api_client.get(f"{ORDERS}{oid}/").data["consignments"]) == 2
        # без контекста компании роль приложения не видит ни строки
        for table in ("order", "orderstatushistory", "consignment", "consignmentpoint"):
            assert raw(f"SELECT count(*) FROM forwarding_{table}")[0][0] == 0, table


def _run_create_threads(company, user_id, total, workers):
    results, errors = [], []
    lock = threading.Lock()
    counter = iter(range(total))
    client = make_client(company)

    def worker():
        try:
            while True:
                with lock:
                    try:
                        next(counter)
                    except StopIteration:
                        return
                with tenant_context(company.id):
                    order = create_order(
                        {"client": client, "consignments": [_svc_cargo()]},
                        User.objects.get(pk=user_id),
                    )
                with lock:
                    results.append(order.number)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    return results


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_order_creation_gets_distinct_gap_free_numbers(make_company):
    company, admin, _ = make_company("ConcOrders")
    results = _run_create_threads(company, admin.pk, 8, 4)
    assert sorted(results) == [f"ORD-2026-{i:05d}" for i in range(1, 9)]
    with tenant_context(company.id):
        assert Order.objects.count() == 8 and Consignment.objects.count() == 8
        assert next_number("order") == "ORD-2026-00009"


# --- контакты клиента, на которые ссылаются заказы ---


def _client_with_two_contacts(admin_client, company):
    r = admin_client.post(
        "/api/clients/",
        {"name": "Старое имя", "contacts": [{"name": "Первый"}, {"name": "Второй"}]},
        format="json",
    )
    assert r.status_code == 201, r.content
    return r.data["id"], r.data["contacts"]


@pytest.mark.parametrize("order_deleted", [False, True])
def test_client_patch_dropping_contact_used_by_order_is_409(admin_client, company, order_deleted):
    cid, contacts = _client_with_two_contacts(admin_client, company)
    used, other = contacts[0]["id"], contacts[1]["id"]
    d = new_order(admin_client, _client_obj(company, cid), contact=used)
    if order_deleted:
        assert admin_client.delete(f"{ORDERS}{d['id']}/").status_code == 204
    audits_before = len(audit_rows(company))
    r = admin_client.patch(
        f"/api/clients/{cid}/",
        {"name": "Новое имя", "contacts": [{"id": other, "name": "Второй изменён"}]},
        format="json",
    )
    assert r.status_code == 409 and "Контакт используется в заказах" in r.data["detail"]
    after = admin_client.get(f"/api/clients/{cid}/").data
    assert after["name"] == "Старое имя"
    assert [(c["id"], c["name"]) for c in after["contacts"]] == [
        (used, "Первый"),
        (other, "Второй"),
    ]
    assert len(audit_rows(company)) == audits_before  # неудачный запрос в аудит не попал


def _client_obj(company, pk):
    with tenant_context(company.id):
        return Client.objects.get(pk=pk)


def test_client_patch_dropping_unused_contact_still_works(admin_client, company):
    cid, contacts = _client_with_two_contacts(admin_client, company)
    new_order(admin_client, _client_obj(company, cid), contact=contacts[0]["id"])
    r = admin_client.patch(
        f"/api/clients/{cid}/", {"contacts": [{"id": contacts[0]["id"]}]}, format="json"
    )
    assert r.status_code == 200 and [c["id"] for c in r.data["contacts"]] == [contacts[0]["id"]]


def test_create_audit_records_extra_managers(admin_client, company):
    u1, _ = client_with_role(company, "Менеджер")
    new_order(admin_client, make_client(company), extra_managers=[u1.pk])
    row = audit_rows(company, action="create", object_type="forwarding.order")[0]
    assert row.changes["extra_managers"] == [[], [u1.pk]]
    new_order(admin_client, make_client(company))
    row2 = audit_rows(company, action="create", object_type="forwarding.order")[1]
    assert "extra_managers" not in row2.changes
