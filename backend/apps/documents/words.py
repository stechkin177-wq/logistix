"""Сумма прописью и дата словами для печатных документов (чистые функции)."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from num2words import num2words

MAX_AMOUNT = Decimal(10**15)

# num2words использует «kz» для казахского; наружу язык называется «kk».
_N2W_LANG = {"ru": "ru", "kk": "kz"}
_MINUS = {"ru": "минус", "kk": "минус"}

# Для ru: (1, 2-4, 5+) для целой и дробной единицы. «тенге», «тиын», «евро» не склоняются.
# Для kk названия после числительного не изменяются.
_CURRENCIES = {
    "KZT": {
        "ru": (("тенге",) * 3, ("тиын",) * 3),
        "kk": (("теңге",) * 3, ("тиын",) * 3),
    },
    "RUB": {
        "ru": (("рубль", "рубля", "рублей"), ("копейка", "копейки", "копеек")),
        "kk": (("рубль",) * 3, ("тиын",) * 3),
    },
    "USD": {
        "ru": (("доллар", "доллара", "долларов"), ("цент", "цента", "центов")),
        "kk": (("доллар",) * 3, ("цент",) * 3),
    },
    "EUR": {
        "ru": (("евро",) * 3, ("цент", "цента", "центов")),
        "kk": (("еуро",) * 3, ("цент",) * 3),
    },
}

_MONTHS = {
    "ru": (
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ),
    "kk": (
        "қаңтар",
        "ақпан",
        "наурыз",
        "сәуір",
        "мамыр",
        "маусым",
        "шілде",
        "тамыз",
        "қыркүйек",
        "қазан",
        "қараша",
        "желтоқсан",
    ),
}


def _check_language(language: str) -> None:
    if language not in _N2W_LANG:
        raise ValueError(f"Неподдерживаемый язык: {language}")


def _plural_index(n: int) -> int:
    """Индекс формы по правилам русского языка: 0 - один, 1 - два-четыре, 2 - остальные."""
    if 11 <= n % 100 <= 14:
        return 2
    last = n % 10
    if last == 1:
        return 0
    if 2 <= last <= 4:
        return 1
    return 2


def amount_in_words(amount: Decimal, currency_code: str, language: str) -> str:
    """«1160.50», KZT, ru -> «одна тысяча сто шестьдесят тенге 50 тиын».

    Дробная часть округляется ROUND_HALF_UP до двух знаков и пишется цифрами.
    Для неизвестной валюты вместо названия подставляется сам код, дробная часть
    без названия единицы. Модуль суммы больше 10**15 - ValueError.
    """
    _check_language(language)
    try:
        amount = Decimal(amount)
    except (ArithmeticError, TypeError, ValueError):
        raise ValueError("Сумма должна быть числом") from None
    if not amount.is_finite():
        raise ValueError("Сумма должна быть конечным числом")
    if abs(amount) > MAX_AMOUNT:
        raise ValueError("Сумма слишком велика для записи прописью")
    negative = amount < 0
    cents_total = int((abs(amount) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    whole, cents = divmod(cents_total, 100)

    words = num2words(whole, lang=_N2W_LANG[language])
    forms = _CURRENCIES.get(currency_code.upper() if currency_code else "")
    if forms:
        major, minor = forms[language]
        ru = language == "ru"
        major_form = major[_plural_index(whole) if ru else 0]
        minor_form = minor[_plural_index(cents) if ru else 0]
        text = f"{words} {major_form} {cents:02d} {minor_form}"
    else:
        text = f"{words} {currency_code} {cents:02d}"
    return f"{_MINUS[language]} {text}" if negative and cents_total else text


def date_long(day: date, language: str) -> str:
    """«1 ноября 2026 г.» (ru) / «2026 жылғы 1 қараша» (kk)."""
    _check_language(language)
    month = _MONTHS[language][day.month - 1]
    if language == "ru":
        return f"{day.day} {month} {day.year} г."
    return f"{day.year} жылғы {day.day} {month}"
