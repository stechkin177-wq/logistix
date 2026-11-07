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

from .. import operations as ops
from .serializers import money

HEADERS = ["Дата", "Заказ", "Клиент", "Название", "Категория", "Доход", "Расход", "Валюта"]


class OperationsMixin:
    def get_permissions(self):
        return [ModuleRequired("forwarding")(), permission_required("finance.view")()]

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
    return {
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
        wb = Workbook(write_only=True)
        ws = wb.create_sheet("Операции")
        head = []
        for title in HEADERS:
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
            ws.append(
                [
                    ln.date,
                    safe_text(ln.order.number),
                    safe_text(ln.order.client.name),
                    safe_text(ln.title),
                    safe_text(ln.category),
                    income,
                    expense,
                    safe_text(ln.order.currency.code),
                ]
            )
        buffer = io.BytesIO()
        wb.save(buffer)
        today = company_today(request.membership.company_id)
        response = HttpResponse(buffer.getvalue(), content_type=CONTENT_TYPE)
        response["Content-Disposition"] = (
            f'attachment; filename="operations-{today.isoformat()}.xlsx"'
        )
        response["Cache-Control"] = "private, no-store"
        return response
