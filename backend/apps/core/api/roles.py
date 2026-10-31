from copy import copy

from django.db import transaction
from django.db.models import ProtectedError
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core.api_permissions import SectionPermissionMixin
from apps.core.audit.mixins import AuditedMixin
from apps.core.models import Department, Role
from apps.core.permission_guard import ensure_can_grant
from apps.core.permissions_catalog import ALL_PERMISSIONS
from apps.core.tenancy import get_current_company_id


class RoleSerializer(serializers.ModelSerializer):
    permissions = serializers.ListField(child=serializers.CharField(), allow_empty=True)

    class Meta:
        model = Role
        fields = ["id", "name", "is_system", "permissions"]
        read_only_fields = ["id", "is_system"]

    def validate_name(self, value):
        value = value.strip()
        qs = Role.objects.filter(name=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Роль с таким названием уже есть")
        return value

    def validate_permissions(self, value):
        unknown = sorted(set(value) - set(ALL_PERMISSIONS))
        if unknown:
            raise serializers.ValidationError(f"Неизвестные права: {', '.join(unknown)}")
        return list(dict.fromkeys(value))

    def validate(self, attrs):
        if self.instance is not None and self.instance.is_system:
            raise serializers.ValidationError("Системную роль изменять нельзя")
        return attrs


class RoleViewSet(AuditedMixin, SectionPermissionMixin, viewsets.ModelViewSet):
    permission_section = "roles"
    serializer_class = RoleSerializer
    pagination_class = None

    def get_queryset(self):
        return Role.objects.order_by("id")

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ensure_can_grant(request.membership, ser.validated_data["permissions"])
        # company берётся из контекста токена, is_system - всегда False
        ser.save(company_id=get_current_company_id(), is_system=False)
        self.audit_created(ser.instance)
        return Response(ser.data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        if "permissions" in serializer.validated_data:
            ensure_can_grant(self.request.membership, serializer.validated_data["permissions"])
        super().perform_update(serializer)

    def destroy(self, request, *args, **kwargs):
        conflict = Response(
            {"detail": "Роль назначена сотрудникам, сначала переназначьте их"},
            status=status.HTTP_409_CONFLICT,
        )
        try:
            return self._destroy(conflict)
        except ProtectedError:
            return conflict

    def _destroy(self, conflict):
        with transaction.atomic():
            role = self.get_object()
            if role.is_system:
                raise ValidationError({"detail": "Системную роль удалять нельзя"})
            if role.memberships.exists():
                return conflict
            snapshot = copy(role)
            role.delete()
            self.audit_deleted(snapshot)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ["id", "name"]
        read_only_fields = ["id"]

    def validate_name(self, value):
        value = value.strip()
        qs = Department.objects.filter(name=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Отдел с таким названием уже есть")
        return value


class DepartmentViewSet(AuditedMixin, SectionPermissionMixin, viewsets.ModelViewSet):
    permission_section = "users"
    serializer_class = DepartmentSerializer
    pagination_class = None

    def get_queryset(self):
        return Department.objects.order_by("id")

    def get_create_kwargs(self, serializer):
        return {"company_id": get_current_company_id()}
