from django.db import IntegrityError, transaction
from django.db.models import F, Q
from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError

from apps.billing.permissions import ModuleRequired
from apps.billing.services import check_limit
from apps.core.api_permissions import SectionPermissionMixin
from apps.core.audit.mixins import AuditedMixin
from apps.core.models import Company
from apps.core.pagination import StandardPagination
from apps.core.tenancy import get_current_company_id

from .models import Insurance, Vehicle, VehicleDocument
from .serializers import InsuranceSerializer, VehicleDocumentSerializer, VehicleSerializer

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
