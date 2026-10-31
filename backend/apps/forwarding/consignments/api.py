from django.db.models import Prefetch
from rest_framework import viewsets

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import SectionPermissionMixin
from apps.core.audit.mixins import AuditedMixin
from apps.core.pagination import StandardPagination

from ..models import Consignment, ConsignmentPoint
from ..orders.api import int_param
from .serializers import ConsignmentSerializer


class ConsignmentViewSet(AuditedMixin, SectionPermissionMixin, viewsets.ModelViewSet):
    permission_section = "consignments"
    serializer_class = ConsignmentSerializer
    pagination_class = StandardPagination

    def get_permissions(self):
        return [ModuleRequired("forwarding")(), *super().get_permissions()]

    def get_queryset(self):
        qs = (
            Consignment.objects.filter(order__deleted_at__isnull=True)  # груз скрыт с заказом
            .select_related("order", "status", "packaging")
            .prefetch_related(
                Prefetch(
                    "points",
                    queryset=ConsignmentPoint.objects.select_related("country", "method"),
                )
            )
        )
        if self.action == "list":
            params = self.request.query_params
            if (order := int_param(params, "order")) is not None:
                qs = qs.filter(order_id=order)
            if q := (params.get("q") or "").strip():
                qs = qs.filter(name__icontains=q)
            qs = qs.order_by("id")
        return qs

    def audit_extra_changes(self, instance):
        return {"points": "changed"} if getattr(instance, "_points_changed", False) else {}
