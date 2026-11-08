"""API передач груза и событий (этап 1.5-D4).

События и инициирование передач - действия груза (/api/consignments/{id}/events|transfers/);
подтверждение и сторно - /api/transfers/{id}/confirm|reverse/ (право consignments.transfer).
"""

from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import permission_any, permission_required
from apps.core.audit.services import client_ip
from apps.core.pagination import StandardPagination

from ..orders.filters import flag_param, int_param
from . import services
from .models import CargoTransfer, ConsignmentEvent
from .serializers import (
    EventCreateSerializer,
    EventSerializer,
    TransferCreateSerializer,
    TransferSerializer,
)

TRANSFER_PERMISSION = "consignments.transfer"


def transfers_queryset():
    return CargoTransfer.objects.select_related(
        "consignment",
        "consignment__order",
        "to_stop",
        "from_trip",
        "to_trip",
        "from_carrier",
        "to_carrier",
    ).prefetch_related("reversals")


def consignment_permissions(request, action_name):
    """Права действий events/transfers груза: просмотр - consignments.view, событие -
    consignments.update, инициирование передачи - consignments.transfer ИЛИ consignments.update."""
    read = request.method in ("GET", "HEAD", "OPTIONS")
    if read:
        return [permission_required("consignments.view")()]
    if action_name == "transfers":
        return [permission_any(TRANSFER_PERMISSION, "consignments.update")()]
    return [permission_required("consignments.update")()]


class ConsignmentTrackingMixin:
    """Действия events и transfers для ConsignmentViewSet."""

    @action(detail=True, methods=["get", "post"], url_path="events")
    def events(self, request, pk=None):
        consignment = self.get_object()
        if request.method == "GET":
            rows = ConsignmentEvent.objects.filter(consignment=consignment).select_related(
                "stop", "trip"
            )
            return Response(EventSerializer(rows, many=True).data)
        body = EventCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        d = body.validated_data
        event, created = services.record_event(
            consignment,
            d["event_type"],
            stop=d.get("stop"),
            leg=d.get("leg"),
            trip=d.get("trip"),
            occurred_at=d.get("occurred_at"),
            user=request.user,
            source=d["source"],
            note=d["note"],
            ip=client_ip(request),
        )
        code = http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK
        return Response(EventSerializer(event).data, status=code)

    @action(detail=True, methods=["get", "post"], url_path="transfers")
    def transfers(self, request, pk=None):
        consignment = self.get_object()
        if request.method == "GET":
            rows = transfers_queryset().filter(consignment=consignment)
            return Response(TransferSerializer(rows, many=True).data)
        body = TransferCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        d = dict(body.validated_data)
        source = d.pop("source")
        transfer = services.initiate_transfer(
            consignment, d, request.user, source=source, ip=client_ip(request)
        )
        fresh = transfers_queryset().get(pk=transfer.pk)
        return Response(TransferSerializer(fresh).data, status=http_status.HTTP_201_CREATED)


class TransferViewSet(viewsets.ReadOnlyModelViewSet):
    """Список передач и подтверждение/сторно."""

    serializer_class = TransferSerializer
    pagination_class = StandardPagination

    def get_permissions(self):
        base = ModuleRequired("forwarding")()
        if self.action in ("confirm", "reverse"):
            return [base, permission_required(TRANSFER_PERMISSION)()]
        return [base, permission_required("consignments.view")()]

    def get_queryset(self):
        qs = transfers_queryset().filter(consignment__order__deleted_at__isnull=True)
        if self.action == "list":
            p = self.request.query_params
            if (v := int_param(p, "consignment")) is not None:
                qs = qs.filter(consignment_id=v)
            if (v := int_param(p, "order")) is not None:
                qs = qs.filter(consignment__order_id=v)
            if (v := int_param(p, "trip")) is not None:
                from django.db.models import Q

                qs = qs.filter(Q(from_trip_id=v) | Q(to_trip_id=v))
            if status := (p.get("status") or "").strip():
                qs = qs.filter(status=status)
            if kind := (p.get("kind") or "").strip():
                qs = qs.filter(transfer_kind=kind)
            if flag_param(p, "pending"):  # ждут подтверждения: инициированные без сторно
                qs = qs.filter(status=CargoTransfer.INITIATED, reversals__isnull=True)
        return qs.order_by("-transferred_at", "-id")

    def _out(self, transfer):
        return Response(TransferSerializer(transfers_queryset().get(pk=transfer.pk)).data)

    @action(detail=True, methods=["post"], url_path="confirm")
    def confirm(self, request, pk=None):
        transfer = self.get_object()
        done = services.confirm_transfer(transfer, request.user, ip=client_ip(request))
        return self._out(done)

    @action(detail=True, methods=["post"], url_path="reverse")
    def reverse(self, request, pk=None):
        transfer = self.get_object()
        note = (request.data.get("note") or "") if hasattr(request.data, "get") else ""
        storno = services.reverse_transfer(transfer, request.user, note=note, ip=client_ip(request))
        return Response(
            TransferSerializer(transfers_queryset().get(pk=storno.pk)).data,
            status=http_status.HTTP_201_CREATED,
        )
