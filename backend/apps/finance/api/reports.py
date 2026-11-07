from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import permission_required
from apps.forwarding.finance_lines.models import company_today
from apps.forwarding.orders.filters import date_param

from .. import debts, debts_base, fx_revaluation, summary
from ..engine import use_new_engine
from ..errors import FinanceError
from ..models import FinancialPeriod
from .serializers import excluded_data, jsonable, money


class ReportView(APIView):
    def get_permissions(self):
        return [ModuleRequired("forwarding")(), permission_required("finance.view")()]

    def today(self, request):
        return company_today(request.membership.company_id)


def debt_row(row: dict) -> dict:
    out = {
        k: (money(v) if k.endswith("_kzt") else v)
        for k, v in row.items()
        if k not in ("by_currency", "credit_limit", "limit_usage_pct")
    }
    out["by_currency"] = {
        c: {k: money(v) for k, v in m.items()} for c, m in row["by_currency"].items()
    }
    if "credit_limit" in row:
        out["credit_limit"] = money(row["credit_limit"])
        pct = row["limit_usage_pct"]
        out["limit_usage_pct"] = None if pct is None else money(pct)
    return out


def report_period(request):
    """?period=YYYY-MM -> (год, месяц) или None; неверное значение - 400."""
    raw = (request.query_params.get("period") or "").strip()
    if not raw:
        return None
    try:
        year, month = (int(x) for x in raw.split("-"))
        if not (1 <= month <= 12 and year >= 1):
            raise ValueError
    except ValueError:
        raise ValidationError({"period": "Ожидается YYYY-MM"}) from None
    return year, month


def new_debts_response(request, direction, today) -> dict:
    """Задолженность engine=new: живой отчёт на as_of либо снимок закрытого периода (period)."""
    period = report_period(request)
    if period is not None:
        closed = FinancialPeriod.objects.filter(
            year=period[0], month=period[1], status="closed"
        ).exists()
        reval = fx_revaluation.snapshot_for_period(*period) if closed else None
        if reval is None:
            raise NotFound("Снимок переоценки закрытого периода не найден")
        return fx_revaluation.snapshot_report(reval, direction)
    as_of = date_param(request.query_params, "as_of") or today
    if as_of > today:
        raise FinanceError("as_of_future", "Дата отчёта не может быть в будущем")
    return debts_base.debts_report(direction, as_of)


def debts_view_response(request, direction, today, legacy_rows) -> Response:
    if not use_new_engine(request.membership.company_id):
        return Response({"results": [debt_row(r) for r in legacy_rows()]})
    return Response(jsonable(new_debts_response(request, direction, today)))


class ClientDebtsView(ReportView):
    def get(self, request):
        today = self.today(request)
        return debts_view_response(request, "out", today, lambda: debts.client_debts(today))


class CarrierDebtsView(ReportView):
    def get(self, request):
        today = self.today(request)
        return debts_view_response(request, "in", today, lambda: debts.carrier_debts(today))


class SummaryView(ReportView):
    def get(self, request):
        data = summary.finance_summary(self.today(request))
        excluded = excluded_data(data.pop("excluded", None))
        out = {
            k: (money(v) if k.endswith("_kzt") else (None if v is None else v))
            if k not in ("month_margin_pct",)
            else (None if v is None else money(v))
            for k, v in data.items()
        }
        out["excluded"] = excluded
        out["is_partial"] = excluded is not None
        return Response(jsonable(out))
