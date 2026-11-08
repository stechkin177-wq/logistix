"""Сбор контекста подстановки по видам документов.

Контекст - словарь из JSON-примитивов (строки, списки, словари): он сохраняется в снимок
выданного документа и по нему же собирается файл. Набор ключей совпадает с метками
`catalog.placeholders(kind)`. Отсутствующие данные дают пустые строки и пустые списки.
"""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.utils import timezone

from apps.core.models import LegalEntity

from .catalog import _KIND_BLOCKS, KINDS
from .words import amount_in_words, date_long

_CENTS = Decimal("0.01")


def _date(value) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        value = value.date()
    return value.strftime("%d.%m.%Y")


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _money(value) -> str:
    """1234567.891 -> «1 234 567,89» (обычные пробелы)."""
    amount = _dec(value)
    if amount is None:
        return ""
    amount = amount.quantize(_CENTS, rounding=ROUND_HALF_UP)
    whole, frac = f"{abs(amount):.2f}".split(".")
    groups = f"{int(whole):,}".replace(",", " ")
    return f"{'-' if amount < 0 else ''}{groups},{frac}"


def _qty(value) -> str:
    """Количество без хвостовых нулей: 1500.50 -> «1500,5», 20000.00 -> «20000»."""
    number = _dec(value)
    if number is None:
        return ""
    text = f"{number:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _words(value, currency: str, language: str) -> str:
    amount = _dec(value)
    if amount is None:
        return ""
    return amount_in_words(amount, currency, language)


def _str(value) -> str:
    return "" if value is None else str(value)


def _code(handbook_value) -> str:
    return handbook_value.code if handbook_value is not None else ""


def _vat_percent(handbook_value) -> str:
    code = _code(handbook_value)
    if not code:
        return ""
    return code if code.isdigit() else "0"


def _company(order=None, invoice=None, trip=None) -> dict:
    entity = None
    if order is None and invoice is not None:
        order = invoice.order
    if order is None and trip is not None:
        first = (
            trip.consignments.filter(order__deleted_at__isnull=True)
            .select_related("order__legal_entity")
            .order_by("id")
            .first()
        )
        order = first.order if first else None
    if order is not None:
        entity = order.legal_entity
    if entity is None:
        entity = LegalEntity.objects.filter(is_default=True).first()
    return {
        "name": entity.name if entity else "",
        "bin": entity.bin if entity else "",
        "address": entity.address if entity else "",
        "bank": entity.bank if entity else "",
        "iban": entity.iban if entity else "",
    }


def _party(party) -> dict:
    contact = party.contacts.order_by("id").first() if party is not None else None
    return {
        "name": _str(party and party.name),
        "bin_iin": _str(party and party.bin_iin),
        "type": _str(party and party.type and party.type.name),
        "address": _str(party and party.address),
        "bank": _str(party and party.bank),
        "iban": _str(party and party.iban),
        "contact": {
            "name": _str(contact and contact.name),
            "position": _str(contact and contact.position),
            "phone": _str(contact and contact.phone),
            "email": _str(contact and contact.email),
        },
    }


def _point(point) -> dict:
    return {
        "city": _str(point and point.city),
        "address": _str(point and point.street),
        "date": _date(point and point.window_from),
    }


_KIND_NAMES = {
    "load": ("Погрузка", "Тиеу"),
    "unload": ("Выгрузка", "Түсіру"),
    "transit": ("Промежуточная остановка", "Аралық аялдама"),
    "transfer": ("Передача / перегрузка", "Тапсыру / қайта тиеу"),
    "customs": ("Граница / таможня", "Шекара / кеден"),
}


def _ordered_stops(consignment) -> list:
    return sorted(consignment.points.all(), key=lambda p: (p.seq, p.pk))


def _points_of(consignment) -> tuple:
    """Первая погрузка и последняя выгрузка маршрута (прежние ключи load/unload)."""
    stops = _ordered_stops(consignment)
    load = next((p for p in stops if p.kind == "load"), None)
    unload = next((p for p in reversed(stops) if p.kind == "unload"), None)
    return load, unload


def _stop(point, number: int, language: str) -> dict:
    names = _KIND_NAMES.get(point.kind, (point.kind, point.kind))
    return {
        "n": str(number),
        "kind": point.kind,
        "kind_name": names[1] if language == "kk" else names[0],
        "city": point.city,
        "address": point.street,
        "date": _date(point.window_from),
        "date_to": _date(point.window_to),
    }


def _stops(consignment, language: str) -> list[dict]:
    return [_stop(p, n, language) for n, p in enumerate(_ordered_stops(consignment), start=1)]


def _merged_stops(consignments, language: str) -> list[dict]:
    """Маршрут нескольких грузов одним списком: одинаковые остановки (вид, город, адрес,
    начало окна) показываются один раз, порядок - по началу окна, затем по порядку в грузе."""
    seen, merged = set(), []
    for c in consignments:
        for p in _ordered_stops(c):
            key = (p.kind, p.city, p.street, p.window_from)
            if key not in seen:
                seen.add(key)
                merged.append(p)
    merged.sort(key=lambda p: (p.window_from, p.seq, p.pk))
    return [_stop(p, n, language) for n, p in enumerate(merged, start=1)]


def _legs(trip) -> list[dict]:
    """Участки рейса (действующие грузы): груз, заказ, откуда - куда, статус, доли."""
    links = (
        trip.links.filter(
            consignment__deleted_at__isnull=True, consignment__order__deleted_at__isnull=True
        )
        .select_related("consignment__order", "from_stop", "to_stop")
        .order_by("consignment_id", "leg_seq", "id")
    )
    items = []
    for n, link in enumerate(links, start=1):
        first, last = link.from_stop, link.to_stop
        items.append(
            {
                "n": str(n),
                "consignment": link.consignment.name,
                "order": link.consignment.order.number,
                "from_city": _str(first and first.city),
                "from_address": _str(first and first.street),
                "to_city": _str(last and last.city),
                "to_address": _str(last and last.street),
                "status": link.status,
                "weight_kg": _qty(link.weight_kg),
                "volume_m3": _qty(link.volume_m3),
                "pallets": _str(link.pallets),
            }
        )
    return items


def _consignment(consignment, language: str = "ru") -> dict:
    load, unload = _points_of(consignment)
    return {
        "name": consignment.name,
        "weight_kg": _qty(consignment.weight_kg),
        "volume_m3": _qty(consignment.volume_m3),
        "pallets": _str(consignment.pallets),
        "load": _point(load),
        "unload": _point(unload),
        "stops": _stops(consignment, language),
    }


def _order(order, language: str) -> dict:
    if order is None:
        return {
            "number": "",
            "date": "",
            "contract_number": "",
            "client_ref": "",
            "rate": "",
            "rate_words": "",
            "currency": "",
            "payment_delay_days": "",
            "comment": "",
            "manager": "",
            "consignments": [],
            "stops": [],
        }
    currency = _code(order.currency)
    consignments = list(order.consignments.prefetch_related("points").order_by("id"))
    return {
        "number": order.number,
        "date": _date(order.created_at),
        "contract_number": order.contract_number,
        "client_ref": order.client_ref,
        "rate": _money(order.client_rate),
        "rate_words": _words(order.client_rate, currency, language),
        "currency": currency,
        "payment_delay_days": _str(order.payment_delay_days),
        "comment": order.comment,
        "manager": order.manager.full_name or "" if order.manager_id else "",
        "consignments": [_consignment(c, language) for c in consignments],
        "stops": _merged_stops(consignments, language),
    }


def _trip(trip, language: str) -> dict:
    currency = _code(trip.currency)
    consignments = list(
        trip.consignments.filter(order__deleted_at__isnull=True)
        .select_related("order__client")
        .prefetch_related("points")
        .order_by("id")
    )
    orders: dict[int, dict] = {}
    items = []
    loads, unloads = [], []
    for c in consignments:
        orders.setdefault(c.order_id, {"number": c.order.number, "client": c.order.client.name})
        load, unload = _points_of(c)
        if load is not None:
            loads.append(load)
        if unload is not None:
            unloads.append(unload)
        items.append({**_consignment(c, language), "order": c.order.number})
    loading = min(loads, key=lambda p: p.window_from, default=None)
    delivery = max(unloads, key=lambda p: p.window_from, default=None)
    return {
        "number": trip.number,
        # price/price_words устарели (используйте carrier_price); оставлены для старых шаблонов
        "price": _money(trip.carrier_price),
        "price_words": _words(trip.carrier_price, currency, language),
        "carrier_price": _money(trip.carrier_price),
        "carrier_price_words": _words(trip.carrier_price, currency, language),
        "currency": currency,
        "vehicle_plate": trip.vehicle_plate,
        "driver_name": trip.driver_name,
        "loading": _point(loading),
        "delivery": _point(delivery),
        "orders": list(orders.values()),
        "consignments": items,
        "stops": _merged_stops(consignments, language),
        "legs": _legs(trip),
    }


def _invoice(invoice, language: str) -> dict:
    currency = _code(invoice.currency)
    items = [
        {"n": str(n), "title": item.title, "amount_net": _money(item.amount_net)}
        for n, item in enumerate(invoice.items.order_by("id"), start=1)
    ]
    return {
        "number": invoice.number,
        "date": _date(invoice.issue_date),
        "due_date": _date(invoice.due_date),
        "currency": currency,
        "vat_rate": _vat_percent(invoice.vat_rate),
        "items": items,
        "net": _money(invoice.total_net),
        "vat": _money(invoice.total_vat),
        "gross": _money(invoice.total_gross),
        "gross_words": _words(invoice.total_gross, currency, language),
    }


def build_context(
    kind: str,
    *,
    client=None,
    order=None,
    trip=None,
    invoice=None,
    letter: dict | None = None,
    number: str,
    issue_date: date,
    language: str,
) -> dict:
    """Контекст подстановки для вида документа; вызывается в контексте компании (RLS)."""
    if kind not in KINDS:
        raise ValueError(f"Неизвестный вид документа: {kind}")
    blocks = _KIND_BLOCKS[kind]
    if invoice is not None and order is None:
        order = invoice.order
    ctx: dict = {
        "doc": {
            "number": number,
            "date": _date(issue_date),
            "date_long": date_long(issue_date, language),
        },
        "company": _company(order=order, invoice=invoice, trip=trip),
    }
    if "client" in blocks:
        owner = client or (order.client if order is not None else None)
        if invoice is not None and invoice.client_id:
            owner = invoice.client
        ctx["client"] = _party(owner)
    if "carrier" in blocks:
        ctx["carrier"] = _party(trip.carrier if trip is not None else None)
    if "order" in blocks:
        ctx["order"] = _order(order, language)
    if "trip" in blocks:
        ctx["trip"] = (
            _trip(trip, language)
            if trip is not None
            else {
                **{
                    k: ""
                    for k in (
                        "number",
                        "price",
                        "price_words",
                        "carrier_price",
                        "carrier_price_words",
                        "currency",
                    )
                },
                **{k: "" for k in ("vehicle_plate", "driver_name")},
                "loading": _point(None),
                "delivery": _point(None),
                "orders": [],
                "consignments": [],
                "stops": [],
                "legs": [],
            }
        )
    if "invoice" in blocks:
        ctx["invoice"] = (
            _invoice(invoice, language)
            if invoice is not None
            else {
                **{k: "" for k in ("number", "date", "due_date", "currency", "vat_rate")},
                **{k: "" for k in ("net", "vat", "gross", "gross_words")},
                "items": [],
            }
        )
    if "letter" in blocks:
        data = letter or {}
        ctx["letter"] = {k: _str(data.get(k)) for k in ("recipient", "subject", "body")}
    return ctx
