"""Этап 1.5-D3/D4: API событий и передач, права, изоляция, фильтр location_status."""

import pytest
from rest_framework.test import APIClient

from apps.core.api.auth import issue_tokens
from apps.core.models import Membership, Role, User
from apps.core.tenancy import tenant_context
from apps.forwarding.models import CargoTransfer, ConsignmentEvent
from apps.forwarding.tests.test_legs import leg, mk_trip, stops_of
from apps.forwarding.tests.test_parties import client_with_role
from apps.forwarding.tests.test_tracking import make_route_cargo

pytestmark = pytest.mark.django_db
CONS = "/api/consignments/"
TRANSFERS = "/api/transfers/"
WHEN = "2026-06-03T12:00:00Z"


def api_with_perms(company, perms, name="Тест"):
    user = User.objects.create_user(email=f"{name}@tracking.kz", password="x")
    with tenant_context(company.id):
        role = Role.objects.create(name=name, permissions=perms)
    Membership.objects.create(user=user, company=company, role=role)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
    return api


@pytest.fixture
def setup(company):
    _, c = make_route_cargo(company)
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    return c, (s1, s2, s3), t1


def body(s2, t1, kind="to_storage", **extra):
    return {
        "transfer_kind": kind,
        "to_stop": s2.pk,
        "from_trip": t1.pk,
        "transferred_at": WHEN,
        **extra,
    }


def test_event_api_creates_and_is_idempotent(admin_client, setup):
    c, (s1, s2, s3), _ = setup
    r = admin_client.post(
        f"{CONS}{c.pk}/events/",
        {"event_type": "arrived", "stop": s1.pk, "occurred_at": WHEN},
        format="json",
    )
    assert r.status_code == 201, r.content
    assert r.data["event_type_name"] and r.data["stop_seq"] == 1
    again = admin_client.post(
        f"{CONS}{c.pk}/events/",
        {"event_type": "arrived", "stop": s1.pk, "occurred_at": WHEN},
        format="json",
    )
    assert again.status_code == 200 and again.data["id"] == r.data["id"]
    assert len(admin_client.get(f"{CONS}{c.pk}/events/").data) == 1
    got = admin_client.get(f"{CONS}{c.pk}/").data
    assert got["location_status"] == "at_stop" and got["current_stop"] == s1.pk
    assert admin_client.get(f"{CONS}?location_status=at_stop").data["count"] == 1
    assert admin_client.get(f"{CONS}?location_status=delivered").data["count"] == 0
    bad = admin_client.post(
        f"{CONS}{c.pk}/events/", {"event_type": "delivered", "stop": s1.pk}, format="json"
    )
    assert bad.status_code == 400


def test_old_fields_of_consignment_still_present(admin_client, setup):
    c, *_ = setup
    d = admin_client.get(f"{CONS}{c.pk}/").data
    for key in ("points", "stops", "route", "trips_count", "status", "order"):
        assert key in d
    assert d["location_status"] == "planned" and d["location_status_name"]


def test_transfer_lifecycle_through_api(admin_client, setup):
    c, (s1, s2, s3), t1 = setup
    r = admin_client.post(f"{CONS}{c.pk}/transfers/", body(s2, t1), format="json")
    assert r.status_code == 201, r.content
    assert (
        r.data["status"] == "initiated"
        and r.data["to_trip"] is None
        and r.data["reversed_by"] is None
    )
    tid = r.data["id"]
    assert admin_client.get(f"{TRANSFERS}?pending=1").data["count"] == 1
    ok = admin_client.post(f"{TRANSFERS}{tid}/confirm/")
    assert ok.status_code == 200 and ok.data["status"] == "confirmed"
    assert admin_client.get(f"{CONS}{c.pk}/").data["location_status"] == "in_storage"
    assert admin_client.get(f"{CONS}?location_status=in_storage").data["count"] == 1
    assert admin_client.get(f"{TRANSFERS}?pending=1").data["count"] == 0
    rev = admin_client.post(f"{TRANSFERS}{tid}/reverse/", {"note": "ошибка"}, format="json")
    assert (
        rev.status_code == 201 and rev.data["status"] == "reversed" and rev.data["reverses"] == tid
    )
    assert admin_client.get(f"{TRANSFERS}{tid}/").data["reversed_by"] == rev.data["id"]
    assert admin_client.get(f"{CONS}{c.pk}/").data["location_status"] != "in_storage"
    assert admin_client.post(f"{TRANSFERS}{tid}/reverse/").status_code == 400
    assert admin_client.get(f"{TRANSFERS}?status=reversed").data["count"] == 1
    assert admin_client.get(f"{TRANSFERS}?kind=to_storage&consignment={c.pk}").data["count"] == 2
    assert len(admin_client.get(f"{CONS}{c.pk}/transfers/").data) == 2
    assert admin_client.delete(f"{TRANSFERS}{tid}/").status_code == 405  # удаления нет


def test_api_validation_errors(admin_client, setup):
    c, (s1, s2, s3), t1 = setup
    r = admin_client.post(f"{CONS}{c.pk}/transfers/", body(s3, t1), format="json")
    assert r.status_code == 400 and "to_stop" in r.data
    r = admin_client.post(
        f"{CONS}{c.pk}/transfers/", {"transfer_kind": "to_storage"}, format="json"
    )
    assert r.status_code == 400
    r = admin_client.post(f"{CONS}{c.pk}/transfers/", body(s2, t1, kind="nope"), format="json")
    assert r.status_code == 400


def test_driver_initiates_with_update_permission_dispatcher_confirms(company, setup):
    c, (s1, s2, s3), t1 = setup
    driver = api_with_perms(company, ["consignments.view", "consignments.update"], "Водитель-тест")
    r = driver.post(f"{CONS}{c.pk}/transfers/", body(s2, t1, source="driver_app"), format="json")
    assert r.status_code == 201 and r.data["source"] == "driver_app"
    tid = r.data["id"]
    assert driver.post(f"{TRANSFERS}{tid}/confirm/").status_code == 403  # без consignments.transfer
    assert driver.post(f"{TRANSFERS}{tid}/reverse/").status_code == 403
    _, dispatcher = client_with_role(company, "Диспетчер")
    assert dispatcher.post(f"{TRANSFERS}{tid}/confirm/").status_code == 200
    _, manager = client_with_role(company, "Менеджер")
    assert manager.post(f"{TRANSFERS}{tid}/reverse/").status_code == 201


def test_transfer_permission_alone_can_initiate_but_viewer_cannot(company, setup):
    c, (s1, s2, s3), t1 = setup
    only_transfer = api_with_perms(
        company, ["consignments.view", "consignments.transfer"], "Только-передача"
    )
    assert (
        only_transfer.post(f"{CONS}{c.pk}/transfers/", body(s2, t1), format="json").status_code
        == 201
    )
    assert (
        only_transfer.post(
            f"{CONS}{c.pk}/events/", {"event_type": "arrived", "stop": s1.pk}, format="json"
        ).status_code
        == 403
    )
    _, observer = client_with_role(company, "Наблюдатель")
    assert observer.post(f"{CONS}{c.pk}/transfers/", body(s2, t1), format="json").status_code == 403
    assert (
        observer.post(
            f"{CONS}{c.pk}/events/", {"event_type": "arrived", "stop": s1.pk}, format="json"
        ).status_code
        == 403
    )
    assert observer.get(f"{CONS}{c.pk}/events/").status_code == 200
    assert observer.get(TRANSFERS).status_code == 200
    _, driver_role = client_with_role(company, "Водитель")
    assert driver_role.get(TRANSFERS).status_code == 403


def test_company_isolation(make_company, setup):
    c, (s1, s2, s3), t1 = setup
    _, _, other_api = make_company("Чужая")
    assert other_api.get(f"{CONS}{c.pk}/events/").status_code == 404
    assert (
        other_api.post(f"{CONS}{c.pk}/transfers/", body(s2, t1), format="json").status_code == 404
    )
    assert other_api.get(TRANSFERS).data["count"] == 0


def test_audit_written_for_every_action(admin_client, company, setup):
    from apps.core.audit.models import AuditLog

    c, (s1, s2, s3), t1 = setup
    admin_client.post(
        f"{CONS}{c.pk}/events/",
        {"event_type": "arrived", "stop": s1.pk, "occurred_at": WHEN},
        format="json",
    )
    tid = admin_client.post(f"{CONS}{c.pk}/transfers/", body(s2, t1), format="json").data["id"]
    admin_client.post(f"{TRANSFERS}{tid}/confirm/")
    admin_client.post(f"{TRANSFERS}{tid}/reverse/")
    with tenant_context(company.id):
        types = sorted(
            AuditLog.objects.filter(
                object_type__in=["forwarding.cargotransfer", "forwarding.consignmentevent"]
            ).values_list("object_type", "action")
        )
        assert types.count(("forwarding.cargotransfer", "create")) == 2
        assert ("forwarding.cargotransfer", "update") in types
        assert types.count(("forwarding.consignmentevent", "create")) == 2  # событие + stored
        assert CargoTransfer.objects.count() == 2 and ConsignmentEvent.objects.count() == 2


def test_list_queries_do_not_grow(admin_client, company, setup, django_assert_max_num_queries):
    c, (s1, s2, s3), t1 = setup
    for _ in range(3):
        admin_client.post(f"{CONS}{c.pk}/transfers/", body(s2, t1), format="json")
    with django_assert_max_num_queries(12):
        assert admin_client.get(TRANSFERS).data["count"] == 3
