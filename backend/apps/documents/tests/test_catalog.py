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
