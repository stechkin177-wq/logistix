from rest_framework import status, viewsets
from rest_framework.response import Response

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import permission_required
from apps.core.pagination import StandardPagination

from .. import debts_base, periods
from .. import payments as pay
from ..engine import use_new_engine
from ..models import Payment
from .filters import filter_payments
from .serializers import jsonable, payment_data


class PaymentViewSet(viewsets.GenericViewSet):
    """Журнал оплат: /api/finance/payments/ (создание - через счёт)."""

    pagination_class = StandardPagination

    def get_permissions(self):
        code = "finance.delete" if self.action == "destroy" else "finance.view"
        return [ModuleRequired("forwarding")(), permission_required(code)()]

    def get_queryset(self):
        qs = Payment.objects.select_related("invoice").order_by("-date", "-id")
        if self.action == "list":
            qs = filter_payments(qs, self.request.query_params)
        return qs

    def base(self, request):
        """Базовая валюта компании при engine=new, иначе None (формат ответа не меняется)."""
        cid = request.membership.company_id
        return debts_base.base_info(cid) if use_new_engine(cid) else None

    def list(self, request):
        base = self.base(request)
        qs = self.get_queryset()
        page = self.paginate_queryset(qs)
        response = self.get_paginated_response([payment_data(p, base) for p in page])
        if base is not None:
            # реализованная курсовая разница по ВСЕМ оплатам фильтра, отдельным полем (не в доходах)
            summary = debts_base.realized_summary(debts_base.realized_rows(qs, base["id"]))
            response.data["summary"] = jsonable({"base_currency": base["code"], **summary})
        return response

    def retrieve(self, request, pk=None):
        return Response(payment_data(self.get_object(), self.base(request)))

    def destroy(self, request, pk=None):
        pay.delete_payment(
            self.get_object(),
            user=request.user,
            perms=periods.request_perms(request),
            adjust_reason=periods.request_adjust_reason(request),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
