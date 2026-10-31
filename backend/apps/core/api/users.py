from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.billing.services import check_limit
from apps.core.api_permissions import SectionPermissionMixin
from apps.core.models import Company, Department, Membership, Role
from apps.core.permission_guard import ensure_can_grant
from apps.core.permissions_catalog import ADMIN_ROLE_NAME
from apps.core.phone import normalize_phone
from apps.core.tenancy import get_current_company_id

User = get_user_model()
FORBIDDEN_FIELDS = ("is_platform_admin", "is_staff", "is_superuser")


class MembershipSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    phone = serializers.CharField(source="user.phone", read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)
    user_id = serializers.IntegerField(read_only=True)
    role_name = serializers.CharField(source="role.name", read_only=True, default=None)

    class Meta:
        model = Membership
        fields = [
            "id",
            "user_id",
            "email",
            "phone",
            "full_name",
            "role",
            "role_name",
            "department",
            "is_active",
        ]


# Менеджеры выбираются лениво (на запросе), чтобы не требовать контекст компании при импорте.
class _RoleField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return Role.objects.all()


class _DepartmentField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return Department.objects.all()


def _reject_forbidden(initial):
    bad = [k for k in FORBIDDEN_FIELDS if k in initial]
    if bad:
        raise serializers.ValidationError({k: "Это поле нельзя менять через API" for k in bad})


class MembershipCreateSerializer(serializers.Serializer):
    login = serializers.CharField()
    password = serializers.CharField(required=False, trim_whitespace=False, write_only=True)
    full_name = serializers.CharField(required=False, allow_blank=True, default="")
    role = _RoleField(queryset=Role.objects)
    department = _DepartmentField(queryset=Department.objects, required=False, allow_null=True)

    def validate(self, attrs):
        _reject_forbidden(self.initial_data)
        return attrs

    def validate_login(self, value):
        value = value.strip()
        if "@" in value:
            return value.lower()
        try:
            return normalize_phone(value)
        except ValueError:
            raise serializers.ValidationError("Некорректный номер телефона") from None


class MembershipUpdateSerializer(serializers.Serializer):
    role = _RoleField(queryset=Role.objects, required=False)
    department = _DepartmentField(queryset=Department.objects, required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False)

    def validate(self, attrs):
        _reject_forbidden(self.initial_data)
        return attrs


def enforce_user_limit(company_id):
    """Лимит max_users по активным членствам; блокировка компании против гонок."""
    company = Company.objects.select_for_update().get(pk=company_id)
    active = Membership.objects.filter(company_id=company_id, is_active=True).count()
    check_limit(company, "max_users", active)


def _is_admin(membership):
    return (
        membership.role is not None
        and membership.role.name == ADMIN_ROLE_NAME
        and (membership.role.is_system)
    )


class MembershipViewSet(
    SectionPermissionMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    permission_section = "users"
    pagination_class = None

    def get_queryset(self):
        # Membership не TenantModel: фильтр по компании токена обязателен
        return (
            Membership.objects.filter(company_id=get_current_company_id())
            .select_related("user", "role")
            .order_by("id")
        )

    def get_serializer_class(self):
        if self.action == "create":
            return MembershipCreateSerializer
        if self.action in ("update", "partial_update"):
            return MembershipUpdateSerializer
        return MembershipSerializer

    def create(self, request, *args, **kwargs):
        ser = MembershipCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        ensure_can_grant(request.membership, data["role"].permissions)
        login = data["login"]
        field = "email" if "@" in login else "phone"
        company_id = get_current_company_id()
        with transaction.atomic():
            enforce_user_limit(company_id)
            user = User.objects.filter(**{field: login}).first()
            attached = user is not None
            if user is None:
                password = data.get("password")
                if not password:
                    raise serializers.ValidationError(
                        {"password": "Для нового пользователя нужен пароль"}
                    )
                try:
                    validate_password(
                        password,
                        user=User(full_name=data["full_name"], **{field: login}),
                    )
                except DjangoValidationError as exc:
                    raise serializers.ValidationError({"password": list(exc.messages)}) from None
                user = User.objects.create_user(
                    password=password, full_name=data["full_name"], **{field: login}
                )
            elif Membership.objects.filter(user=user, company_id=company_id).exists():
                raise serializers.ValidationError({"login": "Пользователь уже в компании"})
            try:
                with transaction.atomic():
                    membership = Membership.objects.create(
                        user=user,
                        company_id=company_id,
                        role=data["role"],
                        department=data.get("department"),
                    )
            except IntegrityError:
                raise serializers.ValidationError(
                    {"login": "Пользователь уже в компании"}
                ) from None
        membership = Membership.objects.select_related("user", "role").get(pk=membership.pk)
        out = MembershipSerializer(membership).data
        if attached:
            # профиль чужого аккаунта (телефон, имя, второй логин) не раскрываем
            out = {
                key: out[key]
                for key in ("id", "user_id", "role", "role_name", "department", "is_active")
            }
            out["login"] = login
        return Response(out, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        with transaction.atomic():
            # блокируем активных администраторов компании, чтобы две правки не обошли защиту
            admins = list(
                Membership.objects.select_for_update()
                .filter(
                    company_id=get_current_company_id(),
                    is_active=True,
                    role__name=ADMIN_ROLE_NAME,
                    role__is_system=True,
                )
                .values_list("pk", flat=True)
            )
            instance = self.get_object()
            ser = MembershipUpdateSerializer(data=request.data, partial=partial)
            ser.is_valid(raise_exception=True)
            data = ser.validated_data
            actor = request.membership
            if instance.pk == actor.pk:
                if "role" in data and data["role"] != instance.role:
                    raise PermissionDenied("Нельзя менять собственную роль")
                if data.get("is_active") is False:
                    raise PermissionDenied("Нельзя отключить самого себя")
            if "role" in data and data["role"] != instance.role:
                ensure_can_grant(actor, data["role"].permissions)
            if data.get("is_active") is True and not instance.is_active:
                enforce_user_limit(instance.company_id)
            was_admin = instance.is_active and _is_admin(instance)
            new_role = data.get("role", instance.role)
            new_active = data.get("is_active", instance.is_active)
            still_admin = (
                new_active
                and new_role is not None
                and (new_role.name == ADMIN_ROLE_NAME and new_role.is_system)
            )
            if was_admin and not still_admin and not [p for p in admins if p != instance.pk]:
                raise serializers.ValidationError(
                    {"detail": "Нельзя отключить или понизить последнего администратора"}
                )
            if "role" in data:
                instance.role = data["role"]
            if "department" in data:
                instance.department = data["department"]
            if "is_active" in data:
                instance.is_active = data["is_active"]
            instance.save()
        instance = self.get_queryset().get(pk=instance.pk)
        return Response(MembershipSerializer(instance).data)
