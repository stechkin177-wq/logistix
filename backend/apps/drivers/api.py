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

from .models import Driver, DriverDocument
from .serializers import DriverDocumentSerializer, DriverSerializer

ORDERING_FIELDS = ("full_name", "created_at", "license_expires")
DUPLICATE_IIN_MESSAGE = "Водитель с таким ИИН уже есть"


class DriverViewSet(AuditedMixin, SectionPermissionMixin, viewsets.ModelViewSet):
    permission_section = "drivers"
    serializer_class = DriverSerializer
    pagination_class = StandardPagination

    def get_permissions(self):
        return [ModuleRequired("drivers")(), *super().get_permissions()]

    def get_queryset(self):
        qs = Driver.objects.prefetch_related("documents")
        if self.action != "list":
            return qs
        p = self.request.query_params
        if q := (p.get("q") or "").strip():
            qs = qs.filter(Q(full_name__icontains=q) | Q(phone__icontains=q) | Q(iin__icontains=q))
        if status := p.get("status"):
            if status not in dict(Driver.STATUSES):
                raise ValidationError({"status": "Допустимо: active, on_leave, inactive"})
            qs = qs.filter(status=status)
        ordering = p.get("ordering") or "full_name"
        allowed = {*ORDERING_FIELDS, *(f"-{f}" for f in ORDERING_FIELDS)}
        if ordering not in allowed:
            raise ValidationError({"ordering": f"Допустимо: {', '.join(sorted(allowed))}"})
        expr = F(ordering.lstrip("-"))
        expr = expr.desc(nulls_last=True) if ordering.startswith("-") else expr.asc(nulls_last=True)
        return qs.order_by(expr, "id")

    def _enforce_limit(self):
        """Лимит max_drivers: блокировка компании против гонок, считаются неудалённые водители."""
        company = Company.objects.select_for_update().get(pk=get_current_company_id())
        check_limit(company, "max_drivers", Driver.objects.count())

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
        if constraint != "driver_company_iin_uniq":
            raise exc
        raise serializers.ValidationError({"iin": [DUPLICATE_IIN_MESSAGE]}) from None


class DriverDocumentViewSet(AuditedMixin, SectionPermissionMixin, viewsets.ModelViewSet):
    permission_section = "drivers"
    serializer_class = DriverDocumentSerializer
    pagination_class = StandardPagination

    def get_permissions(self):
        return [ModuleRequired("drivers")(), *super().get_permissions()]

    def get_queryset(self):
        qs = DriverDocument.objects.filter(driver__deleted_at__isnull=True)
        driver = self.request.query_params.get("driver")
        if self.action == "list" and driver:
            if not driver.isascii() or not driver.isdigit():
                raise ValidationError({"driver": "Ожидается числовой id"})
            qs = qs.filter(driver_id=int(driver))
        return qs.order_by("id")
