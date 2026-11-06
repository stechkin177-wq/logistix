from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import permission_required
from apps.forwarding.finance_lines.models import company_today

from .. import debts, summary
from .serializers import money


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


class ClientDebtsView(ReportView):
    def get(self, request):
        return Response({"results": [debt_row(r) for r in debts.client_debts(self.today(request))]})


class CarrierDebtsView(ReportView):
    def get(self, request):
        return Response(
            {"results": [debt_row(r) for r in debts.carrier_debts(self.today(request))]}
        )


class SummaryView(ReportView):
    def get(self, request):
        data = summary.finance_summary(self.today(request))
        return Response(
            {
                k: (money(v) if k.endswith("_kzt") else (None if v is None else v))
                if k not in ("month_margin_pct",)
                else (None if v is None else money(v))
                for k, v in data.items()
            }
        )
