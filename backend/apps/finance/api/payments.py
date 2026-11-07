from rest_framework import status, viewsets
from rest_framework.response import Response

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import permission_required
from apps.core.pagination import StandardPagination

from .. import payments as pay
from .. import periods
from ..models import Payment
from .filters import filter_payments
from .serializers import payment_data


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

    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response([payment_data(p) for p in page])

    def retrieve(self, request, pk=None):
        return Response(payment_data(self.get_object()))

    def destroy(self, request, pk=None):
        pay.delete_payment(
            self.get_object(),
            user=request.user,
            perms=periods.request_perms(request),
            adjust_reason=periods.request_adjust_reason(request),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
