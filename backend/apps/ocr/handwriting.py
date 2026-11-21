"""Рукописный отчётный лист: чтение Gemini, второе независимое чтение и проверка значений.

Ответу модели не доверяем вслепую. У каждого значения могут быть причины перепроверить его:
- модель сама пометила значение сомнительным;
- ВТОРОЕ чтение (другая модель) видит другое или не видит это значение вовсе;
- не сошлось правило согласованности (литры x цена = сумма, пробег в конце меньше, чем в начале);
- запись пришлось «додумать» (выражение 60+30, нечитаемое число).
Флаги привязаны к путям прочитанного JSON ("fuel_tractor[3].liters"), так их подсвечивает экран.
Привязка к форме отчёта водителя (авансы, топливо, расходы) появится вместе с разделом
«Отчётность»: форма там настраивается, валюты берутся из справочника, а не из кода.
Перенесено из truck365 (apps/documents/handwriting.py) без привязки к его модели формы."""

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from .gemini import GeminiError, read_report_sheet

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.5-flash-lite"  # простая модель, которая отвечает стабильно
DEFAULT_CHECK_MODEL = ""  # пусто: вторая модель подбирается из доступных ключу
TEXT_KEYS = {
    "description", "note", "category", "driver", "vehicle", "country", "currency", "page_type",
}  # fmt: skip
DATE_KEYS = {"date", "start_date", "end_date"}
# Функция Vercel живёт до 60 секунд (vercel.json): бюджет делится на два этапа - основные модели
# читают параллельно, затем (если кто-то не ответил) запасные из списка в оставшееся время.
# Модель на настоящем фото листа отвечает 15-40 секунд, поэтому таймауты не меньше этих значений.
TOTAL_BUDGET = 56
FIRST_STAGE_TIMEOUT = 30


@dataclass(frozen=True)
class HandwritingConfig:
    api_key: str = ""
    model: str = DEFAULT_MODEL
    check_model: str = DEFAULT_CHECK_MODEL
    crosscheck: bool = False
    enabled: bool = True
    fallback_models: tuple[str, ...] = ()  # запасные модели при занятости или сбое основных

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.api_key)


class HandwritingError(Exception):
    """Чтение не удалось ни одной моделью. retryable - сервис занят, позже может получиться."""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


# ----------------------------------------------------------------------------- разбор значений
def parse_number(value):
    """-> (Decimal | None, было_выражением). Принимает 1 234,5 / 60+30 / '' / None."""
    if value is None or value == "" or isinstance(value, bool):
        return None, False
    if isinstance(value, int | float | Decimal):
        return Decimal(str(value)), False
    text = str(value).strip().replace(" ", "").replace(" ", "").replace(",", ".")
    text = text.replace("−", "-")
    if re.fullmatch(r"-?\d+(\.\d+)?(\+\d+(\.\d+)?)+", text):
        try:
            return sum((Decimal(p) for p in text.split("+")), Decimal("0")), True
        except InvalidOperation:
            return None, False
    try:
        return Decimal(text), False
    except InvalidOperation:
        return None, False


def fmt(number) -> str:
    return "" if number is None else format(number.normalize(), "f")


def parse_date(text, today: date | None = None) -> str:
    """'22.07' / '22.07.26' / '22.07.2026' -> ISO. Без года - ближайшая дата не из будущего."""
    today = today or date.today()
    match = re.fullmatch(r"\s*(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2}|\d{4}))?\s*", str(text or ""))
    if not match:
        return ""
    day, month = int(match.group(1)), int(match.group(2))
    year_text = match.group(3)
    try:
        if year_text:
            year = int(year_text) + (2000 if len(year_text) == 2 else 0)
            return date(year, month, day).isoformat()
        candidate = date(today.year, month, day)
        if candidate > today + timedelta(days=7):
            candidate = date(today.year - 1, month, day)
        return candidate.isoformat()
    except ValueError:
        return ""


# ---------------------------------------------------------------- проверки одного чтения
def _leaves(node, path=""):
    """(путь, сравнимое значение) для каждого числа и даты. Свободный текст не сравниваем:
    два чтения по-разному записывают одно и то же рукописное слово."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key != "uncertain":
                yield from _leaves(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _leaves(value, f"{path}[{i}]")
    else:
        key = re.split(r"[.\[]", path)[-1]
        if key in DATE_KEYS:
            iso = parse_date(node, date(2000, 12, 31))
            if iso:
                yield path, iso[8:10] + "." + iso[5:7]
        elif key not in TEXT_KEYS:
            number, _ = parse_number(node)
            if number is not None:
                yield path, number


def _section(path: str) -> str:
    return re.match(r"(expenses\.[A-Z]{3}|[a-z_]+)", path).group(1)


def _row(path: str) -> str | None:
    match = re.search(r"\[(\d+)\]", path)
    return match.group(1) if match else None


def _same(x, y) -> bool:
    if isinstance(x, Decimal) and isinstance(y, Decimal):
        return abs(x - y) <= Decimal("0.005")
    return x == y


def _show(value) -> str:
    return fmt(value) if isinstance(value, Decimal) else str(value)


def compare_readings(first: dict, second: dict) -> dict:
    """Где два независимых чтения расходятся.

    Разделы с одинаковым числом строк сравниваются построчно (alt - что увидело другое чтение).
    Если число строк разное, разделы сравниваются как наборы значений, чтобы одна пропущенная
    строка не делала неверной каждую клетку (missing - значение, которого другое чтение не
    увидело). Одиночные значения (шапка, остатки денег) сравниваются напрямую."""
    a, b = dict(_leaves(first)), dict(_leaves(second))
    alt, missing, notes = {}, [], []

    def rows(leaves):
        by_section: dict[str, dict[str, list[str]]] = {}
        for path in leaves:
            row = _row(path)
            if row is not None:
                by_section.setdefault(_section(path), {}).setdefault(row, []).append(path)
        return by_section

    a_rows, b_rows = rows(a), rows(b)
    for section, a_by_row in a_rows.items():
        b_by_row = b_rows.get(section, {})
        if len(a_by_row) == len(b_by_row):
            for paths in a_by_row.values():
                for path in paths:
                    if path not in b:
                        missing.append(path)
                    elif not _same(a[path], b[path]):
                        alt[path] = _show(b[path])
        else:
            notes.append(
                f"Второе чтение нашло в разделе «{section}» {len(b_by_row)} строк вместо "
                f"{len(a_by_row)} - сверьте строки с фото"
            )
            pool = [b[p] for paths in b_by_row.values() for p in paths]
            for paths in a_by_row.values():
                for path in paths:
                    match = next((v for v in pool if _same(v, a[path])), None)
                    if match is None:
                        missing.append(path)
                    else:
                        pool.remove(match)
    for path, value in a.items():
        if _row(path) is not None:
            continue
        if path not in b:
            missing.append(path)
        elif not _same(value, b[path]):
            alt[path] = _show(b[path])
    return {"alt": alt, "missing": missing, "notes": notes}


def check_values(raw: dict) -> dict[str, list[str]]:
    """Флаги по путям: выражения, нечитаемые числа, литры x цена != сумма, пробег."""
    flags: dict[str, list[str]] = {}

    def flag(path, reason):
        reasons = flags.setdefault(path, [])
        if reason not in reasons:
            reasons.append(reason)

    for path, value in _walk_numbers(raw):
        number, _ = parse_number(value)
        if number is None:
            flag(path, f"Не удалось прочитать «{value}» как число")
        # запись-сумма вроде «2000+200» в листах обычное дело: сомнением не считается
    for key in ("fuel_tractor", "fuel_reefer"):
        for i, row in enumerate(raw.get(key) or []):
            if not isinstance(row, dict):
                continue
            liters = parse_number(row.get("liters"))[0]
            price = parse_number(row.get("price"))[0]
            amount = parse_number(row.get("amount"))[0]
            if liters is not None and price is not None and amount is not None:
                expected = liters * price
                if abs(expected - amount) > max(Decimal("1"), amount * Decimal("0.02")):
                    reason = (
                        f"Литры x цена = {fmt(expected.quantize(Decimal('0.01')))}, "
                        f"а сумма {fmt(amount)}"
                    )
                    for field in ("liters", "amount"):
                        flag(f"{key}[{i}].{field}", reason)
    header = raw.get("header") or {}
    start = parse_number(header.get("start_odometer_km"))[0]
    end = parse_number(header.get("end_odometer_km"))[0]
    if start is not None and end is not None:
        if end < start:
            for field in ("start_odometer_km", "end_odometer_km"):
                flag(f"header.{field}", "Пробег в конце меньше, чем в начале")
        elif end - start > 40000:
            flag("header.end_odometer_km", f"За рейс {fmt(end - start)} км - проверьте цифры")
    return flags


def _walk_numbers(node, path=""):
    """(путь, значение) для непустых числовых клеток (ключи не из текстовых и не даты)."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key != "uncertain":
                yield from _walk_numbers(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk_numbers(value, f"{path}[{i}]")
    elif node not in (None, ""):
        key = re.split(r"[.\[]", path)[-1]
        if key not in TEXT_KEYS and key not in DATE_KEYS:
            yield path, node


def build_page(raw: dict, cross: dict | None, notes: list[str], models: list[str]) -> dict:
    """Итог чтения одной страницы: исходное чтение, флаги, расхождения, пояснения."""
    flags = check_values(raw)

    def flag(path, reason):
        reasons = flags.setdefault(path, [])
        if reason not in reasons:
            reasons.append(reason)

    for path in raw.get("uncertain") or []:
        flag(str(path).strip().replace(" ", ""), "Нейросеть не уверена в этом значении")
    alt = {}
    for path, other in (cross or {}).get("alt", {}).items():
        flag(path, f"Второе чтение видит другое: {other}")
        alt[path] = other
    for path in (cross or {}).get("missing", []):
        flag(path, "Второе чтение не подтвердило это значение")
    return {
        "page_type": raw.get("page_type") or "other",
        "raw": {k: v for k, v in raw.items() if k != "uncertain"},
        "flags": flags,
        "alt": alt,
        "notes": [*notes, *(cross or {}).get("notes", [])],
        "models": models,
    }


# ----------------------------------------------------------------------------- оркестрация
# Модели, которые только что подвели, временно исключаются из запасных (на процесс): 429 - квота
# ключа на эту модель (надолго), 503 и таймаут - перегрузка (ненадолго). Свежий список доступных
# моделей получается заново, поэтому отдохнувшая модель вернётся сама.
_COOLDOWN: dict[str, float] = {}
QUOTA_COOLDOWN = 30 * 60
BUSY_COOLDOWN = 3 * 60


def _cool_down(name: str, exc: GeminiError) -> None:
    seconds = QUOTA_COOLDOWN if exc.status == 429 else BUSY_COOLDOWN
    _COOLDOWN[name] = time.monotonic() + seconds


def _cooling(name: str) -> bool:
    until = _COOLDOWN.get(name)
    return until is not None and until > time.monotonic()


def _run_models(data, content_type, names, api_key, timeout):
    """Читает фото перечисленными моделями параллельно: [(имя, чтение | None, ошибка | None)]."""

    def run(name):
        try:
            return name, read_report_sheet(data, content_type, name, api_key, timeout=timeout), None
        except GeminiError as exc:
            _cool_down(name, exc)
            return name, None, exc

    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        return list(pool.map(run, names))


def read_sheet(data: bytes, content_type: str, config: HandwritingConfig) -> dict:
    """Фото листа читают основная модель и, если нужно, вторая (параллельно). Если кто-то не
    ответил (занят, таймаут, модель недоступна), его место занимают запасные модели из списка
    в оставшееся время функции. Страница сообщает, какие модели реально читали и была ли
    пересверка."""
    started = time.monotonic()
    wanted = [config.model]
    if config.crosscheck:
        check = config.check_model or next(
            (m for m in config.fallback_models if m != config.model and not _cooling(m)), ""
        )
        if check and check != config.model:
            wanted.append(check)
    first_timeout = FIRST_STAGE_TIMEOUT if config.fallback_models else TOTAL_BUDGET - 4
    outcomes = _run_models(data, content_type, wanted, config.api_key, first_timeout)
    errors = [err for _, _, err in outcomes if err is not None]
    good = [(name, raw) for name, raw, _ in outcomes if raw is not None]
    notes: list[str] = []
    spare = [m for m in config.fallback_models if m not in wanted and not _cooling(m)]
    left = TOTAL_BUDGET - (time.monotonic() - started)
    if len(good) < len(wanted) and spare and left >= 8:
        need = len(wanted) - len(good)
        tried = spare[: need + 4]  # с запасом и параллельно: часть запасных тоже занята
        extra = _run_models(data, content_type, tried, config.api_key, int(left))
        errors += [err for _, _, err in extra if err is not None]
        good += [(name, raw) for name, raw, _ in extra if raw is not None][:need]
    if not good:
        err = errors[0] if errors else None
        raise HandwritingError(
            str(err) if err else "Gemini не ответил.",
            retryable=bool(getattr(err, "retryable", True)),
        )
    first, models = good[0][1], [name for name, _ in good]
    if good[0][0] != config.model:
        notes.append(
            f"Основная модель недоступна - читала «{good[0][0]}»"
            + ("" if len(good) > 1 else ", без пересверки")
            + "."
        )
    if len(wanted) > 1 and len(good) < 2:
        if good[0][0] == config.model:
            notes.append(
                "Второе чтение недоступно - пересверка не выполнена, проверьте цифры особенно "
                "внимательно."
            )
    elif len(good) > 1 and good[1][0] != config.check_model:
        notes.append(f"Модель пересверки недоступна - пересверила «{good[1][0]}».")
    other = good[1][1] if len(good) > 1 else None
    cross = compare_readings(first, other) if other is not None else None
    page = build_page(first, cross, notes, models)
    page["raw_check"] = other  # для настройки промпта: что именно сказала каждая модель
    return page
