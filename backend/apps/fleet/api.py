from django.db import IntegrityError, transaction
from django.db.models import F, Q
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.permissions import ModuleRequired
from apps.billing.services import check_limit
from apps.core.api_permissions import SectionPermissionMixin
from apps.core.audit.mixins import AuditedMixin
from apps.core.models import Company
from apps.core.pagination import StandardPagination
from apps.core.tenancy import get_current_company_id

from . import services
from .models import FuelFill, Insurance, MileageReading, ServiceRecord, Vehicle, VehicleDocument
from .serializers import (
    FuelFillSerializer,
    InsuranceSerializer,
    MileageSerializer,
    ServiceRecordSerializer,
    VehicleDocumentSerializer,
    VehicleSerializer,
)

ORDERING_FIELDS = ("plate", "created_at", "year")
DUPLICATE_PLATE_MESSAGE = "Техника с таким госномером уже есть"


class _FleetPermissions(SectionPermissionMixin):
    permission_section = "fleet"

    def get_permissions(self):
        return [ModuleRequired("fleet")(), *super().get_permissions()]


class VehicleViewSet(AuditedMixin, _FleetPermissions, viewsets.ModelViewSet):
    serializer_class = VehicleSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = Vehicle.objects.prefetch_related("documents", "insurances")
        if self.action != "list":
            return qs
        p = self.request.query_params
        if q := (p.get("q") or "").strip():
            qs = qs.filter(
                Q(plate__icontains=q.replace(" ", "").upper())
                | Q(make__icontains=q)
                | Q(model__icontains=q)
                | Q(vin__icontains=q)
            )
        if kind := p.get("kind"):
            if kind not in dict(Vehicle.KINDS):
                raise ValidationError({"kind": "Допустимо: tractor, trailer, truck, other"})
            qs = qs.filter(kind=kind)
        if status := p.get("status"):
            if status not in dict(Vehicle.STATUSES):
                raise ValidationError({"status": "Допустимо: active, repair, inactive"})
            qs = qs.filter(status=status)
        ordering = p.get("ordering") or "plate"
        allowed = {*ORDERING_FIELDS, *(f"-{f}" for f in ORDERING_FIELDS)}
        if ordering not in allowed:
            raise ValidationError({"ordering": f"Допустимо: {', '.join(sorted(allowed))}"})
        expr = F(ordering.lstrip("-"))
        expr = expr.desc(nulls_last=True) if ordering.startswith("-") else expr.asc(nulls_last=True)
        return qs.order_by(expr, "id")

    @action(detail=True, methods=["get"], url_path="fuel-stats")
    def fuel_stats(self, request, pk=None):
        """Средний расход на 100 км по заправкам «до полного бака» и сегменты расчёта."""
        stats = services.fuel_stats(self.get_object())
        stats = {**stats, "liters": str(stats["liters"])}
        if stats["average_l_per_100km"] is not None:
            stats["average_l_per_100km"] = str(stats["average_l_per_100km"])
        stats["segments"] = [
            {**seg, "liters": str(seg["liters"]), "l_per_100km": str(seg["l_per_100km"])}
            for seg in stats["segments"]
        ]
        return Response(stats)

    def _enforce_limit(self):
        """Лимит max_vehicles: блокировка компании против гонок, считается неудалённая техника."""
        company = Company.objects.select_for_update().get(pk=get_current_company_id())
        check_limit(company, "max_vehicles", Vehicle.objects.count())

    def create(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                self._enforce_limit()
                return super().create(request, *args, **kwargs)
        except IntegrityError as exc:
            self._duplicate_or_raise(exc)

    def update(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                return super().update(request, *args, **kwargs)
        except IntegrityError as exc:
            self._duplicate_or_raise(exc)

    @staticmethod
    def _duplicate_or_raise(exc):
        constraint = getattr(getattr(exc.__cause__, "diag", None), "constraint_name", "") or ""
        if constraint != "vehicle_company_plate_uniq":
            raise exc
        raise serializers.ValidationError({"plate": [DUPLICATE_PLATE_MESSAGE]}) from None


class _ChildViewSet(AuditedMixin, _FleetPermissions, viewsets.ModelViewSet):
    model: type
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = self.model.objects.filter(vehicle__deleted_at__isnull=True)
        vehicle = self.request.query_params.get("vehicle")
        if self.action == "list" and vehicle:
            if not vehicle.isascii() or not vehicle.isdigit():
                raise ValidationError({"vehicle": "Ожидается числовой id"})
            qs = qs.filter(vehicle_id=int(vehicle))
        return qs.order_by("id")


class VehicleDocumentViewSet(_ChildViewSet):
    model = VehicleDocument
    serializer_class = VehicleDocumentSerializer


class InsuranceViewSet(_ChildViewSet):
    model = Insurance
    serializer_class = InsuranceSerializer


class _OperationsViewSet(_ChildViewSet):
    """Записи эксплуатации техники: фильтр по технике, плюс vehicle обязателен для фильтров."""

    filter_fields: tuple = ()

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == "list":
            for field in self.filter_fields:
                value = self.request.query_params.get(field)
                if value:
                    qs = qs.filter(**{field: value})
        return qs


class MileageViewSet(_OperationsViewSet):
    model = MileageReading
    serializer_class = MileageSerializer
    filter_fields = ("source",)

    def get_queryset(self):
        return super().get_queryset().order_by("-recorded_at", "-id")


class ServiceRecordViewSet(_OperationsViewSet):
    model = ServiceRecord
    serializer_class = ServiceRecordSerializer
    filter_fields = ("status", "kind")

    def _sync_mileage(self, instance):
        if instance.status == "done" and instance.odometer_km is not None:
            at = services.day_start(instance.done_date)
            services.record_mileage(instance.vehicle, instance.odometer_km, at, "service")

    def perform_create(self, serializer):
        with transaction.atomic():
            super().perform_create(serializer)
            self._sync_mileage(serializer.instance)

    def perform_update(self, serializer):
        with transaction.atomic():
            super().perform_update(serializer)
            self._sync_mileage(serializer.instance)


class FuelFillViewSet(_OperationsViewSet):
    model = FuelFill
    serializer_class = FuelFillSerializer
    filter_fields = ("fuel_type",)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        vehicle = self.request.query_params.get("vehicle")
        if vehicle and vehicle.isascii() and vehicle.isdigit() and self.action == "list":
            vehicle_obj = Vehicle.objects.filter(pk=int(vehicle)).first()
            if vehicle_obj is not None:
                segments = services.fuel_stats(vehicle_obj)["segments"]
                context["consumption"] = {s["fill"]: s["l_per_100km"] for s in segments}
        return context

    def get_queryset(self):
        return super().get_queryset().order_by("-filled_at", "-id")

    def perform_create(self, serializer):
        with transaction.atomic():
            super().perform_create(serializer)
            fill = serializer.instance
            services.record_mileage(fill.vehicle, fill.odometer_km, fill.filled_at, "fuel")

    def perform_update(self, serializer):
        with transaction.atomic():
            super().perform_update(serializer)
            fill = serializer.instance
            services.record_mileage(fill.vehicle, fill.odometer_km, fill.filled_at, "fuel")


class RemindersView(APIView):
    """ТО, документы и страховки, которые просрочены или скоро истекают."""

    def get_permissions(self):
        from apps.core.api_permissions import permission_required

        return [ModuleRequired("fleet")(), permission_required("fleet.view")()]

    def get(self, request):
        def number(name, default, limit):
            raw = request.query_params.get(name)
            if raw in (None, ""):
                return default
            if not raw.isascii() or not raw.isdigit() or int(raw) > limit:
                raise ValidationError({name: f"Ожидается число от 0 до {limit}"})
            return int(raw)

        vehicle = request.query_params.get("vehicle")
        if vehicle and (not vehicle.isascii() or not vehicle.isdigit()):
            raise ValidationError({"vehicle": "Ожидается числовой id"})
        items = services.reminders(
            days=number("days", 30, 3650),
            km_margin=number("km", 1000, 1_000_000),
            vehicle_id=int(vehicle) if vehicle else None,
        )
        return Response({"count": len(items), "results": items})
