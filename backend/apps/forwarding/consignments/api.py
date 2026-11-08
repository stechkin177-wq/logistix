from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from rest_framework import viewsets

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import SectionPermissionMixin
from apps.core.audit.mixins import AuditedMixin
from apps.core.pagination import StandardPagination

from ..models import Consignment, ConsignmentPoint, TripConsignment
from ..orders.filters import flag_param, int_param
from ..tracking.api import ConsignmentTrackingMixin, consignment_permissions
from .serializers import ConsignmentSerializer


class ConsignmentViewSet(
    ConsignmentTrackingMixin, AuditedMixin, SectionPermissionMixin, viewsets.ModelViewSet
):
    permission_section = "consignments"
    serializer_class = ConsignmentSerializer
    pagination_class = StandardPagination

    def get_permissions(self):
        if self.action in ("events", "transfers"):
            return [
                ModuleRequired("logistics")(),
                *consignment_permissions(self.request, self.action),
            ]
        return [ModuleRequired("logistics")(), *super().get_permissions()]

    def get_queryset(self):
        qs = (
            Consignment.objects.filter(order__deleted_at__isnull=True)  # груз скрыт с заказом
            .select_related("order", "order__client", "status", "packaging")
            .annotate(
                # рейсы, а не участки: груз может ехать несколькими участками одного рейса
                trips_count=Count(
                    "trip_links__trip",
                    filter=Q(trip_links__trip__deleted_at__isnull=True),
                    distinct=True,
                )
            )
            .prefetch_related(
                Prefetch(
                    "points",
                    queryset=ConsignmentPoint.objects.select_related("country", "method"),
                ),
                Prefetch(
                    "trip_links",
                    queryset=TripConsignment.objects.select_related(
                        "trip", "from_stop", "to_stop"
                    ).order_by("leg_seq", "id"),
                ),
            )
        )
        if self.action == "list":
            params = self.request.query_params
            if (order := int_param(params, "order")) is not None:
                qs = qs.filter(order_id=order)
            if (client := int_param(params, "client")) is not None:
                qs = qs.filter(order__client_id=client)
            if flag_param(params, "without_trip"):  # очередь распределения по рейсам
                in_trip = TripConsignment.objects.filter(
                    consignment=OuterRef("pk"), trip__deleted_at__isnull=True
                )
                qs = qs.filter(~Exists(in_trip))
            if (location := (params.get("location_status") or "").strip()) in dict(
                Consignment.LOCATION_STATUSES
            ):
                qs = qs.filter(location_status=location)
            if q := (params.get("q") or "").strip():
                qs = qs.filter(name__icontains=q)
            qs = qs.order_by("id")
        return qs

    def audit_extra_changes(self, instance):
        if not getattr(instance, "_points_changed", False):
            return {}
        extra = {"points": "changed"}
        if getattr(instance, "_stops_changed", False):
            extra["stops"] = "changed"
        return extra
