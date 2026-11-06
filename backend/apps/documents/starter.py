"""Стартовые образцы шаблонов документов на русском языке.

Файлы .docx собираются кодом (python-docx) с метками подстановки. Это образцы:
в начале каждого стоит пометка о необходимости проверки у юриста.
"""

import hashlib
from io import BytesIO

from docx import Document

from apps.core.tenancy import tenant_context

DISCLAIMER = "ОБРАЗЕЦ - проверьте формулировки у юриста перед использованием"

STARTER_NAMES: dict[str, str] = {
    "contract": "Договор перевозки (экспедирования)",
    "order_request": "Заявка клиента",
    "carrier_order": "Договор-заявка перевозчику",
    "act": "Акт выполненных работ",
    "invoice_print": "Счёт на оплату",
    "cmr": "CMR (товарно-транспортная накладная)",
    "letter": "Письмо на бланке",
}

_PARTY_LINES = (
    "{{ {p}.name }}, БИН/ИИН {{ {p}.bin_iin }}",
    "Адрес: {{ {p}.address }}",
    "Банк: {{ {p}.bank }}, IBAN: {{ {p}.iban }}",
    "Контакт: {{ {p}.contact.name }}, {{ {p}.contact.position }}, "
    "{{ {p}.contact.phone }}, {{ {p}.contact.email }}",
)


def _party_lines(prefix: str) -> list[str]:
    return [line.replace("{p}", prefix) for line in _PARTY_LINES]


def _company_lines() -> list[str]:
    return [
        "{{ company.name }}, БИН {{ company.bin }}",
        "Адрес: {{ company.address }}",
        "Банк: {{ company.bank }}, IBAN: {{ company.iban }}",
    ]


def _table(doc, header: list[str], loop: str, cells: list[str]):
    """Таблица с циклом по строкам: служебные строки {%tr ...%} удаляются при рендере."""
    table = doc.add_table(rows=1, cols=len(header))
    table.style = "Table Grid"
    for cell, text in zip(table.rows[0].cells, header, strict=True):
        cell.text = text
    start = table.add_row().cells
    start[0].text = "{%tr for it in " + loop + " %}"
    row = table.add_row().cells
    for cell, text in zip(row, cells, strict=True):
        cell.text = text
    end = table.add_row().cells
    end[0].text = "{%tr endfor %}"


def _signatures(doc, left: str, right: str) -> None:
    table = doc.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = left
    table.rows[0].cells[1].text = right
    table.rows[1].cells[0].text = "____________ / ____________ /"
    table.rows[1].cells[1].text = "____________ / ____________ /"


def _lines(doc, lines: list[str]) -> None:
    for line in lines:
        doc.add_paragraph(line)


def _contract(doc) -> None:
    doc.add_heading("Договор перевозки (экспедирования) № {{ doc.number }}", level=1)
    doc.add_paragraph("{{ doc.date_long }}")
    doc.add_paragraph(
        "{{ company.name }} (далее - Экспедитор) и {{ client.name }} (далее - Клиент) "
        "заключили настоящий договор о нижеследующем."
    )
    doc.add_heading("1. Предмет договора", level=2)
    doc.add_paragraph(
        "Экспедитор обязуется организовать перевозку грузов Клиента на основании заявок, "
        "а Клиент обязуется оплатить услуги."
    )
    doc.add_heading("2. Стоимость и порядок расчётов", level=2)
    doc.add_paragraph("Стоимость услуг определяется в заявках. Оплата - по выставленным счетам.")
    doc.add_heading("3. Срок действия", level=2)
    doc.add_paragraph("Договор действует с даты подписания до полного исполнения обязательств.")
    doc.add_heading("4. Реквизиты сторон", level=2)
    _lines(doc, ["Экспедитор:", *_company_lines(), "Клиент:", *_party_lines("client")])
    _signatures(doc, "Экспедитор: {{ company.name }}", "Клиент: {{ client.name }}")


def _order_request(doc) -> None:
    doc.add_heading("Заявка клиента № {{ order.number }} от {{ order.date }}", level=1)
    doc.add_paragraph(
        "К договору № {{ order.contract_number }}. Заказ клиента: {{ order.client_ref }}"
    )
    _lines(doc, ["Заказчик:", *_party_lines("client"), "Исполнитель:", *_company_lines()])
    doc.add_heading("Грузы и маршрут", level=2)
    _table(
        doc,
        ["Груз", "Вес, кг", "Объём, м3", "Паллет", "Погрузка", "Выгрузка"],
        "order.consignments",
        [
            "{{ it.name }}",
            "{{ it.weight_kg }}",
            "{{ it.volume_m3 }}",
            "{{ it.pallets }}",
            "{{ it.load.city }}, {{ it.load.address }}, {{ it.load.date }}",
            "{{ it.unload.city }}, {{ it.unload.address }}, {{ it.unload.date }}",
        ],
    )
    doc.add_paragraph(
        "Ставка: {{ order.rate }} {{ order.currency }} ({{ order.rate_words }}). "
        "Отсрочка платежа: {{ order.payment_delay_days }} дн."
    )
    doc.add_paragraph("Комментарий: {{ order.comment }}")
    doc.add_paragraph("Менеджер: {{ order.manager }}")
    _signatures(doc, "Заказчик: {{ client.name }}", "Исполнитель: {{ company.name }}")


def _carrier_order(doc) -> None:
    doc.add_heading("Договор-заявка перевозчику № {{ doc.number }}", level=1)
    doc.add_paragraph("{{ doc.date_long }}. Рейс № {{ trip.number }}")
    _lines(doc, ["Заказчик:", *_company_lines(), "Перевозчик:", *_party_lines("carrier")])
    doc.add_heading("Условия перевозки", level=2)
    doc.add_paragraph(
        "Транспорт: {{ trip.vehicle_plate }}, водитель: {{ trip.driver_name }}. "
        "Погрузка: {{ trip.loading.city }}, {{ trip.loading.address }}, {{ trip.loading.date }}. "
        "Доставка: {{ trip.delivery.city }}, {{ trip.delivery.address }}, "
        "{{ trip.delivery.date }}."
    )
    _table(
        doc,
        ["Груз", "Вес, кг", "Объём, м3", "Заказ", "Погрузка", "Выгрузка"],
        "trip.consignments",
        [
            "{{ it.name }}",
            "{{ it.weight_kg }}",
            "{{ it.volume_m3 }}",
            "{{ it.order }}",
            "{{ it.load.city }}, {{ it.load.address }}",
            "{{ it.unload.city }}, {{ it.unload.address }}",
        ],
    )
    doc.add_paragraph(
        "Стоимость перевозки: {{ trip.price }} {{ trip.currency }} ({{ trip.price_words }})."
    )
    _signatures(doc, "Заказчик: {{ company.name }}", "Перевозчик: {{ carrier.name }}")


def _act(doc) -> None:
    doc.add_heading("Акт выполненных работ № {{ doc.number }}", level=1)
    doc.add_paragraph("{{ doc.date_long }}")
    doc.add_paragraph(
        "Исполнитель {{ company.name }} оказал, а Заказчик {{ client.name }} принял услуги "
        "по заказу № {{ order.number }} (счёт № {{ invoice.number }} от {{ invoice.date }})."
    )
    _table(
        doc,
        ["№", "Наименование", "Сумма без НДС, {{ invoice.currency }}"],
        "invoice.items",
        ["{{ it.n }}", "{{ it.title }}", "{{ it.amount_net }}"],
    )
    doc.add_paragraph("Итого без НДС: {{ invoice.net }}")
    doc.add_paragraph("НДС ({{ invoice.vat_rate }}%): {{ invoice.vat }}")
    doc.add_paragraph("Всего с НДС: {{ invoice.gross }} ({{ invoice.gross_words }})")
    doc.add_paragraph("Стороны претензий по объёму, качеству и срокам услуг не имеют.")
    _signatures(doc, "Исполнитель: {{ company.name }}", "Заказчик: {{ client.name }}")


def _invoice_print(doc) -> None:
    doc.add_heading("Счёт на оплату № {{ invoice.number }} от {{ invoice.date }}", level=1)
    _lines(doc, ["Поставщик:", *_company_lines(), "Покупатель:", *_party_lines("client")])
    doc.add_paragraph("Заказ № {{ order.number }}. Срок оплаты: {{ invoice.due_date }}")
    _table(
        doc,
        ["№", "Наименование", "Сумма без НДС, {{ invoice.currency }}"],
        "invoice.items",
        ["{{ it.n }}", "{{ it.title }}", "{{ it.amount_net }}"],
    )
    doc.add_paragraph("Итого без НДС: {{ invoice.net }}")
    doc.add_paragraph("НДС ({{ invoice.vat_rate }}%): {{ invoice.vat }}")
    doc.add_paragraph("Всего к оплате: {{ invoice.gross }} ({{ invoice.gross_words }})")
    _signatures(doc, "Руководитель: {{ company.name }}", "Главный бухгалтер")


def _cmr(doc) -> None:
    doc.add_heading("CMR (товарно-транспортная накладная) № {{ doc.number }}", level=1)
    doc.add_paragraph("Дата: {{ doc.date }}. Рейс № {{ trip.number }}")
    _lines(doc, ["1. Отправитель:", *_company_lines(), "2. Перевозчик:", *_party_lines("carrier")])
    doc.add_paragraph(
        "3. Место погрузки: {{ trip.loading.city }}, {{ trip.loading.address }}, "
        "{{ trip.loading.date }}"
    )
    doc.add_paragraph(
        "4. Место доставки: {{ trip.delivery.city }}, {{ trip.delivery.address }}, "
        "{{ trip.delivery.date }}"
    )
    doc.add_paragraph("5. Транспорт: {{ trip.vehicle_plate }}, водитель: {{ trip.driver_name }}")
    _table(
        doc,
        ["Груз", "Вес, кг", "Объём, м3", "Паллет"],
        "trip.consignments",
        ["{{ it.name }}", "{{ it.weight_kg }}", "{{ it.volume_m3 }}", "{{ it.pallets }}"],
    )
    _signatures(doc, "Отправитель: {{ company.name }}", "Перевозчик: {{ carrier.name }}")


def _letter(doc) -> None:
    doc.add_paragraph("{{ company.name }}")
    doc.add_paragraph("{{ company.address }}")
    doc.add_paragraph("Исх. № {{ doc.number }} от {{ doc.date }}")
    doc.add_paragraph("Кому: {{ letter.recipient }}")
    doc.add_heading("{{ letter.subject }}", level=2)
    doc.add_paragraph("{{ letter.body }}")
    doc.add_paragraph("С уважением, {{ company.name }}")


_BUILDERS = {
    "contract": _contract,
    "order_request": _order_request,
    "carrier_order": _carrier_order,
    "act": _act,
    "invoice_print": _invoice_print,
    "cmr": _cmr,
    "letter": _letter,
}


def starter_bytes(kind: str, language: str = "ru") -> bytes:
    if language != "ru":
        raise ValueError(f"Стартовые шаблоны есть только на русском: {language}")
    if kind not in _BUILDERS:
        raise ValueError(f"Неизвестный вид документа: {kind}")
    doc = Document()
    doc.add_paragraph(DISCLAIMER)
    _BUILDERS[kind](doc)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _seed(company_id: int, templates, versions) -> None:
    with tenant_context(company_id):
        for kind, name in STARTER_NAMES.items():
            template, _ = templates.get_or_create(
                company_id=company_id,
                kind=kind,
                language="ru",
                is_active=True,
                defaults={"name": name},
            )
            if versions.filter(template=template).exists():
                continue
            content = starter_bytes(kind)
            version = versions.create(
                company_id=company_id,
                template=template,
                number=1,
                content=content,
                sha256=hashlib.sha256(content).hexdigest(),
                is_starter=True,
            )
            template.current_version = version
            template.save(update_fields=["current_version"])


def seed_starter_templates(company) -> None:
    """Идемпотентно создать стартовый набор шаблонов компании."""
    from .models import DocumentTemplate, DocumentTemplateVersion

    _seed(company.id, DocumentTemplate.objects, DocumentTemplateVersion.objects)
