"""Справочник меток шаблонов: единый источник правды.

Одна таблица данных описывает каждую метку (имя, описание, пример значения, блок).
Из неё строятся список меток для API (`placeholders`) и тестовый контекст
для пробного рендера загруженных шаблонов (`sample_context`).
"""

from datetime import date
from decimal import Decimal

from .words import amount_in_words, date_long

KINDS = frozenset(
    {"contract", "order_request", "carrier_order", "act", "invoice_print", "cmr", "letter"}
)

# Какие блоки меток входят в какой вид документа.
_KIND_BLOCKS = {
    "contract": ("doc", "company", "client"),
    "order_request": ("doc", "company", "client", "order"),
    "carrier_order": ("doc", "company", "carrier", "trip"),
    "act": ("doc", "company", "client", "invoice", "order"),
    "invoice_print": ("doc", "company", "client", "invoice", "order"),
    "cmr": ("doc", "company", "carrier", "trip"),
    "letter": ("doc", "company", "letter"),
}

_SAMPLE_DAY = date(2026, 3, 15)
_AMOUNT = Decimal("1250000.50")
_NET = Decimal("1116071.88")
_VAT = Decimal("133928.62")


def _s(ru: str, kk: str | None = None):
    """Строка-пример; в списках к ней добавляется номер элемента."""

    def make(lang: str, i: int) -> str:
        text = kk if (lang == "kk" and kk is not None) else ru
        return f"{text} {i + 1}" if i else text

    return make


def _const(value):
    return lambda lang, i: value


def _words(amount: Decimal, currency: str = "KZT"):
    return lambda lang, i: amount_in_words(amount, currency, lang)


def _date_long():
    return lambda lang, i: date_long(_SAMPLE_DAY, lang)


def _date(shift: int = 0):
    return lambda lang, i: date.fromordinal(_SAMPLE_DAY.toordinal() + shift + i).strftime(
        "%d.%m.%Y"
    )


def _party(prefix: str, label: str) -> list[tuple]:
    return [
        (f"{prefix}.name", f"Название: {label}", _s('ТОО "Пример"', 'ЖШС "Мысал"')),
        (f"{prefix}.bin_iin", f"БИН/ИИН: {label}", _const("123456789012")),
        (f"{prefix}.type", f"Тип организации: {label}", _s("ТОО", "ЖШС")),
        (
            f"{prefix}.address",
            f"Адрес: {label}",
            _s("г. Алматы, ул. Абая, 1", "Алматы қ., Абай к., 1"),
        ),
        (f"{prefix}.bank", f"Банк: {label}", _s("АО Народный банк", "Халық банкі АҚ")),
        (f"{prefix}.iban", f"IBAN: {label}", _const("KZ86125KZT5004100100")),
        (f"{prefix}.contact.name", f"Контактное лицо: {label}", _s("Иванов Иван", "Иванов Иван")),
        (f"{prefix}.contact.position", f"Должность контакта: {label}", _s("Директор", "Директор")),
        (f"{prefix}.contact.phone", f"Телефон контакта: {label}", _const("+7 701 000 00 00")),
        (f"{prefix}.contact.email", f"Email контакта: {label}", _const("info@example.kz")),
    ]


def _point(prefix: str, label: str) -> list[tuple]:
    return [
        (f"{prefix}.city", f"Город: {label}", _s("Алматы", "Алматы")),
        (f"{prefix}.address", f"Адрес: {label}", _s("ул. Складская, 5", "Қоймалық к., 5")),
        (f"{prefix}.date", f"Дата: {label}", _date(1)),
    ]


def _stop(prefix: str, label: str) -> list[tuple]:
    """Остановка маршрута: порядок, вид, город, адрес, окно (с и по)."""
    return [
        (f"{prefix}[].n", f"Порядковый номер остановки: {label}", lambda lang, i: str(i + 1)),
        (
            f"{prefix}[].kind",
            f"Вид остановки (load, unload, transit, transfer, customs): {label}",
            lambda lang, i: ("load", "unload")[i % 2],
        ),
        (
            f"{prefix}[].kind_name",
            f"Вид остановки словами: {label}",
            lambda lang, i: (("Тиеу", "Түсіру") if lang == "kk" else ("Погрузка", "Выгрузка"))[
                i % 2
            ],
        ),
        (f"{prefix}[].city", f"Город остановки: {label}", _s("Алматы", "Алматы")),
        (
            f"{prefix}[].address",
            f"Адрес остановки: {label}",
            _s("ул. Складская, 5", "Қоймалық к., 5"),
        ),
        (f"{prefix}[].date", f"Начало окна остановки: {label}", _date(1)),
        (f"{prefix}[].date_to", f"Конец окна остановки: {label}", _date(2)),
    ]


def _cargo(prefix: str) -> list[tuple]:
    return [
        (f"{prefix}[].name", "Наименование груза", _s("Продукты питания", "Азық-түлік")),
        (f"{prefix}[].weight_kg", "Вес груза, кг", _const("20000")),
        (f"{prefix}[].volume_m3", "Объём груза, м3", _const("82")),
        (f"{prefix}[].pallets", "Количество паллет", _const("33")),
    ]


def _build_blocks() -> dict[str, list[tuple]]:
    return {
        "doc": [
            ("doc.number", "Номер документа", _const("ДОК-2026-001")),
            ("doc.date", "Дата документа", _date()),
            ("doc.date_long", "Дата документа словами", _date_long()),
        ],
        "company": [
            ("company.name", "Название вашей компании", _s('ТОО "Логистикс"', 'ЖШС "Логистикс"')),
            ("company.bin", "БИН вашей компании", _const("987654321098")),
            (
                "company.address",
                "Адрес вашей компании",
                _s("г. Астана, пр. Республики, 10", "Астана қ., Республика д., 10"),
            ),
            ("company.bank", "Банк вашей компании", _s("АО Kaspi Bank", "Kaspi Bank АҚ")),
            ("company.iban", "IBAN вашей компании", _const("KZ12722S000012345678")),
        ],
        "client": _party("client", "клиент"),
        "carrier": _party("carrier", "перевозчик"),
        "order": [
            ("order.number", "Номер заказа", _const("З-2026-0042")),
            ("order.date", "Дата заказа", _date()),
            ("order.contract_number", "Номер договора", _const("Д-15/2026")),
            ("order.client_ref", "Номер заказа клиента", _const("PO-7788")),
            ("order.rate", "Ставка по заказу", _const("1250000.50")),
            ("order.rate_words", "Ставка по заказу прописью", _words(_AMOUNT)),
            ("order.currency", "Валюта заказа", _const("KZT")),
            ("order.payment_delay_days", "Отсрочка платежа, дней", _const("10")),
            (
                "order.comment",
                "Комментарий к заказу",
                _s("Температурный режим +2..+6", "Температура +2..+6"),
            ),
            ("order.manager", "Менеджер заказа", _s("Петров Пётр", "Петров Пётр")),
            *_cargo("order.consignments"),
            *_point("order.consignments[].load", "погрузка"),
            *_point("order.consignments[].unload", "выгрузка"),
            *_stop("order.consignments[].stops", "маршрут груза"),
            *_stop("order.stops", "маршрут заказа"),
        ],
        "trip": [
            ("trip.number", "Номер рейса", _const("Р-2026-0017")),
            (
                "trip.price",
                "Стоимость рейса (устарело, используйте carrier_price)",
                _const("900000.00"),
            ),
            (
                "trip.price_words",
                "Стоимость рейса прописью (устарело, используйте carrier_price_words)",
                _words(Decimal("900000.00")),
            ),
            ("trip.carrier_price", "Стоимость перевозчика", _const("900000.00")),
            (
                "trip.carrier_price_words",
                "Стоимость перевозчика прописью",
                _words(Decimal("900000.00")),
            ),
            ("trip.currency", "Валюта рейса", _const("KZT")),
            ("trip.vehicle_plate", "Госномер транспорта", _const("123ABC02")),
            ("trip.driver_name", "ФИО водителя", _s("Сидоров Сидор", "Сидоров Сидор")),
            *_point("trip.loading", "погрузка рейса"),
            *_point("trip.delivery", "доставка рейса"),
            ("trip.orders[].number", "Номер заказа в рейсе", _const("З-2026-0042")),
            ("trip.orders[].client", "Клиент заказа в рейсе", _s('ТОО "Пример"', 'ЖШС "Мысал"')),
            *_cargo("trip.consignments"),
            ("trip.consignments[].order", "Номер заказа грузового места", _const("З-2026-0042")),
            *_point("trip.consignments[].load", "погрузка"),
            *_point("trip.consignments[].unload", "выгрузка"),
            *_stop("trip.consignments[].stops", "маршрут груза"),
            *_stop("trip.stops", "маршрут рейса"),
        ],
        "invoice": [
            ("invoice.number", "Номер счёта", _const("СЧ-2026-0100")),
            ("invoice.date", "Дата счёта", _date()),
            ("invoice.due_date", "Срок оплаты счёта", _date(10)),
            ("invoice.currency", "Валюта счёта", _const("KZT")),
            ("invoice.vat_rate", "Ставка НДС, %", _const("12")),
            ("invoice.items[].n", "Номер позиции счёта", lambda lang, i: str(i + 1)),
            (
                "invoice.items[].title",
                "Наименование позиции счёта",
                _s("Транспортные услуги", "Көлік қызметтері"),
            ),
            (
                "invoice.items[].amount_net",
                "Сумма позиции без НДС",
                lambda lang, i: str(558035 + i),
            ),
            ("invoice.net", "Итого без НДС", _const(str(_NET))),
            ("invoice.vat", "Сумма НДС", _const(str(_VAT))),
            ("invoice.gross", "Итого с НДС", _const(str(_AMOUNT))),
            ("invoice.gross_words", "Итого с НДС прописью", _words(_AMOUNT)),
        ],
        "letter": [
            ("letter.recipient", "Адресат письма", _s('ТОО "Пример"', 'ЖШС "Мысал"')),
            ("letter.subject", "Тема письма", _s("О сроках поставки", "Жеткізу мерзімдері туралы")),
            (
                "letter.body",
                "Текст письма",
                _s("Уважаемые партнёры, сообщаем вам...", "Құрметті серіктестер..."),
            ),
        ],
    }


_BLOCKS = _build_blocks()


def _entries(kind: str) -> list[tuple]:
    if kind not in KINDS:
        raise ValueError(f"Неизвестный вид документа: {kind}")
    return [e for block in _KIND_BLOCKS[kind] for e in _BLOCKS[block]]


def placeholders(kind: str) -> list[dict]:
    return [{"name": name, "description": desc} for name, desc, _ in _entries(kind)]


def _put(node: dict, segments: list[str], make, lang: str, index: int | None) -> None:
    head, rest = segments[0], segments[1:]
    if head.endswith("[]"):
        key = head[:-2]
        items = node.setdefault(key, [{}, {}])
        for i, item in enumerate(items):
            _put(item, rest, make, lang, i)
        return
    if not rest:
        node[head] = make(lang, index or 0)
        return
    _put(node.setdefault(head, {}), rest, make, lang, index)


def sample_context(kind: str, language: str = "ru") -> dict:
    ctx: dict = {}
    for name, _desc, make in _entries(kind):
        _put(ctx, name.split("."), make, language, None)
    return ctx


def context_keys(ctx: dict) -> set[str]:
    keys: set[str] = set()

    def walk(value, prefix: str) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, f"{prefix}.{k}" if prefix else k)
        elif isinstance(value, list):
            for item in value:
                walk(item, f"{prefix}[]")
        else:
            keys.add(prefix)

    walk(ctx, "")
    return keys
