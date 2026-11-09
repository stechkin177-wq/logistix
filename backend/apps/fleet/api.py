from django.db import IntegrityError, transaction
from django.db.models import F, Q
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import SectionPermissionMixin
from apps.core.audit.mixins import AuditedMixin
from apps.core.pagination import StandardPagination

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
        qs = Vehicle.objects.prefetch_related("documents__doc_type", "insurances")
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

    @action(detail=True, methods=["get"], url_path="mileage-check")
    def mileage_check(self, request, pk=None):
        """Официальный пробег, пробег по GPS и разница (если включено «Сверять пробег по GPS»)."""
        return Response(services.mileage_check(self.get_object()))

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

    def create(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
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


class MileageViewSet(_FleetPermissions, viewsets.ReadOnlyModelViewSet):
    """История ОФИЦИАЛЬНОГО пробега (чтение). Пишется только при выезде и завершении рейса."""

    serializer_class = MileageSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = MileageReading.objects.filter(vehicle__deleted_at__isnull=True)
        vehicle = self.request.query_params.get("vehicle")
        if self.action == "list" and vehicle:
            if not vehicle.isascii() or not vehicle.isdigit():
                raise ValidationError({"vehicle": "Ожидается числовой id"})
            qs = qs.filter(vehicle_id=int(vehicle))
        return qs.order_by("-recorded_at", "-id")


class ServiceRecordViewSet(_OperationsViewSet):
    model = ServiceRecord
    serializer_class = ServiceRecordSerializer
    filter_fields = ("status", "kind")

    # odometer_km в обслуживании - справочный: официальный пробег не меняется


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

    # odometer_km в заправке - справочный: нужен для расчёта расхода, официальный пробег не меняется


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


class FleetSettingsView(APIView):
    """Настройки автопарка компании: допустимое расхождение пробега с GPS (км)."""

    def get_permissions(self):
        from apps.core.api_permissions import permission_required

        code = "fleet.view" if self.request.method in ("GET", "HEAD", "OPTIONS") else "fleet.update"
        return [ModuleRequired("fleet")(), permission_required(code)()]

    def get(self, request):
        return Response({"gps_mismatch_km": services.fleet_settings().gps_mismatch_km})

    def patch(self, request):
        value = request.data.get("gps_mismatch_km") if hasattr(request.data, "get") else None
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1_000_000:
            raise ValidationError({"gps_mismatch_km": "Ожидается целое число от 0 до 1000000"})
        with transaction.atomic():
            settings = services.fleet_settings()
            settings.gps_mismatch_km = value
            settings.save(update_fields=["gps_mismatch_km"])
        return Response({"gps_mismatch_km": settings.gps_mismatch_km})
