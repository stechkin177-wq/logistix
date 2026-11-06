"""Выгрузка заказов в Excel: GET /api/orders/export/.

Книга openpyxl в режиме write_only (строки не держатся в памяти openpyxl, лист «Заказы»),
отдаётся в HttpResponse. Те же фильтры и сортировка, что у списка. Жёсткий лимит
EXPORT_LIMIT строк: больше - 400 с просьбой сузить фильтр. Столбцы выручки, расходов, прибыли и
маржи - только при finance.view. Даты - в часовом поясе компании (без пояса, как принято в
Excel). Деньги пишутся числовыми ячейками из Decimal без перевода в float; Excel хранит числа
как double с 15 значащими цифрами - этого достаточно для сумм до 10^12 с копейками.

Защита от инъекции формул: текст, начинающийся с = + - @ табуляции или возврата каретки,
получает ведущий апостроф (') и не становится формулой. Число запросов фиксировано (10).
"""

import io
from datetime import datetime

from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font
from rest_framework.exceptions import ValidationError
from rest_framework.negotiation import DefaultContentNegotiation

from ..finance_lines.services import annotate_order_totals, margin_pct
from ..models import Order
from .board import carrier_names, routed
from .filters import apply_filters, apply_ordering, loading_at_subquery
from .serializers import order_route


class AnyAcceptNegotiation(DefaultContentNegotiation):
    """Файл отдаётся при любом Accept (в т.ч. самом типе xlsx), а не 406."""

    def select_renderer(self, request, renderers, format_suffix=None):
        return (renderers[0], renderers[0].media_type)


EXPORT_LIMIT = 10_000
SHEET_NAME = "Заказы"
CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HEADERS = [
    "Номер",
    "Клиент",
    "Маршрут",
    "Перевозчик",
    "Статус",
    "Погрузка",
    "Ставка",
    "Валюта",
    "Создан",
]
FINANCE_HEADERS = ["Выручка", "Расходы", "Прибыль", "Маржа %"]
DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
MONEY_FORMAT = "#,##0.00"
DATETIME_FORMAT = "DD.MM.YYYY HH:MM"


def safe_text(value) -> str:
    """Текст ячейки без риска формулы: опасное начало защищается ведущим апострофом."""
    text = ILLEGAL_CHARACTERS_RE.sub("", str(value or ""))  # иначе openpyxl падает с 500
    return "'" + text if text.startswith(DANGEROUS_PREFIXES) else text


def _cell(ws, value, number_format=None):
    cell = WriteOnlyCell(ws, value=value)
    if number_format:
        cell.number_format = number_format
    return cell


def _local(value: datetime | None, zone):
    return value.astimezone(zone).replace(tzinfo=None) if value else None


def _row(ws, order, carriers, zone, with_finance):
    row = [
        safe_text(order.number),
        safe_text(order.client.name),
        safe_text(order_route(order)),
        safe_text(", ".join(carriers.get(order.pk, []))),
        safe_text(order.status.name),
        _cell(ws, _local(order.loading_at, zone), DATETIME_FORMAT),
        _cell(ws, order.client_rate, MONEY_FORMAT),
        safe_text(order.currency.code),
        _cell(ws, _local(order.created_at, zone), DATETIME_FORMAT),
    ]
    if with_finance:
        profit = order.revenue - order.cost
        margin = margin_pct(order.revenue, profit)
        row += [
            _cell(ws, order.revenue, MONEY_FORMAT),
            _cell(ws, order.cost, MONEY_FORMAT),
            _cell(ws, profit, MONEY_FORMAT),
            _cell(ws, margin if margin is not None else None, MONEY_FORMAT),
        ]
    return row


def export_orders(params, zone, *, with_finance: bool) -> HttpResponse:
    qs = Order.objects.select_related("client", "status", "currency").annotate(
        loading_at=loading_at_subquery()
    )
    if with_finance:
        qs = annotate_order_totals(qs)
    qs = apply_ordering(apply_filters(qs, params, zone), params)
    if qs.values("pk")[EXPORT_LIMIT : EXPORT_LIMIT + 1].exists():  # дёшево, до загрузки строк
        raise ValidationError(
            f"Слишком много заказов для выгрузки (больше {EXPORT_LIMIT:,}): "
            "сузьте фильтр (период, клиент, статус) и повторите".replace(",", " ")
        )
    orders = list(routed(qs[:EXPORT_LIMIT]))
    carriers = carrier_names([o.pk for o in orders])
    wb = Workbook(write_only=True)
    ws = wb.create_sheet(SHEET_NAME)
    for column, width in zip("ABCDEFGHIJKLM", (22, 28, 32, 28, 16, 18, 16, 8, 18, 16, 16, 16, 10)):
        ws.column_dimensions[column].width = width
    bold = Font(bold=True)
    head = HEADERS + (FINANCE_HEADERS if with_finance else [])
    cells = []
    for title in head:
        cell = WriteOnlyCell(ws, value=title)
        cell.font = bold
        cells.append(cell)
    ws.append(cells)
    for order in orders:
        ws.append(_row(ws, order, carriers, zone, with_finance))
    buffer = io.BytesIO()
    wb.save(buffer)
    today = timezone.now().astimezone(zone).date()
    response = HttpResponse(buffer.getvalue(), content_type=CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="orders-{today.isoformat()}.xlsx"'
    response["Cache-Control"] = "private, no-store"
    return response
