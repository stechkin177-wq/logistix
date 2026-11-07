from copy import copy

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import permission_required
from apps.core.audit import services as audit
from apps.core.audit.mixins import AuditedMixin
from apps.core.pagination import StandardPagination
from apps.forwarding.finance_lines.models import company_today

from .. import invoices as svc
from .. import payments as pay
from .. import periods
from ..errors import FinanceError
from ..models import Invoice
from .filters import filter_invoices
from .serializers import (
    InvoiceWriteSerializer,
    PaymentWriteSerializer,
    invoice_data,
    payment_data,
)

PERMISSIONS = {
    "list": "finance.view",
    "retrieve": "finance.view",
    "create": "finance.create",
    "partial_update": "finance.update",
    "destroy": "finance.delete",
    "issue": "finance.update",
    "cancel": "finance.cancel_invoice",
}


class InvoiceViewSet(AuditedMixin, viewsets.GenericViewSet):
    """Счета компании: /api/finance/invoices/ (+ issue, cancel, payments)."""

    pagination_class = StandardPagination

    def get_permissions(self):
        code = PERMISSIONS.get(self.action)
        if self.action == "payments":
            code = "finance.create" if self.request.method == "POST" else "finance.view"
        return [ModuleRequired("forwarding")(), permission_required(code or "finance.delete")()]

    def today(self):
        return company_today(self.request.membership.company_id)

    def get_queryset(self):
        qs = svc.annotate_paid(
            Invoice.objects.select_related(
                "client", "carrier", "order", "trip", "currency", "vat_rate"
            ).prefetch_related("items")
        )
        if self.action == "list":
            qs = filter_invoices(qs, self.request.query_params, self.today())
        return qs

    def respond(self, invoice, code=status.HTTP_200_OK):
        fresh = self.get_queryset().get(pk=invoice.pk)
        return Response(invoice_data(fresh, self.today()), status=code)

    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        today = self.today()
        return self.get_paginated_response([invoice_data(i, today) for i in page])

    def retrieve(self, request, pk=None):
        return self.respond(self.get_object())

    def create(self, request):
        ser = InvoiceWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = dict(ser.validated_data)
        invoice = svc.create_draft(
            direction=data.pop("direction"),
            party=data.pop("party"),
            order=data.pop("order", None),
            trip=data.pop("trip", None),
            currency=data.pop("currency"),
            vat_rate=data.pop("vat_rate"),
            items=data.pop("items", []),
            user=request.user,
            **data,
        )
        self.audit_created(invoice)
        return self.respond(invoice, status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        invoice = self.get_object()
        ser = InvoiceWriteSerializer(invoice, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        data = dict(ser.validated_data)
        data.pop("direction", None)
        before = audit.snapshot(invoice)
        if invoice.status == "draft":
            items = data.pop("items", None)
            invoice = svc.update_draft(invoice, items=items, **data)
        else:
            if "items" in data or set(data) - set(svc.LIGHT_FIELDS):
                raise FinanceError("invoice_not_editable", "Выставленный счёт нельзя изменить")
            invoice = svc.update_issued(invoice, **data)
        self.audit_updated(before, invoice)
        return self.respond(invoice)

    def destroy(self, request, pk=None):
        invoice = self.get_object()
        before = copy(invoice)
        svc.delete_draft(invoice)
        self.audit_deleted(before)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="issue")
    def issue(self, request, pk=None):
        invoice = self.get_object()
        reason = (
            (request.data.get("override_reason") or "").strip()
            if hasattr(request.data, "get")
            else ""
        )
        can_override = "finance.override_limit" in request.membership.role.permissions
        if reason and not can_override:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Недостаточно прав для обхода кредитного лимита")
        svc.issue(
            invoice,
            user=request.user,
            can_override=can_override,
            override_reason=reason,
            perms=periods.request_perms(request),
            adjust_reason=periods.request_adjust_reason(request),
        )
        return self.respond(invoice)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        svc.cancel(
            self.get_object(),
            user=request.user,
            perms=periods.request_perms(request),
            adjust_reason=periods.request_adjust_reason(request),
        )
        return self.respond(self.get_object())

    @action(detail=True, methods=["get", "post"], url_path="payments")
    def payments(self, request, pk=None):
        invoice = self.get_object()
        if request.method == "POST":
            ser = PaymentWriteSerializer(data=request.data)
            ser.is_valid(raise_exception=True)
            payment = pay.add_payment(
                invoice,
                user=request.user,
                perms=periods.request_perms(request),
                adjust_reason=periods.request_adjust_reason(request),
                **ser.validated_data,
            )
            payment.invoice = invoice
            return Response(payment_data(payment), status=status.HTTP_201_CREATED)
        qs = invoice.payments.select_related("invoice")
        page = self.paginate_queryset(qs)
        return self.get_paginated_response([payment_data(p) for p in page])
