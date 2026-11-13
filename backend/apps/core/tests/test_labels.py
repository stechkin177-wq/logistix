"""Метки: создание, назначение разным объектам, права, фильтры, изоляция, аудит."""

import pytest

from apps.core.audit.models import AuditLog
from apps.core.models import Label, LabelAssignment
from apps.core.tenancy import tenant_context
from apps.forwarding.models import Carrier, Client
from apps.forwarding.tests.test_orders import ORDERS, make_client, make_order
from apps.forwarding.tests.test_parties import client_with_role
from apps.forwarding.tests.test_trips import make_cargos, new_trip

pytestmark = pytest.mark.django_db

LABELS = "/api/labels/"


def make_label(api, name="Срочно", color="red"):
    r = api.post(LABELS, {"name": name, "color": color}, format="json")
    assert r.status_code == 201, r.content
    return r.json()


def set_labels(api, kind, pk, ids):
    return api.put(f"/api/labels/subjects/{kind}/{pk}/", {"labels": ids}, format="json")


def test_label_crud_unique_name_and_colors(admin_client):
    first = make_label(admin_client)
    assert make_label.__name__  # helper used below
    dup = admin_client.post(LABELS, {"name": " срочно ", "color": "blue"}, format="json")
    assert dup.status_code == 400
    assert (
        admin_client.post(LABELS, {"name": "X", "color": "magenta"}, format="json").status_code
        == 400
    )
    assert (
        admin_client.post(LABELS, {"name": "  ", "color": "red"}, format="json").status_code == 400
    )
    ok = admin_client.patch(
        f"{LABELS}{first['id']}/", {"name": "Очень срочно", "color": "amber"}, format="json"
    )
    assert ok.status_code == 200 and ok.json()["color"] == "amber"
    assert [x["name"] for x in admin_client.get(LABELS).json()] == ["Очень срочно"]
    assert admin_client.delete(f"{LABELS}{first['id']}/").status_code == 204
    assert admin_client.get(LABELS).json() == []


def test_same_label_goes_to_different_kinds_of_objects(admin_client, company):
    label = make_label(admin_client)
    client = make_client(company)
    order = make_order(company, client)
    _, ids = make_cargos(company)
    trip = new_trip(admin_client, ids)
    with tenant_context(company.id):
        carrier = Carrier.objects.create(name="П")
    for kind, pk in (
        ("order", order.pk),
        ("trip", trip["id"]),
        ("client", client.pk),
        ("carrier", carrier.pk),
    ):
        r = set_labels(admin_client, kind, pk, [label["id"]])
        assert r.status_code == 200, (kind, r.content)
        assert r.json() == [{"id": label["id"], "name": "Срочно", "color": "red"}]
        assert admin_client.get(f"/api/labels/subjects/{kind}/{pk}/").json()[0]["id"] == label["id"]
    assert admin_client.get(f"{ORDERS}{order.pk}/").json()["labels"][0]["name"] == "Срочно"
    assert admin_client.get(f"/api/trips/{trip['id']}/").json()["labels"][0]["name"] == "Срочно"
    assert admin_client.get(f"/api/clients/{client.pk}/").json()["labels"][0]["name"] == "Срочно"
    assert admin_client.get(LABELS).json()[0]["usage_count"] == 4


def test_list_shows_labels_for_page_and_filters_by_label(admin_client, company):
    red = make_label(admin_client, "Красная", "red")
    blue = make_label(admin_client, "Синяя", "blue")
    client = make_client(company)
    a, b, c = (make_order(company, client) for _ in range(3))
    set_labels(admin_client, "order", a.pk, [red["id"], blue["id"]])
    set_labels(admin_client, "order", b.pk, [blue["id"]])
    listed = admin_client.get(ORDERS).json()["results"]
    by_id = {o["id"]: [x["name"] for x in o["labels"]] for o in listed}
    assert by_id == {a.pk: ["Красная", "Синяя"], b.pk: ["Синяя"], c.pk: []}
    got = admin_client.get(ORDERS, {"label": blue["id"]}).json()["results"]
    assert {o["id"] for o in got} == {a.pk, b.pk}
    assert admin_client.get(ORDERS, {"label": "x"}).status_code == 400
    only_client = admin_client.get("/api/clients/", {"label": red["id"]}).json()["results"]
    assert only_client == []  # метка красная висит на заказе, не на клиенте


def test_replace_remove_and_audit_of_subject(admin_client, company):
    red = make_label(admin_client, "Красная", "red")
    blue = make_label(admin_client, "Синяя", "blue")
    order = make_order(company)
    set_labels(admin_client, "order", order.pk, [red["id"]])
    set_labels(admin_client, "order", order.pk, [blue["id"]])
    assert [
        x["name"] for x in admin_client.get(f"/api/labels/subjects/order/{order.pk}/").json()
    ] == ["Синяя"]
    set_labels(admin_client, "order", order.pk, [])
    with tenant_context(company.id):
        assert LabelAssignment.objects.count() == 0
        rows = list(
            AuditLog.objects.filter(
                object_type="forwarding.order", object_id=str(order.pk), action="update"
            ).order_by("id")
        )
    changes = [r.changes.get("labels") for r in rows if "labels" in r.changes]
    assert changes == [[[], ["Красная"]], [["Красная"], ["Синяя"]], [["Синяя"], []]]


def test_deleting_label_unassigns_it(admin_client, company):
    label = make_label(admin_client)
    order = make_order(company)
    set_labels(admin_client, "order", order.pk, [label["id"]])
    admin_client.delete(f"{LABELS}{label['id']}/")
    assert admin_client.get(f"{ORDERS}{order.pk}/").json()["labels"] == []
    with tenant_context(company.id):
        assert LabelAssignment.objects.count() == 0


def test_validation_and_limits(admin_client, company):
    order = make_order(company)
    assert set_labels(admin_client, "order", order.pk, [999999]).status_code == 400
    assert (
        admin_client.put(
            f"/api/labels/subjects/order/{order.pk}/", {"labels": "1"}, format="json"
        ).status_code
        == 400
    )
    assert set_labels(admin_client, "bogus", 1, []).status_code == 404
    assert set_labels(admin_client, "order", 424242, []).status_code == 404
    many = [make_label(admin_client, f"Л{i}")["id"] for i in range(21)]
    assert set_labels(admin_client, "order", order.pk, many).status_code == 400


def test_permissions(company):
    client = make_client(company)
    order = make_order(company, client)
    _, manager = client_with_role(company, "Менеджер")  # labels.manage + orders.update
    _, observer = client_with_role(company, "Наблюдатель")  # только просмотр
    _, accountant = client_with_role(company, "Бухгалтер")  # orders.view, без update и manage
    label = make_label(manager, "М")
    assert observer.post(LABELS, {"name": "Н", "color": "red"}, format="json").status_code == 403
    assert accountant.post(LABELS, {"name": "Б", "color": "red"}, format="json").status_code == 403
    assert observer.get(LABELS).status_code == 200 and accountant.get(LABELS).status_code == 200
    assert set_labels(observer, "order", order.pk, [label["id"]]).status_code == 403
    assert set_labels(accountant, "order", order.pk, [label["id"]]).status_code == 403
    assert set_labels(manager, "order", order.pk, [label["id"]]).status_code == 200
    assert accountant.get(f"/api/labels/subjects/order/{order.pk}/").status_code == 200
    assert observer.delete(f"{LABELS}{label['id']}/").status_code == 403


def test_isolation_between_companies(make_company):
    a, _, api_a = make_company("A")
    b, _, api_b = make_company("B")
    label_a = make_label(api_a, "Только А")
    client_b = make_client(b)
    order_b = make_order(b, client_b)
    assert api_b.get(LABELS).json() == []
    assert set_labels(api_b, "order", order_b.pk, [label_a["id"]]).status_code == 400  # чужая метка
    order_a = make_order(a)
    assert set_labels(api_b, "order", order_a.pk, []).status_code == 404  # чужой объект
    assert api_b.delete(f"{LABELS}{label_a['id']}/").status_code == 404
    with tenant_context(a.id):
        assert Label.objects.count() == 1
        assert Client.objects.filter(pk=client_b.pk).count() == 0
