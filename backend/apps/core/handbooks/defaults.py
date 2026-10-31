"""Справочники по умолчанию: код -> {name, group, values}. Порядок значений = order с 1."""


def _names(*names):
    return [{"name": n} for n in names]


def _coded(*pairs):
    return [{"name": n, "code": c} for n, c in pairs]


_PERSON_TYPES = _names("Юридическое лицо", "ИП", "Физическое лицо")

DEFAULTS: dict[str, dict] = {
    "order_status": {
        "name": "Статусы заявок",
        "group": "Статусы",
        "values": [
            {"name": "Новый", "is_initial": True},
            {"name": "В работе"},
            {"name": "На погрузке"},
            {"name": "В пути"},
            {"name": "На выгрузке"},
            # code нужен бизнес-логике заказов: completed_at ставится по коду, не по названию
            {"name": "Завершён", "code": "completed", "is_final": True},
            {"name": "Отменён", "code": "cancelled", "is_final": True},
        ],
    },
    "consignment_status": {
        "name": "Статусы грузов",
        "group": "Статусы",
        "values": [
            {"name": "Принят", "is_initial": True},
            {"name": "На складе"},
            {"name": "В пути"},
            {"name": "Доставлен"},
            {"name": "Выдан", "is_final": True},
        ],
    },
    "trip_status": {
        "name": "Статусы рейсов",
        "group": "Статусы",
        "values": [
            {"name": "Планируется", "is_initial": True},
            {"name": "Ожидает выезда"},
            {"name": "В пути"},
            {"name": "Выгрузка"},
            {"name": "Завершён", "is_final": True},
            {"name": "Отменён", "is_final": True},
        ],
    },
    "currency": {
        "name": "Валюты",
        "group": "Финансы",
        "values": _coded(
            ("Тенге", "KZT"),
            ("Российский рубль", "RUB"),
            ("Доллар США", "USD"),
            ("Евро", "EUR"),
        ),
    },
    "payment_delay_condition": {
        "name": "Условия отсрочки платежа",
        "group": "Финансы",
        "values": _names(
            "По факту выгрузки", "По получении оригиналов", "С даты счёта", "С даты отгрузки"
        ),
    },
    "client_type": {"name": "Типы клиентов", "group": "Контрагенты", "values": _PERSON_TYPES},
    "carrier_type": {"name": "Типы перевозчиков", "group": "Контрагенты", "values": _PERSON_TYPES},
    "packaging": {
        "name": "Виды упаковки",
        "group": "Грузы и маршруты",
        "values": _names("Паллета", "Коробка", "Мешок", "Бочка", "Навалом"),
    },
    "loading_method": {
        "name": "Способы погрузки",
        "group": "Грузы и маршруты",
        "values": _names("Боковая", "Задняя", "Верхняя", "Гидроборт"),
    },
    "country": {
        "name": "Страны",
        "group": "Грузы и маршруты",
        "values": _coded(
            ("Казахстан", "KZ"),
            ("Россия", "RU"),
            ("Китай", "CN"),
            ("Узбекистан", "UZ"),
            ("Киргизия", "KG"),
            ("Беларусь", "BY"),
            ("Туркменистан", "TM"),
            ("Таджикистан", "TJ"),
            ("Азербайджан", "AZ"),
            ("Грузия", "GE"),
            ("Турция", "TR"),
            ("Иран", "IR"),
            ("Монголия", "MN"),
            ("Германия", "DE"),
            ("Польша", "PL"),
            ("Литва", "LT"),
            ("Латвия", "LV"),
            ("Эстония", "EE"),
            ("Армения", "AM"),
            ("Украина", "UA"),
        ),
    },
    "transport_condition": {
        "name": "Условия перевозки",
        "group": "Грузы и маршруты",
        "values": _names("FCA", "DAP", "CPT"),
    },
}
