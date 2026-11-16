"""Официальные курсы Национального банка Казахстана (RSS get_rates.cfm).

Берём только нужные валюты: USD, EUR, RUB, CNY. Курс в ленте указан за ``quant`` единиц
(например, 10 юаней) - приводим к курсу за 1 единицу.
"""

import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal, InvalidOperation

from .errors import FinanceError

NBRK_URL = "https://nationalbank.kz/rss/get_rates.cfm?fdate={day}"
NBRK_CODES = ("USD", "EUR", "RUB", "CNY")
TIMEOUT = 10
MAX_BYTES = 1_000_000


def parse_rates(xml_bytes: bytes) -> dict[str, Decimal]:
    """Разбирает ленту НБ РК: {код: курс к тенге за 1 единицу}, только NBRK_CODES."""
    try:
        root = ET.fromstring(xml_bytes)  # noqa: S314 - небольшой ответ доверенного источника, размер ограничен
    except ET.ParseError as exc:
        raise FinanceError("nbrk_bad_response", "Нацбанк вернул непонятный ответ") from exc
    result: dict[str, Decimal] = {}
    for item in root.iter("item"):
        code = (item.findtext("title") or "").strip().upper()
        if code not in NBRK_CODES:
            continue
        try:
            value = Decimal((item.findtext("description") or "").strip().replace(",", "."))
            quant = Decimal((item.findtext("quant") or "1").strip() or "1")
        except InvalidOperation:
            continue
        if value > 0 and quant > 0:
            result[code] = (value / quant).quantize(Decimal("0.000001"))
    return result


def fetch_rates(day: date) -> dict[str, Decimal]:
    """Запрашивает курсы на дату у Нацбанка. Ошибка сети/ответа - FinanceError nbrk_unavailable."""
    url = NBRK_URL.format(day=day.strftime("%d.%m.%Y"))
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:  # noqa: S310 - https, фиксированный адрес
            body = response.read(MAX_BYTES)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FinanceError(
            "nbrk_unavailable", "Нацбанк сейчас недоступен, попробуйте позже"
        ) from exc
    rates = parse_rates(body)
    if not rates:
        raise FinanceError("nbrk_unavailable", "Нацбанк не вернул курсы на эту дату", 502)
    return rates
