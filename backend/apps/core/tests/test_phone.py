import pytest

from apps.core.phone import normalize_phone


@pytest.mark.parametrize(
    "raw",
    ["8 700 111 22 33", "+7(700)1112233", "7001112233", "+7 700 111-22-33", "87001112233"],
)
def test_normalize_ok(raw):
    assert normalize_phone(raw) == "+77001112233"


@pytest.mark.parametrize("raw", ["12345", "", "abc", "+1 700 111 22 33", "770011122334", "9" * 12])
def test_normalize_invalid(raw):
    with pytest.raises(ValueError):
        normalize_phone(raw)
