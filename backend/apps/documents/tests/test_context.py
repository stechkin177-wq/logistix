"""Контекст подстановки: ключи совпадают с каталогом меток, значения - JSON-примитивы."""

import json
from datetime import date, datetime
from datetime import timezone as dt_tz

import pytest

from apps.core.models import LegalEntity
from apps.core.tenancy import tenant_context
from apps.documents.catalog import KINDS, context_keys, placeholders
from apps.documents.context import build_context
from apps.finance.tests.helpers import cur, issue_invoice, make_carrier, make_client
from apps.forwarding.models import Contact
from apps.forwarding.tests.test_orders import _svc_cargo
from apps.forwarding.tests.test_orders import make_order as _make_order
from apps.forwarding.tests.test_trips import svc_create

pytestmark = pytest.mark.django_db


def make_order(company, client, **extra):
    return _make_order(company, client, currency=cur(company), **extra)


DAY = date(2026, 11, 1)
WHEN = datetime(2026, 6, 2, 9, 0, tzinfo=dt_tz.utc)


def _cargo(name="Мука", load="Шымкент", unload="Алматы", **extra):
    return _svc_cargo(
        name=name,
        weight_kg="20000.00",
        volume_m3="82",
        pallets=33,
        points=[
            {"kind": "load", "window_from": WHEN, "city": load, "street": "ул. Складская, 5"},
            {"kind": "unload", "window_from": WHEN, "city": unload},
        ],
        **extra,
    )


@pytest.fixture
def full(company):
    """Полный набор объектов: клиент с контактом и реквизитами, перевозчик, заказ, рейс, счёт."""
    client = make_client(company, "ТОО Клиент", bin_iin="123456789012", address="Алматы", bank="Б")
    carrier = make_carrier(company, "ИП Перевозчик", iban="KZ1")
    with tenant_context(company.id):
        Contact.objects.create(client=client, name="Иванов", position="Директор", phone="+7701")
        Contact.objects.create(client=client, name="Второй")
        Contact.objects.create(carrier=carrier, name="Сидоров")
    order = make_order(
        company,
        client,
        consignments=[_cargo(), _cargo("Сахар")],
        client_rate="1234567.89",
        client_ref="PO-1",
        comment="Холод",
    )
    trip = svc_create(
        company,
        _cargo_ids(company, order),
        carrier,
        {"vehicle_plate": "123ABC", "driver_name": "Пётр"},
    )
    invoice = issue_invoice(company, order=order, amount="1000", percent="12")
    with tenant_context(company.id):
        yield {"client": client, "order": order, "trip": trip, "invoice": invoice}


def _cargo_ids(company, order):
    from apps.forwarding.models import Consignment

    with tenant_context(company.id):
        return list(Consignment.objects.filter(order=order).values_list("pk", flat=True))


def _build(kind, objs, language="ru", **extra):
    args = {
        "client": objs["client"],
        "order": objs["order"],
        "trip": objs["trip"],
        "invoice": objs["invoice"],
        "letter": {"recipient": "ТОО", "subject": "Тема", "body": "Текст"},
        **extra,
    }
    used = {
        "contract": ("client",),
        "order_request": ("order",),
        "carrier_order": ("trip",),
        "cmr": ("trip",),
        "act": ("invoice",),
        "invoice_print": ("invoice",),
        "letter": ("letter",),
    }[kind]
    args = {k: v for k, v in args.items() if k in used}
    return build_context(kind, number="Н-1", issue_date=DAY, language=language, **args)


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_context_keys_match_catalog_for_every_kind(company, full, kind):
    ctx = _build(kind, full)
    assert context_keys(ctx) == {p["name"] for p in placeholders(kind)}


def test_order_request_values(company, full):
    ctx = _build("order_request", full)
    o = ctx["order"]
    assert ctx["doc"] == {"number": "Н-1", "date": "01.11.2026", "date_long": "1 ноября 2026 г."}
    assert o["number"] == full["order"].number
    assert o["rate"] == "1 234 567,89"
    assert o["rate_words"].startswith("один миллион двести тридцать четыре тысячи")
    assert o["rate_words"].endswith("тенге 89 тиын")
    assert o["currency"] == "KZT" and o["client_ref"] == "PO-1" and o["comment"] == "Холод"
    assert [c["name"] for c in o["consignments"]] == ["Мука", "Сахар"]
    first = o["consignments"][0]
    assert first["weight_kg"] == "20000" and first["pallets"] == "33"
    assert first["load"] == {"city": "Шымкент", "address": "ул. Складская, 5", "date": "02.06.2026"}
    assert first["unload"]["city"] == "Алматы"
    assert ctx["client"]["name"] == "ТОО Клиент"
    assert ctx["client"]["contact"]["name"] == "Иванов"
    assert ctx["client"]["contact"]["position"] == "Директор"


def test_consolidated_trip_lists_all_orders(company, full):
    other = make_order(company, full["client"], consignments=[_cargo("Рис")])
    ids = _cargo_ids(company, full["order"]) + _cargo_ids(company, other)
    trip = svc_create(company, ids, make_carrier(company, "П2"))
    ctx = build_context("carrier_order", trip=trip, number="ЗП-1", issue_date=DAY, language="ru")
    t = ctx["trip"]
    assert t["number"] == trip.number
    assert [o["number"] for o in t["orders"]] == [full["order"].number, other.number]
    assert len(t["consignments"]) == 3
    assert {c["order"] for c in t["consignments"]} == {full["order"].number, other.number}
    assert t["loading"]["city"] == "Шымкент" and t["delivery"]["city"] == "Алматы"
    assert ctx["carrier"]["name"] == "П2"


def test_act_values_from_invoice(company, full):
    ctx = _build("act", full)
    inv = ctx["invoice"]
    assert inv["number"] == full["invoice"].number
    assert [i["n"] for i in inv["items"]] == ["1"]
    assert inv["items"][0]["amount_net"] == "1 000,00"
    assert (inv["net"], inv["vat"], inv["gross"]) == ("1 000,00", "120,00", "1 120,00")
    assert inv["vat_rate"] == "12" and inv["currency"] == "KZT"
    assert inv["gross_words"] == "одна тысяча сто двадцать тенге 00 тиын"
    assert ctx["order"]["number"] == full["order"].number
    assert ctx["client"]["name"] == "ТОО Клиент"


def test_missing_data_gives_blanks(company):
    with tenant_context(company.id):
        _missing(company)


def _missing(company):
    client = make_client(company, "Пустой")
    order = make_order(company, client)
    trip_ctx = build_context("cmr", trip=None, number="CMR-1", issue_date=DAY, language="ru")
    assert trip_ctx["trip"]["orders"] == [] and trip_ctx["trip"]["driver_name"] == ""
    assert trip_ctx["carrier"]["contact"]["name"] == ""
    ctx = build_context("order_request", order=order, number="1", issue_date=DAY, language="ru")
    assert ctx["order"]["consignments"] == []
    assert ctx["client"]["bin_iin"] == "" and ctx["client"]["iban"] == ""
    assert ctx["client"]["contact"] == {"name": "", "position": "", "phone": "", "email": ""}
    letter = build_context("letter", number="1", issue_date=DAY, language="ru")
    assert letter["letter"] == {"recipient": "", "subject": "", "body": ""}
    contract = build_context("contract", client=client, number="1", issue_date=DAY, language="ru")
    assert contract["client"]["name"] == "Пустой"
    # рейс без перевозчика и водителя
    other = make_order(company, client, consignments=[_cargo()])
    trip = svc_create(company, _cargo_ids(company, other), None)
    ctx = build_context("carrier_order", trip=trip, number="1", issue_date=DAY, language="ru")
    assert ctx["carrier"]["name"] == "" and ctx["trip"]["driver_name"] == ""


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_snapshot_is_json_serializable(company, full, kind):
    ctx = _build(kind, full)
    assert json.loads(json.dumps(ctx)) == ctx


def test_kk_language_uses_kazakh_words(company, full):
    ctx = _build("act", full, language="kk")
    assert ctx["doc"]["date_long"] == "2026 жылғы 1 қараша"
    assert ctx["invoice"]["gross_words"] == "бір мың жүз жиырма теңге 00 тиын"


def test_company_entity_prefers_order_legal_entity(company, full):
    with tenant_context(company.id):
        default = LegalEntity.objects.get(is_default=True)
        special = LegalEntity.objects.create(name="ТОО Особое", bin="111", iban="KZ9")
        order = full["order"]
        order.legal_entity = special
        order.save()
        ctx = build_context("order_request", order=order, number="1", issue_date=DAY, language="ru")
        assert ctx["company"]["name"] == "ТОО Особое" and ctx["company"]["iban"] == "KZ9"
        letter = build_context("letter", number="1", issue_date=DAY, language="ru")
        assert letter["company"]["name"] == default.name
