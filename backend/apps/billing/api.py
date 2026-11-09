from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ViewSet

from . import features, limits, plans
from .models import Plan
from .services import days_left, effective_status, get_subscription


class PlanSerializer(serializers.ModelSerializer):
    # options - устаревшее поле (до T2): оставлено для совместимости клиентов, только чтение и
    # выводится из features; новые клиенты используют features
    options = serializers.SerializerMethodField()

    def get_options(self, plan):
        features = plan.features or {}
        return {key: features.get(key) is True for key in ("white_label", "custom_domain")}

    class Meta:
        model = Plan
        fields = [
            "code", "name", "description", "billing_type", "price", "currency",
            "limits", "modules", "features", "options",
        ]  # fmt: skip


class PlanListView(ListAPIView):
    serializer_class = PlanSerializer
    pagination_class = None
    queryset = Plan.objects.filter(is_active=True, archived_at__isnull=True)  # порядок: sort_order


class SubscriptionView(APIView):
    def get(self, request):
        sub = get_subscription(request.membership.company_id)
        now = timezone.now()
        return Response(
            {
                "plan": PlanSerializer(sub.plan).data,
                "status": effective_status(sub, now),
                "is_free_period": sub.is_free_period,
                "starts_at": sub.starts_at,
                "ends_at": sub.ends_at,
                "days_left": days_left(sub, now),
            }
        )


# --- управление тарифами (администратор платформы) ---------------------------------------------


class IsPlatformAdmin(BasePermission):
    """Только администратор платформы. Шлюз подписки компании не применяется: управление
    тарифами не должно зависеть от состояния подписки компании самого администратора."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_platform_admin)


class AdminPlanSerializer(serializers.ModelSerializer):
    status = serializers.CharField(read_only=True)
    subscriptions_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Plan
        fields = [
            "code", "name", "description", "billing_type", "price", "currency", "sort_order",
            "status", "is_default", "limits", "modules", "features", "archived_at",
            "subscriptions_count",
        ]  # fmt: skip
        read_only_fields = fields


EDIT_FIELDS = ("name", "description", "billing_type", "price", "currency", "sort_order")


class AdminPlanViewSet(ViewSet):
    """Тарифы платформы: список (все состояния), создание, правка, публикация, архив, удаление,
    тариф по умолчанию, порядок. Модули, функции и лимиты тарифа настраиваются на этапах T2-T3."""

    permission_classes = [IsAuthenticated, IsPlatformAdmin]
    lookup_field = "code"

    @staticmethod
    def _plan(code):
        plan = plans.with_subscription_counts().filter(code=code).first()
        if plan is None:
            raise NotFound()
        return plan

    @staticmethod
    def _out(plan):
        return Response(AdminPlanSerializer(plans.with_subscription_counts().get(pk=plan.pk)).data)

    def list(self, request):
        return Response(AdminPlanSerializer(plans.with_subscription_counts(), many=True).data)

    def retrieve(self, request, code=None):
        return Response(AdminPlanSerializer(self._plan(code)).data)

    def create(self, request):
        data = {k: v for k, v in request.data.items() if k != "code"}
        plan = plans.create_plan(code=request.data.get("code", ""), **data)
        response = self._out(plan)
        response.status_code = 201
        return response

    def partial_update(self, request, code=None):
        plan = plans.update_plan(self._plan(code), **dict(request.data.items()))
        return self._out(plan)

    def destroy(self, request, code=None):
        plans.delete_plan(self._plan(code))
        return Response(status=204)

    def _act(self, code, func):
        return self._out(func(self._plan(code)))

    @action(detail=True, methods=["post"])
    def publish(self, request, code=None):
        return self._act(code, plans.publish)

    @action(detail=True, methods=["post"])
    def unpublish(self, request, code=None):
        return self._act(code, plans.unpublish)

    @action(detail=True, methods=["post"])
    def archive(self, request, code=None):
        return self._act(code, plans.archive)

    @action(detail=True, methods=["post"])
    def restore(self, request, code=None):
        return self._act(code, plans.restore)

    @action(detail=True, methods=["post"], url_path="set-default")
    def set_default(self, request, code=None):
        return self._act(code, plans.set_default)

    @action(detail=False, methods=["post"])
    def reorder(self, request):
        codes = request.data.get("codes") if hasattr(request.data, "get") else None
        if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
            raise ValidationError({"codes": "Ожидается список кодов тарифов"})
        plans.reorder(codes)
        return self.list(request)


class PlatformCatalogView(APIView):
    """Что можно включать в тариф: модули (с зависимостями) и функции (с видами и уровнями)."""

    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        from apps.core import module_catalog

        modules = [
            {
                "code": m["code"], "name": m["name"], "description": m["description"],
                "requires": [r for r in m["requires"] if r != module_catalog.CORE],
                "status": m["status"],
            }
            for m in module_catalog.MODULES
            if not m["is_core"]
        ]  # fmt: skip
        catalog_limits = [
            {"code": s["code"], "name": s["name"], "unit": s["unit"],
             "scope": s.get("scope", limits.TOTAL), "enforced": s.get("enforced", True)}
            for s in limits.LIMITS
        ]  # fmt: skip
        return Response(
            {"modules": modules, "features": features.FEATURES, "limits": catalog_limits}
        )


class UsageView(APIView):
    """Использование лимитов тарифа компанией: лимит, использование, превышение (для интерфейса)."""

    def get(self, request):
        return Response({"results": limits.company_usage(request.membership.company_id)})
