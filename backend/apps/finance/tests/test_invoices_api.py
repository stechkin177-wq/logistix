from datetime import date, timedelta

import pytest

from apps.core.audit.models import AuditLog
from apps.core.models import Role
from apps.core.tenancy import tenant_context
from apps.core.tests.test_rls import app_role
from apps.finance.tests.helpers import add_line, cur, make_client, make_order, vat
from apps.forwarding.tests.test_parties import client_with_role

pytestmark = pytest.mark.django_db

INV = "/api/finance/invoices/"


def url(pk, suffix=""):
    return f"{INV}{pk}/{suffix}"


def payload(company, order, lines, *, percent="16", **extra):
    return {
        "direction": "out",
        "party": order.client_id,
        "order": order.pk,
        "currency": cur(company).pk,
        "vat_rate": vat(company, percent).pk,
        "items": [
            {"title": f"п{i}", "amount_net": str(a), "line": ln.pk}
            for i, (ln, a) in enumerate(lines)
        ],
        **extra,
    }


def create(api, company, order, lines, **kw):
    r = api.post(INV, payload(company, order, lines, **kw), format="json")
    assert r.status_code == 201, r.content
    return r.data


@pytest.fixture
def order(company):
    return make_order(company)


def test_create_issue_flow(admin_client, company, order):
    line = add_line(company, order, income=1000)
    d = create(admin_client, company, order, [(line, 1000)])
    assert d["status"] == "draft" and d["display_status"] == "draft" and d["number"] == ""
    r = admin_client.post(url(d["id"], "issue/"), {}, format="json")
    assert r.status_code == 200, r.content
    got = admin_client.get(url(d["id"])).data
    assert got["display_status"] == "issued" and got["number"].startswith("СЧ-")
    assert got["totals"] == {"net": "1000.00", "vat": "160.00", "gross": "1160.00"}
    assert got["paid"] == "0.00" and got["balance"] == "1160.00"
    assert got["client"]["name"] and got["order"]["number"] == order.number
    assert got["currency"]["code"] == "KZT" and len(got["items"]) == 1


def test_patch_issued_forbidden_but_light_fields_ok(admin_client, company, order):
    line = add_line(company, order, income=100)
    d = create(admin_client, company, order, [(line, 100)])
    admin_client.post(url(d["id"], "issue/"), {}, format="json")
    r = admin_client.patch(
        url(d["id"]), {"comment": "новый", "due_date": "2027-01-01"}, format="json"
    )
    assert r.status_code == 200 and r.data["comment"] == "новый"
    r = admin_client.patch(url(d["id"]), {"vat_rate": vat(company, "0").pk}, format="json")
    assert r.status_code == 400 and r.data["code"] == "invoice_not_editable"
    r = admin_client.delete(url(d["id"]))
    assert r.status_code == 400 and r.data["code"] == "invoice_not_editable"


def test_draft_edit_and_delete(admin_client, company, order):
    l1 = add_line(company, order, income=100)
    l2 = add_line(company, order, income=50)
    d = create(admin_client, company, order, [(l1, 100)])
    r = admin_client.patch(
        url(d["id"]),
        {"items": [{"title": "новая", "amount_net": "50", "line": l2.pk}]},
        format="json",
    )
    assert r.status_code == 200 and [i["title"] for i in r.data["items"]] == ["новая"]
    assert admin_client.delete(url(d["id"])).status_code == 204
    assert admin_client.get(url(d["id"])).status_code == 404


def test_permissions_matrix(company, order, admin_client):
    line = add_line(company, order, income=100)
    d = create(admin_client, company, order, [(line, 100)])
    admin_client.post(url(d["id"], "issue/"), {}, format="json")
    _, manager = client_with_role(company, "Менеджер")
    _, accountant = client_with_role(company, "Бухгалтер")
    _, observer = client_with_role(company, "Наблюдатель")
    for api in (manager, accountant, observer):
        assert api.get(INV).status_code == 200
    l2 = add_line(company, order, income=5)
    assert manager.post(INV, payload(company, order, [(l2, 5)]), format="json").status_code == 403
    assert observer.post(url(d["id"], "cancel/")).status_code == 403
    assert manager.post(url(d["id"], "cancel/")).status_code == 403
    assert accountant.post(url(d["id"], "cancel/")).status_code == 200


def test_override_requires_right(company, admin_client):
    client = make_client(company, "Лимит", credit_limit=100)
    order = make_order(company, client=client)
    line = add_line(company, order, income=500)
    d = create(admin_client, company, order, [(line, 500)], percent="0")
    r = admin_client.post(url(d["id"], "issue/"), {}, format="json")
    assert r.status_code == 400 and r.data["code"] == "credit_limit_exceeded"
    with tenant_context(company.id):
        Role.objects.create(
            name="Без обхода", permissions=["finance.view", "finance.create", "finance.update"]
        )
    user, api = client_with_role(company, "Без обхода")
    r = api.post(url(d["id"], "issue/"), {"override_reason": "нужно"}, format="json")
    assert r.status_code == 403
    r = admin_client.post(url(d["id"], "issue/"), {"override_reason": "согласовано"}, format="json")
    assert r.status_code == 200


def test_company_isolation(make_company, order, company, admin_client):
    line = add_line(company, order, income=100)
    d = create(admin_client, company, order, [(line, 100)])
    _, _, other = make_company("Other Co")
    assert other.get(INV).data["results"] == []
    for method, suffix in (
        ("get", ""),
        ("post", "issue/"),
        ("post", "cancel/"),
        ("get", "payments/"),
    ):
        assert getattr(other, method)(url(d["id"], suffix)).status_code == 404


def test_amount_overflow_returns_400(admin_client, company, order):
    line = add_line(company, order, income=100)
    body = payload(company, order, [(line, "99999999999999.99")])
    body["items"][0]["amount_net"] = "123456789012345.00"  # 15 знаков: больше max_digits=14
    r = admin_client.post(INV, body, format="json")
    assert r.status_code == 400


def test_filters(admin_client, company):
    order = make_order(company)
    l1, l2, l3 = (add_line(company, order, income=100) for _ in range(3))
    a = create(
        admin_client, company, order, [(l1, 100)], due_date=str(date.today() - timedelta(days=3))
    )
    b = create(admin_client, company, order, [(l2, 100)])
    admin_client.post(url(a["id"], "issue/"), {}, format="json")
    ids = lambda q: {x["id"] for x in admin_client.get(INV + q).data["results"]}  # noqa: E731
    assert ids("?status=overdue") == {a["id"]}
    assert ids("?overdue=true") == {a["id"]}
    assert ids("?status=draft") == {b["id"]}
    assert ids("?direction=in") == set()
    assert ids(f"?client={order.client_id}") == {a["id"], b["id"]}
    assert ids("?date_from=2999-01-01") == set()
    assert admin_client.get(INV + "?status=bogus").status_code == 400
    assert admin_client.get(INV + "?date_from=junk").status_code == 400


def test_payments_endpoint_and_delete(admin_client, company, order):
    line = add_line(company, order, income=100)
    d = create(admin_client, company, order, [(line, 100)], percent="0")
    admin_client.post(url(d["id"], "issue/"), {}, format="json")
    r = admin_client.post(
        url(d["id"], "payments/"),
        {"date": "2026-10-01", "amount": "40", "method": "bank", "payment_ref": "П-1"},
        format="json",
    )
    assert r.status_code == 201, r.content
    pid = r.data["id"]
    assert admin_client.get(url(d["id"])).data["display_status"] in ("partial", "overdue")
    assert admin_client.get(url(d["id"])).data["balance"] == "60.00"
    r = admin_client.post(
        url(d["id"], "payments/"),
        {"date": "2026-10-01", "amount": "61", "method": "bank"},
        format="json",
    )
    assert r.status_code == 400 and r.data["code"] == "payment_exceeds_balance"
    assert len(admin_client.get(url(d["id"], "payments/")).data["results"]) == 1
    assert len(admin_client.get("/api/finance/payments/").data["results"]) == 1
    assert admin_client.delete(f"/api/finance/payments/{pid}/").status_code == 204
    assert admin_client.get(url(d["id"])).data["balance"] == "100.00"


def test_audit_written_for_create_issue(admin_client, company, order):
    line = add_line(company, order, income=100)
    d = create(admin_client, company, order, [(line, 100)])
    admin_client.post(url(d["id"], "issue/"), {}, format="json")
    with tenant_context(company.id):
        actions = list(
            AuditLog.objects.filter(object_type__icontains="invoice").values_list(
                "action", flat=True
            )
        )
    assert "create" in actions and "update" in actions


def test_deleting_invoiced_order_line_is_400_not_500(admin_client, company, order):
    line = add_line(company, order, income=100)
    create(admin_client, company, order, [(line, 100)])
    r = admin_client.delete(f"/api/order-lines/{line.pk}/")
    assert r.status_code == 400 and r.data["code"] == "line_invoiced"


def test_query_count_stable(admin_client, company, order, django_assert_max_num_queries):
    for _ in range(12):
        line = add_line(company, order, income=1)
        create(admin_client, company, order, [(line, 1)])
    with django_assert_max_num_queries(14):
        r = admin_client.get(INV + "?page_size=50")
    assert r.status_code == 200 and len(r.data["results"]) == 12


def test_rls_role_flow(admin_client, company, order):
    line = add_line(company, order, income=100)
    d = create(admin_client, company, order, [(line, 100)], percent="0")
    with app_role():
        r = admin_client.post(url(d["id"], "issue/"), {}, format="json")
        assert r.status_code == 200, r.content
        r = admin_client.post(
            url(d["id"], "payments/"),
            {"date": "2026-10-01", "amount": "10", "method": "cash"},
            format="json",
        )
        assert r.status_code == 201, r.content
        assert admin_client.get(INV).data["count"] == 1
