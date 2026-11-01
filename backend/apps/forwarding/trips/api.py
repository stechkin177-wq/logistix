from contextlib import contextmanager

from django.db import OperationalError
from django.db.models import Exists, OuterRef, Prefetch, Q
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import SectionPermissionMixin, permission_required
from apps.core.audit.mixins import AuditedMixin
from apps.core.audit.services import client_ip
from apps.core.pagination import StandardPagination

from ..models import Consignment, Trip
from ..orders.filters import flag_param, int_param
from .serializers import (
    ReassignSerializer,
    TripCreateSerializer,
    TripSerializer,
    TripStatusSerializer,
)
from .services import ConcurrentChange, is_concurrency_failure


@contextmanager
def concurrency_guard():
    """Взаимоблокировка/сбой сериализации (только эти pgcode) -> 409 вместо 500."""
    try:
        yield
    except OperationalError as exc:
        if not is_concurrency_failure(exc):
            raise
        raise ConcurrentChange() from None


UPDATE_ACTIONS = ("reassign", "change_status")


def filter_trips(qs, params):
    """status (id), carrier (id), only_consolidated (1), q (номер, перевозчик, название груза)."""
    if (status := int_param(params, "status")) is not None:
        qs = qs.filter(status_id=status)
    if (carrier := int_param(params, "carrier")) is not None:
        qs = qs.filter(carrier_id=carrier)
    if flag_param(params, "only_consolidated"):
        qs = qs.filter(is_consolidated=True)
    if q := (params.get("q") or "").strip():
        by_cargo = Exists(
            Consignment.objects.filter(trip_links__trip=OuterRef("pk"), name__icontains=q)
        )
        qs = qs.filter(Q(number__icontains=q) | Q(carrier__name__icontains=q) | by_cargo)
    return qs.order_by("-created_at", "-id")


class TripViewSet(AuditedMixin, SectionPermissionMixin, viewsets.ModelViewSet):
    permission_section = "trips"
    pagination_class = StandardPagination

    def get_serializer_class(self):
        return TripCreateSerializer if self.action == "create" else TripSerializer

    def get_permissions(self):
        if self.action in UPDATE_ACTIONS:
            return [ModuleRequired("forwarding")(), permission_required("trips.update")()]
        return [ModuleRequired("forwarding")(), *super().get_permissions()]

    def get_queryset(self):
        qs = Trip.objects.select_related("carrier", "status").prefetch_related(
            Prefetch(
                "consignments",
                # действующие грузы: груз и его заказ не удалены; одним запросом вместе с заказом
                queryset=Consignment.objects.filter(order__deleted_at__isnull=True)
                .select_related("order")
                .order_by("id"),
            )
        )
        if self.action == "list":
            qs = filter_trips(qs, self.request.query_params)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with concurrency_guard():
            trip = serializer.save()  # create_trip сам пишет аудит
        return Response(self._output(trip), status=http_status.HTTP_201_CREATED)

    def _output(self, trip):
        fresh = self.get_queryset().get(pk=trip.pk)
        return TripSerializer(fresh, context=self.get_serializer_context()).data

    @action(detail=True, methods=["post"], url_path="reassign")
    def reassign(self, request, pk=None):
        """Замена грузов рейса: тело {"consignment_ids": [id, ...]}."""
        trip = self.get_object()
        serializer = ReassignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with concurrency_guard():
            serializer.save(trip, request.user, ip=client_ip(request))
        return Response(self._output(trip))

    @action(detail=True, methods=["post"], url_path="status")
    def change_status(self, request, pk=None):
        """Смена статуса: тело {"status": id значения trip_status}."""
        trip = self.get_object()
        serializer = TripStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with concurrency_guard():
            serializer.save(trip, request.user, ip=client_ip(request))
        return Response(self._output(trip))
