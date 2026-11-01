import pytest

from apps.core.phone import normalize_phone


@pytest.mark.parametrize(
    "raw",
    ["8 700 111 22 33", "+7(700)1112233", "7001112233", "+7 700 111-22-33", "87001112233"],
)
def test_normalize_ok(raw):
    assert normalize_phone(raw) == "+77001112233"


@pytest.mark.parametrize(
    "raw",
    [
        "12345",
        "",
        "abc",
        "+1 700 111 22 33",
        "770011122334",
        "9" * 12,
        "٧٠٠١١١٢٢٣٣",  # арабо-индийские цифры
        "+7700111223３",  # полноширинная цифра
        "+8 700 111 22 33",  # после + должна быть 7
        "+7001112233",  # после + нужны 11 цифр
        "7001112２33",
        "+7 700 111 22 33 4",
    ],
)
def test_normalize_invalid(raw):
    with pytest.raises(ValueError):
        normalize_phone(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "8\u00a0700\u00a0111\u00a022\u00a033",
        "+7\u202f700\u202f111\u202f22\u202f33",
        "+7\u2009(700)\u20091112233",
        "7\u3000700 111 22 33",
        " \u00a0+7 700 111-22-33\u00a0",
    ],
)
def test_unicode_whitespace_separators_are_stripped(raw):
    assert normalize_phone(raw) == "+77001112233"
