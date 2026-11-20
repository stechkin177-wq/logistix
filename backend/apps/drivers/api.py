from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import F
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.permissions import ModuleRequired
from apps.core.api.users import ATTACH_ERROR, enforce_user_limit
from apps.core.api_permissions import SectionPermissionMixin, permission_required
from apps.core.audit.mixins import AuditedMixin
from apps.core.models import Membership, Role
from apps.core.pagination import StandardPagination
from apps.core.permission_guard import ensure_can_grant
from apps.core.phone import normalize_phone
from apps.core.search import search
from apps.core.tenancy import get_current_company_id

from . import reminders
from .models import Driver, DriverDocument
from .serializers import DriverDocumentSerializer, DriverSerializer

ORDERING_FIELDS = ("full_name", "created_at", "license_expires")
DUPLICATE_IIN_MESSAGE = "Водитель с таким ИИН уже есть"


class DriverViewSet(AuditedMixin, SectionPermissionMixin, viewsets.ModelViewSet):
    permission_section = "drivers"
    serializer_class = DriverSerializer
    pagination_class = StandardPagination
    # выдача и отзыв доступа в мобильную версию - право изменения водителя
    _action_map = {
        **SectionPermissionMixin._action_map,
        "grant_access": "update",
        "revoke_access": "update",
    }

    def get_permissions(self):
        return [ModuleRequired("drivers")(), *super().get_permissions()]

    def get_queryset(self):
        qs = Driver.objects.prefetch_related("documents__doc_type")
        if self.action != "list":
            return qs
        p = self.request.query_params
        if q := (p.get("q") or "").strip():
            qs = search(qs, q, fields=("full_name", "phone", "iin"))
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

    @action(detail=True, methods=["post"], url_path="grant-access")
    def grant_access(self, request, pk=None):
        """Доступ водителя в мобильную версию: пользователь по телефону карточки + пароль, который
        вводит офис (водитель потом меняет его сам); роль «Водитель», связь Driver.user."""
        ModuleRequired("driver_app")().has_permission(request, self)
        driver = self.get_object()
        if driver.user_id:
            raise ValidationError({"detail": "Доступ уже выдан"})
        password = str(request.data.get("password") or "")
        if not password:
            raise ValidationError({"password": "Укажите пароль"})
        try:
            phone = normalize_phone(driver.phone)
        except ValueError:
            raise ValidationError({"phone": "У водителя нет корректного телефона"}) from None
        role = Role.objects.filter(name="Водитель", is_system=True).first()
        if role is None:
            raise ValidationError({"detail": "Нет системной роли «Водитель»"})
        ensure_can_grant(request.membership, role.permissions)
        User = get_user_model()
        company_id = get_current_company_id()
        with transaction.atomic():
            enforce_user_limit(company_id)
            user = User.objects.filter(phone=phone).first()
            if user is None:
                try:
                    validate_password(password, user=User(full_name=driver.full_name, phone=phone))
                except DjangoValidationError as exc:
                    raise ValidationError({"password": list(exc.messages)}) from None
                user = User.objects.create_user(
                    password=password, full_name=driver.full_name, phone=phone
                )
            elif Membership.objects.filter(user=user, company_id=company_id).exists():
                raise ValidationError({"detail": "Пользователь с этим телефоном уже в компании"})
            elif not (user.is_active and user.check_password(password)):
                raise ValidationError({"detail": ATTACH_ERROR})
            Membership.objects.create(user=user, company_id=company_id, role=role)
            driver.user = user
            driver.save(update_fields=["user", "updated_at"])
        return Response({"user": user.pk, "login": phone}, status=201)

    @action(detail=True, methods=["post"], url_path="revoke-access")
    def revoke_access(self, request, pk=None):
        """Отзыв доступа: связь снимается, членство водителя в компании отключается."""
        driver = self.get_object()
        if driver.user_id:
            Membership.objects.filter(user_id=driver.user_id, company_id=driver.company_id).update(
                is_active=False
            )
            driver.user = None
            driver.save(update_fields=["user", "updated_at"])
        return Response({"revoked": True})

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


class DriverRemindersView(APIView):
    """Просроченные и приближающиеся документы водителей (по настройкам типов документов)."""

    def get_permissions(self):
        return [ModuleRequired("drivers")(), permission_required("drivers.view")()]

    def get(self, request):
        items = reminders.reminders()
        return Response({"count": len(items), "results": items})
