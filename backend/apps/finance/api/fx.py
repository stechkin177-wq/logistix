"""API курсовых переоценок и разниц в базовой валюте (1.4.14, только engine=new).

Снимки (FxRevaluation) создаются при закрытии периода и по требованию; изменение и удаление
невозможны (методов PATCH/PUT/DELETE нет - 405). Просмотр - finance.view; создание по требованию -
finance.close_period ИЛИ finance.manage_settings. Курсовые разницы в доходы/расходы не попадают.
"""

import io

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import permission_required
from apps.core.pagination import StandardPagination
from apps.forwarding.finance_lines.models import company_today
from apps.forwarding.orders.export import (
    CONTENT_TYPE,
    MONEY_FORMAT,
    AnyAcceptNegotiation,
    safe_text,
)
from apps.forwarding.orders.filters import date_param

from .. import debts_base, fx_revaluation
from ..engine import use_new_engine
from ..errors import FinanceError
from ..models import FxRevaluation, FxRevaluationLine, Payment
from .reports import new_debts_response
from .serializers import jsonable

NOT_NEW = (
    "engine_not_new",
    "Показатели в базовой валюте доступны только при новом финансовом учёте",
)


def assert_new_engine(request) -> None:
    if not use_new_engine(request.membership.company_id):
        raise FinanceError(*NOT_NEW, status_code=409)


def any_permission(*codes):
    classes = [permission_required(c) for c in codes]

    class _AnyPermission(BasePermission):
        def has_permission(self, request, view):
            return any(cls().has_permission(request, view) for cls in classes)

    return _AnyPermission


def _perm(*codes):
    guard = permission_required(codes[0]) if len(codes) == 1 else any_permission(*codes)
    return [ModuleRequired("finance")(), guard()]


def revaluation_data(r: FxRevaluation) -> dict:
    return jsonable(
        {
            "id": r.pk,
            "as_of": r.as_of,
            "kind": r.kind,
            "base_currency": r.base_currency.code,
            "period": (
                None
                if r.period_id is None
                else {"id": r.period_id, "year": r.period.year, "month": r.period.month}
            ),
            "created_by": r.created_by.email if r.created_by_id else None,
            "created_at": r.created_at,
            "summary": r.summary,
        }
    )


def line_data(line: FxRevaluationLine) -> dict:
    return jsonable(
        {
            "id": line.pk,
            "invoice": line.invoice_id,
            "direction": line.direction,
            "currency": line.currency.code,
            "open_balance": line.open_balance,
            "invoice_rate_base": line.invoice_rate_base,
            "carrying_base": line.carrying_base,
            "applied_rate": line.applied_rate,
            "applied_rate_date": line.applied_rate_date,
            "applied_rate_source": line.applied_rate_source,
            "current_base": line.current_base,
            "unrealized_diff": line.unrealized_diff,
            "flags": line.flags,
        }
    )


class FxRevaluationsView(APIView):
    """GET - список снимков; POST {as_of} - снимок по требованию (на дату не позже сегодня)."""

    def get_permissions(self):
        if self.request.method == "POST":
            return _perm("finance.close_period", "finance.manage_settings")
        return _perm("finance.view")

    def get(self, request):
        qs = FxRevaluation.objects.select_related("base_currency", "period", "created_by").order_by(
            "-id"
        )
        if kind := request.query_params.get("kind"):
            qs = qs.filter(kind=kind)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response([revaluation_data(r) for r in page])

    def post(self, request):
        assert_new_engine(request)
        raw = request.data.get("as_of") if hasattr(request.data, "get") else None
        as_of = date_param({"as_of": str(raw)}, "as_of") if raw else None
        if as_of is None:
            raise FinanceError("as_of_required", "Укажите дату отчёта as_of (YYYY-MM-DD)")
        if as_of > company_today(request.membership.company_id):
            raise FinanceError("as_of_future", "Дата отчёта не может быть в будущем")
        reval = fx_revaluation.create_revaluation(
            request.membership.company_id, as_of, "report", request.user
        )
        fresh = FxRevaluation.objects.select_related("base_currency", "period", "created_by").get(
            pk=reval.pk
        )
        return Response(revaluation_data(fresh), status=status.HTTP_201_CREATED)


class FxRevaluationView(APIView):
    """GET - карточка снимка (только чтение: PATCH/PUT/DELETE отсутствуют)."""

    def get_permissions(self):
        return _perm("finance.view")

    def get(self, request, pk):
        reval = (
            FxRevaluation.objects.select_related("base_currency", "period", "created_by")
            .filter(pk=pk)
            .first()
        )
        if reval is None:
            raise NotFound("Снимок не найден")
        return Response(revaluation_data(reval))


class FxRevaluationLinesView(APIView):
    def get_permissions(self):
        return _perm("finance.view")

    def get(self, request, pk):
        reval = FxRevaluation.objects.filter(pk=pk).first()
        if reval is None:
            raise NotFound("Снимок не найден")
        paginator = StandardPagination()
        page = paginator.paginate_queryset(
            reval.lines.select_related("currency").order_by("id"), request, view=self
        )
        return paginator.get_paginated_response([line_data(x) for x in page])


# --- реализованные курсовые разницы (по оплатам) ----------------------------------------


def realized_filters(request) -> dict:
    p = request.query_params
    direction = p.get("direction")
    if direction and direction not in ("out", "in"):
        raise FinanceError("direction_invalid", "Допустимо: out или in")
    return {
        "date_from": date_param(p, "date_from"),
        "date_to": date_param(p, "date_to"),
        "direction": direction,
    }


def realized_queryset(flt: dict):
    qs = Payment.objects.filter(invoice__status="issued")
    if flt["date_from"]:
        qs = qs.filter(date__gte=flt["date_from"])
    if flt["date_to"]:
        qs = qs.filter(date__lte=flt["date_to"])
    if flt["direction"]:
        qs = qs.filter(invoice__direction=flt["direction"])
    return qs


def fx_row(r: dict) -> dict:
    return jsonable(
        {
            "payment": r["id"],
            "date": r["date"],
            "invoice": {
                "id": r["invoice_id"],
                "number": r["invoice__number"],
                "direction": r["invoice__direction"],
            },
            "currency": r["invoice__currency__code"],
            "amount": r["amount"],
            "invoice_rate_to_base": r["invoice__rate_to_base"],
            "payment_rate_to_base": r["rate_to_base"],
            "fx_realized_base": r["fx_realized_base"],
            "fx_status": r["fx_status"],
        }
    )


class FxDifferencesView(APIView):
    """Раздел журнала «Курсовые разницы»: реализованные разницы по оплатам, отдельно от
    доходов и расходов. Нереализованная - в отчётах по долгам и снимках переоценки."""

    def get_permissions(self):
        return _perm("finance.view")

    def get(self, request):
        assert_new_engine(request)
        base = debts_base.base_info(request.membership.company_id)
        rows = debts_base.realized_rows(realized_queryset(realized_filters(request)), base["id"])
        paginator = StandardPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        response = paginator.get_paginated_response([fx_row(r) for r in page])
        response.data["summary"] = jsonable(
            {"base_currency": base["code"], **debts_base.realized_summary(rows)}
        )
        return response


# --- Excel ------------------------------------------------------------------------------

STATUS_TEXT = {
    "ok": "",
    "no_rate": "нет курса на дату отчёта",
    "prior_base": "в прежней базовой валюте",
    "no_base_rate": "без базового курса счёта",
}


def _header(ws, titles):
    cells = []
    for title in titles:
        cell = WriteOnlyCell(ws, value=title)
        cell.font = Font(bold=True)
        cells.append(cell)
    ws.append(cells)


def _money_cell(ws, value):
    cell = WriteOnlyCell(ws, value=value)
    cell.number_format = MONEY_FORMAT
    return cell


def write_realized_sheet(wb, base_code: str, rows: list[dict]) -> None:
    ws = wb.create_sheet("Курсовые разницы")
    _header(
        ws,
        [
            "Дата оплаты",
            "Счёт",
            "Направление",
            "Валюта",
            "Сумма оплаты",
            "Курс счёта к базе",
            "Курс оплаты к базе",
            f"Курсовая разница реализованная, {base_code}",
            "Пометка",
        ],
    )
    for r in rows:
        ws.append(
            [
                r["date"],
                safe_text(r["invoice__number"]),
                "Клиент" if r["invoice__direction"] == "out" else "Перевозчик",
                safe_text(r["invoice__currency__code"]),
                _money_cell(ws, r["amount"]),
                r["invoice__rate_to_base"],
                r["rate_to_base"],
                _money_cell(ws, r["fx_realized_base"]),
                STATUS_TEXT.get(r["fx_status"], r["fx_status"]),
            ]
        )


class DebtsExportMixin(APIView):
    content_negotiation_class = AnyAcceptNegotiation
    direction = "out"

    def get_permissions(self):
        return _perm("finance.view")

    def get(self, request):
        assert_new_engine(request)
        today = company_today(request.membership.company_id)
        report = new_debts_response(request, self.direction, today)
        code = report["base_currency"]
        wb = Workbook(write_only=True)
        ws = wb.create_sheet("Клиенты" if self.direction == "out" else "Перевозчики")
        _header(
            ws,
            [
                "Контрагент",
                "Валюта",
                "Остаток, исходная валюта",
                f"Эквивалент в базе, {code}",
                "Курс на дату отчёта",
                "Дата курса",
                "Источник курса",
                "Просрочено, исходная валюта",
                f"Просрочено, {code}",
                f"Балансовая стоимость, {code}",
                f"Курсовая разница нереализованная, {code}",
                "Пометка о неполноте",
            ],
        )
        for row in report["results"]:
            for cur_code, cell in sorted(row["by_currency"].items()):
                if not cell["balance"]:
                    continue
                rate = cell["applied_rate"] or {}
                notes = [
                    STATUS_TEXT[reason]
                    for reason in debts_base.REASONS
                    if cell["excluded"][reason]["count"]
                ]
                ws.append(
                    [
                        safe_text(row["name"]),
                        safe_text(cur_code),
                        _money_cell(ws, cell["balance"]),
                        _money_cell(ws, cell["balance_base"]),
                        rate.get("rate"),
                        rate.get("rate_date"),
                        rate.get("source", ""),
                        _money_cell(ws, cell["overdue"]),
                        _money_cell(ws, cell["overdue_base"]),
                        _money_cell(ws, cell["carrying_base"]),
                        _money_cell(ws, cell["unrealized_diff"]),
                        "; ".join(notes),
                    ]
                )
        buffer = io.BytesIO()
        wb.save(buffer)
        response = HttpResponse(buffer.getvalue(), content_type=CONTENT_TYPE)
        response["Content-Disposition"] = (
            f'attachment; filename="debts-{self.direction}-{report["as_of"].isoformat()}.xlsx"'
        )
        response["Cache-Control"] = "private, no-store"
        return response


class ClientDebtsExportView(DebtsExportMixin):
    direction = "out"


class CarrierDebtsExportView(DebtsExportMixin):
    direction = "in"


__all__ = [
    "FxRevaluationsView",
    "FxRevaluationView",
    "FxRevaluationLinesView",
    "FxDifferencesView",
    "ClientDebtsExportView",
    "CarrierDebtsExportView",
    "write_realized_sheet",
    "realized_queryset",
]
