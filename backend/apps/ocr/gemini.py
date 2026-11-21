# ruff: noqa: E501 - промпт для модели: длинные строки текста читаются лучше переносов
"""Клиент Google Gemini (vision) для рукописного отчётного листа, без сторонних библиотек.

Обычное распознавание рассчитано на печатный текст и плохо читает рукописные цифры в клетках
таблицы. Модель с «зрением» читает лист как человек и возвращает значения в виде JSON.
Промпт описывает бланк по СМЫСЛУ разделов, а не по положению, поэтому слегка изменённый бланк
продолжает читаться. Ключ идёт в заголовке и в тексты ошибок не попадает.
Перенесено из truck365 (apps/documents/gemini.py)."""

import base64
import json
import logging
import re
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

REPORT_SHEET_PROMPT = """Это фото бумажного «Отчётного листа рейса» дальнобойщика. Лист заполнен ОТ РУКИ на печатном бланке.
Лист может состоять из нескольких страниц-бланков; на фото — одна из них. Название и расположение разделов могут немного
отличаться — ориентируйся на СМЫСЛ разделов, а не на положение.

Верни ТОЛЬКО JSON, без пояснений. Переписывай именно то, что написано рукой. Ничего не додумывай, не вычисляй, не исправляй.
Пустые клетки — null. Числа: десятичная запятая -> точка, пробелы внутри числа убирай (50 000 -> 50000).
Если в клетке написано выражение вроде 60+30 — верни его как строку "60+30". Даты — как написано (ДД.ММ или ДД.ММ.ГГ).
Цифры читай особенно внимательно (путаются 3/5, 7/4, 1/7, 0/6, 2/8, 4/9): если сомневаешься в цифре — всё равно верни своё
лучшее прочтение, но добавь путь к этому значению в "uncertain".

Определи тип страницы "page_type":
- "main" — главный лист: шапка (фамилия, даты, пробег, остаток топлива), полученные деньги, остаток денег, переводы,
  ЗАПРАВКИ (тягач и рефрижератор), основные расходы по странам, затраты на авто, техобслуживание и ремонт;
- "expenses" — лист «Расходы в рейсе»: четыре колонки-валюты (ТЕНГЕ, РУБЛИ, ЮАНИ, ЕВРО), в каждой строки «сумма + описание»;
- "other" — что-то иное.

Формат (включай только то, что относится к этой странице):
{
 "page_type": "main" | "expenses" | "other",
 "header": {"driver": str, "start_date": str, "start_odometer_km": num, "end_date": str, "end_odometer_km": num,
            "remaining_fuel_tractor_l": num, "remaining_fuel_reefer_l": num, "reefer_engine_hours": num},
 "cash_received": {"KZT": num, "RUB": num, "CNY": num, "EUR": num},
 "cash_remaining": {"KZT": num, "RUB": num, "CNY": num, "EUR": num},
 "transfers": [{"date": str, "amount": num, "currency": "KZT|RUB|CNY|EUR|BYN|USD", "description": str}],
 "fuel_tractor": [{"date": str, "liters": num, "price": num, "amount": num, "currency": str, "note": str}],
 "fuel_reefer":  [{"date": str, "liters": num, "price": num, "amount": num, "currency": str, "note": str}],
 "main_expenses": [{"category": str, "country": "KZ|RU|CN|EU", "count": num, "amount": num-or-str}],
 "car_costs": [{"date": str, "description": str, "amount": num, "currency": str}],
 "maintenance": [{"date": str, "vehicle": str, "odometer_km": num, "description": str, "cost": num, "currency": str}],
 "expenses": {"KZT": [{"amount": num, "description": str}], "RUB": [], "CNY": [], "EUR": []},
 "uncertain": [str]
}
Правила:
- Каждая рукописная строка таблицы «ЗАПРАВКИ» — один элемент (даже если заполнены только литры). Заправки тягача и
  рефрижератора — в разных списках. "currency" заправки заполняй только если она ЯВНО написана (например «руб.», «бел.руб»),
  иначе null. В "note" — приписки рядом со строкой (название АЗС, город).
- "main_expenses": каждая непустая клетка таблицы основных расходов (командировочные, стоянки, душ/стирка, платные дороги,
  транспортники, ГАИ/штрафы, прочее) — отдельный элемент: "category" как напечатано (для «прочее» добавь то, что написано рукой),
  "country" по колонке, "count" — число в колонке «кол-во», "amount" — сумма.
- "uncertain": пути к сомнительным значениям в этом же JSON, например "transfers[2].amount", "fuel_tractor[4].liters",
  "expenses.RUB[1].amount", "header.end_odometer_km"."""


class GeminiError(Exception):
    """Текст безопасно показывать пользователю. retryable - есть смысл повторить или взять другую модель."""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def _scrub(text: str, api_key: str) -> str:
    return text.replace(api_key, "***") if api_key else text


def _post(model: str, api_key: str, body: dict, timeout: int) -> dict:
    request = urllib.request.Request(  # noqa: S310 - https, фиксированный адрес
        f"{API_ROOT}/{model}:generateContent",
        data=json.dumps(body).encode(),
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        message = ""
        try:
            error = json.loads(exc.read().decode("utf-8")).get("error") or {}
            message = str(error.get("message", ""))
        except (ValueError, OSError, AttributeError):
            pass
        message = _scrub(message, api_key)[:200]
        if exc.code == 404:
            message = f"модель «{model}» недоступна: {message}"
        raise GeminiError(
            f"Gemini вернул {exc.code}: {message}", retryable=exc.code in RETRYABLE_STATUS
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GeminiError(f"Gemini недоступен: {type(exc).__name__}", retryable=True) from None
    except ValueError:
        raise GeminiError("Gemini вернул не JSON.", retryable=True) from None


def _extract_json(payload: dict) -> dict:
    try:
        parts = payload["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError, TypeError):
        reason = (payload.get("promptFeedback") or {}).get("blockReason") or "пустой ответ"
        raise GeminiError(f"Gemini не вернул результат ({reason}).", retryable=True) from None
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    try:
        data = json.loads(text)
    except ValueError:
        raise GeminiError("Gemini вернул ответ не в формате JSON.", retryable=True) from None
    if not isinstance(data, dict):
        raise GeminiError("Gemini вернул неожиданную структуру.", retryable=True)
    return data


def generate_json(
    model: str, api_key: str, parts: list, *, timeout: int = 40, retries: int = 0
) -> dict:
    """Один JSON-ответ модели; занятый сервис (503, 429) повторяется retries раз, остальное сразу."""
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    attempt = 0
    while True:
        try:
            return _extract_json(_post(model, api_key, body, timeout))
        except GeminiError as exc:
            if not exc.retryable or attempt >= retries:
                raise
            attempt += 1
            logger.warning("Gemini %s занят (%s), повтор %s/%s", model, exc, attempt, retries)
            time.sleep(2 * attempt)


def _image(data: bytes, content_type: str) -> dict:
    return {
        "inline_data": {"mime_type": content_type, "data": base64.b64encode(data).decode("ascii")}
    }


def read_report_sheet(
    data: bytes, content_type: str, model: str, api_key: str, *, timeout: int = 40, retries: int = 0
) -> dict:
    if not api_key:
        raise GeminiError("Не задан ключ Gemini.")
    return generate_json(
        model, api_key, [{"text": REPORT_SHEET_PROMPT}, _image(data, content_type)],
        timeout=timeout, retries=retries,
    )  # fmt: skip


def check_key(model: str, api_key: str, data: bytes, content_type: str) -> str:
    """Читает тестовую картинку: доказывает, что работают ключ, модель и приём изображений."""
    if not api_key:
        raise GeminiError("Не задан ключ Gemini.")
    prompt = 'Что написано на картинке? Верни JSON вида {"text": "..."} - только текст с картинки.'
    reply = generate_json(
        model, api_key, [{"text": prompt}, _image(data, content_type)], timeout=25
    )
    return str(reply.get("text", ""))


_SKIP = (
    "embedding",
    "tts",
    "transcribe",
    "image",
    "live",
    "audio",
    "robotics",
    "aqa",
    "learnlm",
    "veo",
    "imagen",
)


def _version_key(name: str) -> tuple:
    nums = re.findall(r"\d+(?:\.\d+)?", name)
    return (float(nums[0]) if nums else 0.0, name)


def list_models(api_key: str, timeout: int = 20) -> list[str]:
    """Модели Gemini, доступные этому ключу и умеющие читать картинки (generateContent), от новых
    к старым. Без служебных (эмбеддинги, речь, изображения, live) и без «preview»/«exp»."""
    if not api_key:
        raise GeminiError("Не задан ключ Gemini.")
    request = urllib.request.Request(  # noqa: S310 - https, фиксированный адрес
        f"{API_ROOT}?pageSize=200", headers={"x-goog-api-key": api_key}, method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise GeminiError(f"Gemini вернул {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise GeminiError(f"Gemini недоступен: {type(exc).__name__}") from None
    names = []
    for item in payload.get("models") or []:
        name = str(item.get("name", "")).removeprefix("models/")
        methods = item.get("supportedGenerationMethods") or []
        if (
            name.startswith("gemini")
            and "generateContent" in methods
            and not any(word in name for word in _SKIP)
            and "preview" not in name
            and "exp" not in name
        ):
            names.append(name)
    return sorted(set(names), key=_version_key, reverse=True)
