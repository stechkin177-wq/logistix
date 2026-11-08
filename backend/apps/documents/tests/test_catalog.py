import pytest

from apps.documents.catalog import KINDS, context_keys, placeholders, sample_context


@pytest.mark.parametrize("kind", sorted(KINDS))
@pytest.mark.parametrize("language", ["ru", "kk"])
def test_catalog_names_match_sample_context(kind, language):
    names = [p["name"] for p in placeholders(kind)]
    assert len(names) == len(set(names))
    assert set(names) == context_keys(sample_context(kind, language))


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_sample_context_lists_nonempty(kind):
    ctx = sample_context(kind)

    def walk(value):
        if isinstance(value, list):
            assert len(value) == 2
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        else:
            assert value != ""

    walk(ctx)


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        placeholders("nope")
    with pytest.raises(ValueError):
        sample_context("nope")


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_every_description_nonempty(kind):
    for p in placeholders(kind):
        assert p["description"].strip()
        assert "\n" not in p["description"]


def test_context_keys_format():
    keys = context_keys({"a": {"b": 1}, "l": [{"x": 1}, {"x": 2}]})
    assert keys == {"a.b", "l[].x"}


def test_kind_membership():
    names = {p["name"] for p in placeholders("carrier_order")}
    assert "carrier.name" in names and "trip.consignments[].load.city" in names
    assert not any(n.startswith("client.") for n in names)
    assert "doc.number" in names and "company.iban" in names
    assert "order.consignments[].load.city" in {p["name"] for p in placeholders("order_request")}


def _expand(prefix, leaves):
    return {f"{prefix}.{leaf}" for leaf in leaves}


_POINT = ["city", "address", "date"]
_PARTY = [
    "name",
    "bin_iin",
    "type",
    "address",
    "bank",
    "iban",
    "contact.name",
    "contact.position",
    "contact.phone",
    "contact.email",
]
_CARGO = ["name", "weight_kg", "volume_m3", "pallets"]
_STOP = ["n", "kind", "kind_name", "city", "address", "date", "date_to"]

_EXPECTED_BLOCKS = {
    "doc": _expand("doc", ["number", "date", "date_long"]),
    "company": _expand("company", ["name", "bin", "address", "bank", "iban"]),
    "client": _expand("client", _PARTY),
    "carrier": _expand("carrier", _PARTY),
    "order": _expand(
        "order",
        ["number", "date", "contract_number", "client_ref", "rate", "rate_words"]
        + ["currency", "payment_delay_days", "comment", "manager"]
        + [f"consignments[].{x}" for x in _CARGO]
        + [f"consignments[].load.{x}" for x in _POINT]
        + [f"consignments[].unload.{x}" for x in _POINT]
        + [f"consignments[].stops[].{x}" for x in _STOP]
        + [f"stops[].{x}" for x in _STOP],
    ),
    "trip": _expand(
        "trip",
        ["number", "price", "price_words", "carrier_price", "carrier_price_words"]
        + ["currency", "vehicle_plate", "driver_name"]
        + [f"loading.{x}" for x in _POINT]
        + [f"delivery.{x}" for x in _POINT]
        + ["orders[].number", "orders[].client"]
        + [f"consignments[].{x}" for x in _CARGO + ["order"]]
        + [f"consignments[].load.{x}" for x in _POINT]
        + [f"consignments[].unload.{x}" for x in _POINT]
        + [f"consignments[].stops[].{x}" for x in _STOP]
        + [f"stops[].{x}" for x in _STOP],
    ),
    "invoice": _expand(
        "invoice",
        ["number", "date", "due_date", "currency", "vat_rate"]
        + ["items[].n", "items[].title", "items[].amount_net"]
        + ["net", "vat", "gross", "gross_words"],
    ),
    "letter": _expand("letter", ["recipient", "subject", "body"]),
}

_EXPECTED_KIND_BLOCKS = {
    "contract": ["doc", "company", "client"],
    "order_request": ["doc", "company", "client", "order"],
    "carrier_order": ["doc", "company", "carrier", "trip"],
    "act": ["doc", "company", "client", "invoice", "order"],
    "invoice_print": ["doc", "company", "client", "invoice", "order"],
    "cmr": ["doc", "company", "carrier", "trip"],
    "letter": ["doc", "company", "letter"],
}


def test_expected_kinds_cover_all_kinds():
    assert set(_EXPECTED_KIND_BLOCKS) == set(KINDS)


@pytest.mark.parametrize("kind", sorted(_EXPECTED_KIND_BLOCKS))
def test_placeholder_names_equal_spec(kind):
    expected = set().union(*(_EXPECTED_BLOCKS[b] for b in _EXPECTED_KIND_BLOCKS[kind]))
    assert {p["name"] for p in placeholders(kind)} == expected
