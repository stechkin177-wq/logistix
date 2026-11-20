"""Разбор распознанного текста: поля чека АЗС и общие поля (дата, сумма).

Правила прозрачные и проверяемые; ненайденное просто отсутствует - человек поправит в карточке.
Значения: date - ГГГГ-ММ-ДД, суммы и литры - строки с точкой."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

DATE_RE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})\b")
NUM = r"(\d{1,3}(?:[  ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,3})?)"
TOTAL_RE = re.compile(rf"(?:итого|к\s*оплате|сумма|всего|total)\D{{0,25}}?{NUM}", re.IGNORECASE)
LITERS_RE = re.compile(
    rf"(?:{NUM}\s*(?:л\b|литр|l\b|ltr)|(?:объ[её]м|количество|кол-во|литры|volume)\D{{0,12}}?{NUM})",
    re.IGNORECASE,
)
PRICE_RE = re.compile(rf"(?:цена|price)\D{{0,20}}?{NUM}", re.IGNORECASE)
# Госномер РК: 123ABC01 (латиница; похожие кириллические буквы приводятся к латинице)
PLATE_RE = re.compile(r"\b(\d{3})\s*([A-ZА-Я]{2,3})\s*(\d{2})\b", re.IGNORECASE)
CYR_TO_LAT = str.maketrans("АВЕКМНОРСТУХ", "ABEKMHOPCTYX")
FUELS = (
    ("diesel", re.compile(r"\b(?:дт|дизел\w*|diesel|d[tт]\b)", re.IGNORECASE)),
    ("ai98", re.compile(r"(?:аи|ai)[- ]?98", re.IGNORECASE)),
    ("ai95", re.compile(r"(?:аи|ai)[- ]?95", re.IGNORECASE)),
    ("ai92", re.compile(r"(?:аи|ai)[- ]?92", re.IGNORECASE)),
    ("ai80", re.compile(r"(?:аи|ai)[- ]?80", re.IGNORECASE)),
    ("gas", re.compile(r"\b(?:газ|пропан|lpg|сжиженный)\b", re.IGNORECASE)),
)


def to_decimal(raw: str) -> Decimal | None:
    text = re.sub(r"[  ]", "", raw or "").replace(",", ".")
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value >= 0 else None


def fmt(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")) if value.as_tuple().exponent < -2 else value, "f")


def parse_date(text: str, today: date | None = None) -> str | None:
    """Первая правдоподобная дата: не из будущего дальше суток и не старше пяти лет."""
    today = today or date.today()
    for d, m, y in DATE_RE.findall(text):
        year = int(y) + (2000 if len(y) == 2 else 0)
        try:
            found = date(year, int(m), int(d))
        except ValueError:
            continue
        if (found - today).days <= 1 and (today - found).days <= 5 * 366:
            return found.isoformat()
    return None


def _first_decimal(pattern, text) -> Decimal | None:
    for match in pattern.finditer(text):
        raw = next((g for g in match.groups() if g), "")
        value = to_decimal(raw)
        if value is not None and value > 0:
            return value
    return None


def parse_plate(text: str) -> str | None:
    for digits, letters, region in PLATE_RE.findall(text):
        lat = letters.upper().translate(CYR_TO_LAT)
        if re.fullmatch(r"[A-Z]{2,3}", lat):
            return f"{digits}{lat}{region}"
    return None


def parse_fuel_type(text: str) -> str | None:
    for code, pattern in FUELS:
        if pattern.search(text):
            return code
    return None


def parse_fields(text: str, doc_type: str = "other", today: date | None = None) -> dict:
    """Поля документа. Для чека АЗС: дата, сумма, литры, цена за литр, вид топлива, госномер;
    для остальных типов: дата и сумма. Если сумма не найдена по ключевым словам, берётся
    самая большая."""
    fields: dict[str, str] = {}
    if found := parse_date(text, today):
        fields["date"] = found
    total = _first_decimal(TOTAL_RE, text)
    if total is None:
        numbers = [to_decimal(n) for n in re.findall(NUM, text)]
        numbers = [n for n in numbers if n is not None and n >= 1]
        total = max(numbers) if numbers else None
    if total is not None:
        fields["amount"] = fmt(total)
    if doc_type == "fuel_receipt":
        liters = _first_decimal(LITERS_RE, text)
        price = _first_decimal(PRICE_RE, text)
        if liters is not None:
            fields["liters"] = fmt(liters)
        if price is not None:
            fields["price_per_liter"] = fmt(price)
        if liters is not None and price is None and total is not None and liters > 0:
            fields["price_per_liter"] = fmt((total / liters).quantize(Decimal("0.01")))
        if fuel := parse_fuel_type(text):
            fields["fuel_type"] = fuel
        if plate := parse_plate(text):
            fields["plate"] = plate
    return fields
