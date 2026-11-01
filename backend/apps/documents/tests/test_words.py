from datetime import date
from decimal import Decimal

import pytest

from apps.documents.words import amount_in_words, date_long


@pytest.mark.parametrize(
    ("amount", "code", "lang", "expected"),
    [
        ("0", "KZT", "ru", "ноль тенге 00 тиын"),
        ("1", "KZT", "ru", "один тенге 00 тиын"),
        ("11", "KZT", "ru", "одиннадцать тенге 00 тиын"),
        ("12", "KZT", "ru", "двенадцать тенге 00 тиын"),
        ("14", "KZT", "ru", "четырнадцать тенге 00 тиын"),
        ("21", "KZT", "ru", "двадцать один тенге 00 тиын"),
        ("100", "KZT", "ru", "сто тенге 00 тиын"),
        ("1000", "KZT", "ru", "одна тысяча тенге 00 тиын"),
        ("2000", "KZT", "ru", "две тысячи тенге 00 тиын"),
        ("1000000", "KZT", "ru", "один миллион тенге 00 тиын"),
        ("0.01", "KZT", "ru", "ноль тенге 01 тиын"),
        ("1.5", "KZT", "ru", "один тенге 50 тиын"),
        ("1160.50", "KZT", "ru", "одна тысяча сто шестьдесят тенге 50 тиын"),
        ("0.005", "KZT", "ru", "ноль тенге 01 тиын"),
        ("0.994", "KZT", "ru", "ноль тенге 99 тиын"),
        ("0.999", "KZT", "ru", "один тенге 00 тиын"),
        ("1", "RUB", "ru", "один рубль 00 копеек"),
        ("2", "RUB", "ru", "два рубля 00 копеек"),
        ("5", "RUB", "ru", "пять рублей 00 копеек"),
        ("11", "RUB", "ru", "одиннадцать рублей 00 копеек"),
        ("14", "RUB", "ru", "четырнадцать рублей 00 копеек"),
        ("21", "RUB", "ru", "двадцать один рубль 00 копеек"),
        ("22", "RUB", "ru", "двадцать два рубля 00 копеек"),
        ("1001", "RUB", "ru", "одна тысяча один рубль 00 копеек"),
        ("1000", "RUB", "ru", "одна тысяча рублей 00 копеек"),
        ("3", "USD", "ru", "три доллара 00 центов"),
        ("1", "EUR", "ru", "один евро 00 центов"),
        ("7", "XXX", "ru", "семь XXX 00"),
    ],
)
def test_amount_in_words_ru(amount, code, lang, expected):
    assert amount_in_words(Decimal(amount), code, lang) == expected


def test_negative_has_minus():
    assert amount_in_words(Decimal("-5"), "KZT", "ru") == "минус пять тенге 00 тиын"


def test_too_large_raises():
    with pytest.raises(ValueError):
        amount_in_words(Decimal(10**16), "KZT", "ru")
    with pytest.raises(ValueError):
        amount_in_words(Decimal(-(10**16)), "KZT", "ru")


def test_limit_inclusive():
    assert amount_in_words(Decimal(10**15), "KZT", "ru").startswith("один квадриллион")


def test_kazakh():
    text = amount_in_words(Decimal("1234"), "KZT", "kk")
    assert "мың" in text
    assert "теңге" in text
    assert text.endswith("00 тиын")


def test_unknown_language_raises():
    with pytest.raises(ValueError):
        amount_in_words(Decimal(1), "KZT", "en")


def test_date_long():
    assert date_long(date(2026, 11, 1), "ru") == "1 ноября 2026 г."
    assert date_long(date(2026, 3, 8), "ru") == "8 марта 2026 г."
    assert date_long(date(2026, 11, 1), "kk") == "2026 жылғы 1 қараша"
    assert date_long(date(2026, 12, 31), "kk") == "2026 жылғы 31 желтоқсан"


@pytest.mark.parametrize(
    "bad",
    [
        Decimal("NaN"),
        Decimal("sNaN"),
        "NaN",
        "sNaN",
        "abc",
        "",
        None,
        Decimal("Infinity"),
        "-Infinity",
    ],
)
def test_non_numeric_or_non_finite_raises_value_error(bad):
    with pytest.raises(ValueError):
        amount_in_words(bad, "KZT", "ru")
