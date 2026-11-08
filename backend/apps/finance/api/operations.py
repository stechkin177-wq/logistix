import io

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import permission_required
from apps.core.pagination import StandardPagination
from apps.forwarding.finance_lines.models import company_today
from apps.forwarding.orders.export import (
    CONTENT_TYPE,
    EXPORT_LIMIT,
    MONEY_FORMAT,
    AnyAcceptNegotiation,
    safe_text,
)
from apps.forwarding.orders.filters import date_param, int_param
from apps.forwarding.orders.services import BASE_CURRENCY_CODE

from .. import debts_base
from .. import operations as ops
from ..reports_new import base_currency_code
from .fx import realized_queryset, write_realized_sheet
from .serializers import excluded_data, money

HEADERS = ["Дата", "Заказ", "Клиент", "Название", "Категория", "Доход", "Расход", "Валюта"]
BASE_STATUS_TEXT = {
    "current": "",
    "prior_base": "в прежней базовой валюте",
    "no_rate": "без курса",
}


class OperationsMixin:
    def get_permissions(self):
        return [ModuleRequired("finance")(), permission_required("finance.view")()]

    def filters(self, request) -> dict:
        p = request.query_params
        return dict(
            date_from=date_param(p, "date_from"),
            date_to=date_param(p, "date_to"),
            category=(p.get("category") or "").strip() or None,
            client=int_param(p, "client"),
            order=int_param(p, "order"),
            accounting_start=request.membership.company.accounting_start,
        )


def summary_data(s: dict) -> dict:
    # *_kzt - прежние имена полей (совместимость); суммы в базовой валюте, её код - в currency
    return {
        "currency": s.get("currency") or BASE_CURRENCY_CODE,
        "excluded": excluded_data(s.get("excluded")),
        "is_partial": bool(s.get("excluded") and s["excluded"]["count"]),
        "income_kzt": money(s["income_kzt"]),
        "expense_kzt": money(s["expense_kzt"]),
        "diff_kzt": money(s["diff_kzt"]),
        "by_currency": {
            c: {k: money(v) for k, v in row.items()} for c, row in s["by_currency"].items()
        },
        "unconverted": s["unconverted"],
    }


class OperationsView(OperationsMixin, APIView):
    def get(self, request):
        filters = self.filters(request)
        cid = request.membership.company_id
        paginator = StandardPagination()
        page = paginator.paginate_queryset(ops.journal_rows(cid, **filters), request, view=self)
        rows = [
            {
                "id": ln.pk,
                "date": ln.date,
                "order": {"id": ln.order_id, "number": ln.order.number},
                "client": {"id": ln.order.client_id, "name": ln.order.client.name},
                "title": ln.title,
                "category": ln.category,
                "income": money(ln.income),
                "expense": money(ln.expense),
                "currency": ln.order.currency.code,
                "is_base": ln.is_base,
                "base_status": getattr(ln, "bucket", None),
            }
            for ln in page
        ]
        response = paginator.get_paginated_response(rows)
        response.data["summary"] = summary_data(ops.journal_summary(cid, **filters))
        return response


class OperationsExportView(OperationsMixin, APIView):
    content_negotiation_class = AnyAcceptNegotiation

    def get(self, request):
        qs = ops.journal_rows(request.membership.company_id, **self.filters(request))
        too_many = (
            len(qs) > EXPORT_LIMIT
            if isinstance(qs, list)
            else qs.values("pk")[EXPORT_LIMIT : EXPORT_LIMIT + 1].exists()
        )
        if too_many:
            raise ValidationError(
                f"Слишком много операций для выгрузки (больше {EXPORT_LIMIT}): сузьте фильтр"
            )
        # новая модель: добавляются суммы в базовой валюте и пометка записей вне итога базы
        in_base = isinstance(qs, list)
        headers = list(HEADERS)
        if in_base:
            code = base_currency_code(request.membership.company_id)
            headers += [f"Доход, {code}", f"Расход, {code}", "Учёт в базовой валюте"]
        wb = Workbook(write_only=True)
        ws = wb.create_sheet("Операции")
        head = []
        for title in headers:
            cell = WriteOnlyCell(ws, value=title)
            cell.font = Font(bold=True)
            head.append(cell)
        ws.append(head)
        for ln in qs[:EXPORT_LIMIT]:
            income, expense = (
                WriteOnlyCell(ws, value=ln.income),
                WriteOnlyCell(ws, value=ln.expense),
            )
            income.number_format = expense.number_format = MONEY_FORMAT
            cells = [
                ln.date,
                safe_text(ln.order.number),
                safe_text(ln.order.client.name),
                safe_text(ln.title),
                safe_text(ln.category),
                income,
                expense,
                safe_text(ln.order.currency.code),
            ]
            if in_base:
                base_income = WriteOnlyCell(ws, value=ln.base_income)
                base_expense = WriteOnlyCell(ws, value=ln.base_expense)
                base_income.number_format = base_expense.number_format = MONEY_FORMAT
                cells += [base_income, base_expense, BASE_STATUS_TEXT.get(ln.bucket, ln.bucket)]
            ws.append(cells)
        if in_base:
            # курсовые разницы - отдельным листом и колонками, в доходы/расходы не входят
            filters = self.filters(request)
            base = debts_base.base_info(request.membership.company_id)
            flt = {
                "date_from": filters["date_from"],
                "date_to": filters["date_to"],
                "direction": None,
            }
            rows = debts_base.realized_rows(realized_queryset(flt), base["id"])
            write_realized_sheet(wb, base["code"], rows[:EXPORT_LIMIT])
        buffer = io.BytesIO()
        wb.save(buffer)
        today = company_today(request.membership.company_id)
        response = HttpResponse(buffer.getvalue(), content_type=CONTENT_TYPE)
        response["Content-Disposition"] = (
            f'attachment; filename="operations-{today.isoformat()}.xlsx"'
        )
        response["Cache-Control"] = "private, no-store"
        return response
