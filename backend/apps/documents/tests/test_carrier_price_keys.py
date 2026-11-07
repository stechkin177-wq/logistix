"""Ключи trip.carrier_price / trip.carrier_price_words и совместимость со старым trip.price."""

from decimal import Decimal

import pytest

from apps.core.tenancy import tenant_context
from apps.documents import engine
from apps.documents.catalog import placeholders, sample_context
from apps.documents.context import build_context
from apps.documents.tests.test_context import DAY, _cargo, _cargo_ids
from apps.documents.tests.test_engine import docx_text, make_docx
from apps.finance.tests.helpers import cur, make_carrier, make_client
from apps.forwarding.tests.test_orders import make_order as _make_order
from apps.forwarding.tests.test_trips import svc_create

pytestmark = pytest.mark.django_db

KIND = "carrier_order"


@pytest.fixture
def trip(company):
    client = make_client(company, "ТОО Клиент")
    carrier = make_carrier(company, "ИП Перевозчик")
    order = _make_order(company, client, currency=cur(company), consignments=[_cargo()])
    with tenant_context(company.id):
        yield svc_create(
            company, _cargo_ids(company, order), carrier, {"carrier_price": Decimal("1500.50")}
        )


def _ctx(trip, language="ru"):
    return build_context(KIND, trip=trip, number="ЗП-1", issue_date=DAY, language=language)


def test_catalog_has_new_keys_and_marks_old_ones_deprecated():
    items = {p["name"]: p for p in placeholders(KIND)}
    assert "trip.carrier_price" in items and "trip.carrier_price_words" in items
    assert "устарело" in items["trip.price"]["description"]
    assert "carrier_price" in items["trip.price"]["description"]
    assert "устарело" in items["trip.price_words"]["description"]
    assert "устарело" not in items["trip.carrier_price"]["description"]


def test_context_has_old_and_new_keys_with_equal_values(trip):
    t = _ctx(trip)["trip"]
    assert t["price"] == t["carrier_price"] == "1 500,50"
    assert t["price_words"] == t["carrier_price_words"] != ""
    assert _ctx(trip, "kk")["trip"]["price"] == "1 500,50"


def test_empty_trip_context_has_new_keys(company):
    with tenant_context(company.id):
        t = build_context(KIND, trip=None, number="1", issue_date=DAY, language="ru")["trip"]
    assert t["carrier_price"] == "" and t["carrier_price_words"] == ""


def test_template_with_old_price_key_still_renders(trip):
    data = make_docx("Цена {{ trip.price }} {{ trip.currency }} ({{ trip.price_words }})")
    engine.validate_upload(data, KIND)
    out = engine.render_docx(data, _ctx(trip))
    assert "Цена 1 500,50 KZT" in docx_text(out)


def test_template_with_all_new_keys_renders(trip):
    data = make_docx("{{ trip.carrier_price }} / {{ trip.carrier_price_words }} / {{ trip.price }}")
    engine.validate_upload(data, KIND)
    text = docx_text(engine.render_docx(data, _ctx(trip)))
    assert text.startswith("1 500,50 / ") and text.endswith(" / 1 500,50")


def test_sample_context_renders_new_and_old_keys():
    data = make_docx("{{ trip.carrier_price }} {{ trip.carrier_price_words }} {{ trip.price }}")
    engine.validate_upload(data, KIND)
    assert "900000.00" in docx_text(engine.render_docx(data, sample_context(KIND)))
