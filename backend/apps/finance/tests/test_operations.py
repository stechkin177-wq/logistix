import io
from datetime import date

import pytest
from openpyxl import load_workbook

from apps.core.handbooks.models import HandbookValue
from apps.core.models import Company
from apps.core.tenancy import tenant_context
from apps.finance.tests.helpers import add_line, make_client, make_order, set_rate

pytestmark = pytest.mark.django_db

OPS = "/api/finance/operations/"


def seed(company):
    """Заказ KZT: доход 1000/расход 300 (5 мая); заказ USD: доход 100/расход 40 (6 мая)."""
    kz = make_order(company)
    add_line(company, kz, income=1000, expense=300, day=date(2026, 5, 5), category="Перевозка")
    usd = make_order(company, currency="USD")
    add_line(company, usd, income=100, expense=40, day=date(2026, 5, 6), category="Прочее")
    return kz, usd


def test_filters_and_totals_kzt(admin_client, company):
    seed(company)
    r = admin_client.get(OPS + "?category=Перевозка")
    assert r.status_code == 200
    assert [x["income"] for x in r.data["results"]] == ["1000.00"]
    s = r.data["summary"]
    assert (s["income_kzt"], s["expense_kzt"], s["diff_kzt"]) == ("1000.00", "300.00", "700.00")
    assert admin_client.get(OPS + "?date_from=2026-05-06").data["count"] == 1
    assert admin_client.get(OPS + "?date_to=2026-05-05").data["count"] == 1


def test_foreign_currency_converted_and_breakdown(admin_client, company):
    seed(company)
    set_rate(company, "USD", 450, day=date(2026, 5, 1))
    s = admin_client.get(OPS).data["summary"]
    # 1000 + 100*450 = 46000 доход; 300 + 40*450 = 18300 расход
    assert (s["income_kzt"], s["expense_kzt"], s["diff_kzt"]) == (
        "46000.00",
        "18300.00",
        "27700.00",
    )
    assert s["by_currency"]["USD"] == {"income": "100.00", "expense": "40.00", "diff": "60.00"}
    assert s["by_currency"]["KZT"]["income"].startswith("1000")
    assert s["unconverted"] == 0


def test_missing_rate_goes_to_unconverted(admin_client, company):
    seed(company)
    s = admin_client.get(OPS).data["summary"]
    assert s["unconverted"] == 1
    assert (s["income_kzt"], s["expense_kzt"]) == ("1000.00", "300.00")  # USD-строка не суммируется
    assert "USD" in s["by_currency"]


def test_excludes_cancelled_and_deleted_orders(admin_client, company):
    kz, usd = seed(company)
    with tenant_context(company.id):
        kz.status = HandbookValue.objects.get(handbook__code="order_status", code="cancelled")
        kz.save()
        usd.delete()
    assert admin_client.get(OPS).data["count"] == 0


def test_accounting_start_respected(admin_client, company):
    seed(company)
    Company.objects.filter(pk=company.pk).update(accounting_start=date(2026, 5, 6))
    assert admin_client.get(OPS).data["count"] == 1


def test_bad_params_are_400(admin_client):
    assert admin_client.get(OPS + "?date_from=zzz").status_code == 400
    assert admin_client.get(OPS + "?client=abc").status_code == 400


def test_export_strips_control_chars_and_formulas(admin_client, company):
    order = make_order(company)
    add_line(company, order, income=5, title="a\x0bb\x1fc", category="=cmd")
    r = admin_client.get(OPS + "export/")
    assert r.status_code == 200
    assert r["Content-Type"].startswith("application/vnd.openxmlformats")
    wb = load_workbook(io.BytesIO(r.content))
    rows = list(wb.active.iter_rows(values_only=True))
    assert rows[0][0] == "Дата"
    assert "abc" in [c for row in rows[1:] for c in row]
    assert "'=cmd" in [c for row in rows[1:] for c in row]


def test_export_requires_view(company):
    from apps.forwarding.tests.test_parties import client_with_role

    _, api = client_with_role(company, "Механик")
    assert api.get(OPS).status_code == 403
    assert api.get(OPS + "export/").status_code == 403


def test_isolation_between_companies(make_company, company, admin_client):
    seed(company)
    _, _, other = make_company("Other")
    assert other.get(OPS).data["count"] == 0
    assert len(load_workbook(io.BytesIO(other.get(OPS + "export/").content)).active["A"]) == 1


def test_query_count_stable(admin_client, company, django_assert_max_num_queries):
    order = make_order(company, client=make_client(company))
    for i in range(20):
        add_line(company, order, income=i)
    with django_assert_max_num_queries(12):
        assert admin_client.get(OPS + "?page_size=100").status_code == 200
