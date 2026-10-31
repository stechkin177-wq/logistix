from django.db.models import Exists, OuterRef, Prefetch, Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import SectionPermissionMixin, permission_required
from apps.core.audit.mixins import AuditedMixin
from apps.core.audit.services import client_ip
from apps.core.pagination import StandardPagination

from ..models import Consignment, ConsignmentPoint, Order, OrderStatusHistory
from .serializers import OrderSerializer, StatusChangeSerializer

ORDERING_FIELDS = ("created_at", "number")
DEFAULT_ORDERING = "-created_at"


def int_param(params, name):
    value = params.get(name)
    if value in (None, ""):
        return None
    if not value.isascii() or not value.isdigit():
        raise ValidationError({name: "Ожидается числовой id"})
    return int(value)


def consignments_prefetch() -> Prefetch:
    """Грузы заказа (без удалённых) по id, сразу с точками и справочниками: без N+1."""
    points = Prefetch(
        "points", queryset=ConsignmentPoint.objects.select_related("country", "method")
    )
    return Prefetch(
        "consignments",
        queryset=Consignment.objects.select_related("status", "packaging")
        .prefetch_related(points)
        .order_by("id"),
    )


def filter_orders(qs, params):
    """client (id), status (id), q (номер, клиент, название груза), ordering."""
    if (client := int_param(params, "client")) is not None:
        qs = qs.filter(client_id=client)
    if (status := int_param(params, "status")) is not None:
        qs = qs.filter(status_id=status)
    if q := (params.get("q") or "").strip():
        by_cargo = Exists(Consignment.objects.filter(order=OuterRef("pk"), name__icontains=q))
        qs = qs.filter(Q(number__icontains=q) | Q(client__name__icontains=q) | by_cargo)
    ordering = params.get("ordering") or DEFAULT_ORDERING
    allowed = {*ORDERING_FIELDS, *(f"-{f}" for f in ORDERING_FIELDS)}
    if ordering not in allowed:
        raise ValidationError({"ordering": f"Допустимо: {', '.join(sorted(allowed))}"})
    return qs.order_by(ordering, "-id" if ordering.startswith("-") else "id")


class OrderViewSet(AuditedMixin, SectionPermissionMixin, viewsets.ModelViewSet):
    permission_section = "orders"
    serializer_class = OrderSerializer
    pagination_class = StandardPagination

    def get_permissions(self):
        if self.action == "change_status":
            return [ModuleRequired("forwarding")(), permission_required("orders.update")()]
        return [ModuleRequired("forwarding")(), *super().get_permissions()]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["with_history"] = self.action != "list"
        return context

    def get_queryset(self):
        qs = Order.objects.select_related("client", "status", "manager").prefetch_related(
            "extra_managers", consignments_prefetch()
        )
        if self.action != "list":
            qs = qs.prefetch_related(
                Prefetch(
                    "history",
                    queryset=OrderStatusHistory.objects.select_related("from_status", "to_status"),
                )
            )
        else:
            qs = filter_orders(qs, self.request.query_params)
        return qs

    def perform_create(self, serializer):
        serializer.save()  # create_order сам пишет аудит заказа и его грузов

    def audit_extra_changes(self, instance):
        diff = getattr(instance, "_extra_managers_diff", None)
        return {"extra_managers": diff} if diff else {}

    @action(detail=True, methods=["post"], url_path="status")
    def change_status(self, request, pk=None):
        """Смена статуса: тело {"status": id значения order_status}."""
        order = self.get_object()
        serializer = StatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(order, request.user, ip=client_ip(request))
        fresh = self.get_queryset().get(pk=order.pk)
        return Response(self.get_serializer(fresh).data)
