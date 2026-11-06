import pytest

from apps.core.audit.models import AuditLog
from apps.core.handbooks.models import HandbookValue
from apps.core.tenancy import tenant_context
from apps.finance.tests.helpers import add_line, cur, make_order, vat
from apps.forwarding.tests.test_parties import client_with_role

pytestmark = pytest.mark.django_db

RATES = "/api/finance/rates/"


def body(company, code="USD", **extra):
    return {"currency": cur(company, code).pk, "date": "2026-05-01", "rate": "450.5", **extra}


def test_create_list_update_delete(admin_client, company):
    r = admin_client.post(RATES, body(company), format="json")
    assert r.status_code == 201, r.content
    rid = r.data["id"]
    assert r.data["currency"]["code"] == "USD" and r.data["rate"] == "450.500000"
    assert admin_client.get(RATES).data["count"] == 1
    assert admin_client.get(RATES + "?currency=" + str(cur(company, "USD").pk)).data["count"] == 1
    assert admin_client.get(RATES + "?date_from=2026-06-01").data["count"] == 0
    r = admin_client.patch(f"{RATES}{rid}/", {"rate": "451"}, format="json")
    assert r.status_code == 200 and r.data["rate"] == "451.000000"
    assert admin_client.delete(f"{RATES}{rid}/").status_code == 204
    assert admin_client.get(RATES).data["count"] == 0


def test_kzt_rate_rejected(admin_client, company):
    r = admin_client.post(RATES, body(company, "KZT"), format="json")
    assert r.status_code == 400 and "currency" in r.data


def test_duplicate_day_is_400_not_500(admin_client, company):
    assert admin_client.post(RATES, body(company), format="json").status_code == 201
    r = admin_client.post(RATES, body(company), format="json")
    assert r.status_code == 400


def test_foreign_handbook_value_rejected(admin_client, company):
    wrong = vat(company, "16").pk  # значение справочника ставок НДС, не валюты
    assert admin_client.post(RATES, body(company, currency=wrong), format="json").status_code == 400
    # и в счёте: валюта не из справочника currency / ставка не из vat_rate
    order = make_order(company)
    line = add_line(company, order, income=10)
    payload = {
        "direction": "out",
        "party": order.client_id,
        "order": order.pk,
        "currency": cur(company).pk,
        "vat_rate": cur(company).pk,
        "items": [{"title": "x", "amount_net": "10", "line": line.pk}],
    }
    r = admin_client.post("/api/finance/invoices/", payload, format="json")
    assert r.status_code == 400 and "vat_rate" in r.data


def test_rate_validation(admin_client, company):
    for bad in ("0", "-1", "abc", "12345678901234567.0"):
        r = admin_client.post(RATES, body(company, rate=bad), format="json")
        assert r.status_code == 400, bad
    assert (
        admin_client.post(RATES, body(company, date="2026-13-40"), format="json").status_code == 400
    )


def test_permissions(company, admin_client):
    admin_client.post(RATES, body(company), format="json")
    _, manager = client_with_role(company, "Менеджер")
    assert manager.get(RATES).status_code == 200
    assert manager.post(RATES, body(company, date="2026-05-02"), format="json").status_code == 403
    _, accountant = client_with_role(company, "Бухгалтер")
    assert (
        accountant.post(RATES, body(company, date="2026-05-03"), format="json").status_code == 201
    )
    _, observer = client_with_role(company, "Наблюдатель")
    assert observer.delete(f"{RATES}1/").status_code in (403, 404)


def test_isolation(make_company, company, admin_client):
    r = admin_client.post(RATES, body(company), format="json")
    _, _, other = make_company("Other")
    assert other.get(RATES).data["count"] == 0
    assert other.patch(f"{RATES}{r.data['id']}/", {"rate": "1"}, format="json").status_code == 404
    other_usd = HandbookValue.all_objects.filter(handbook__code="currency", code="USD").exclude(
        pk=cur(company, "USD").pk
    )
    assert other_usd.exists()  # значение чужой компании по id в нашу не принимается
    foreign = other_usd.first().pk
    assert (
        admin_client.post(RATES, body(company, currency=foreign), format="json").status_code == 400
    )


def test_audit_written(admin_client, company):
    admin_client.post(RATES, body(company), format="json")
    with tenant_context(company.id):
        assert AuditLog.objects.filter(
            action="create", object_type__icontains="exchangerate"
        ).exists()
