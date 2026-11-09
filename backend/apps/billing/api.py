from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ViewSet

from apps.core.platform import COMPANIES, PLANS, SUBSCRIPTIONS, PlatformAccess

from . import features, limits, plans, subscriptions
from .models import BillingEvent, Plan
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


# --- управление тарифами (платформенный контекст; права по роли: apps.core.platform) ---


class AdminPlanSerializer(serializers.ModelSerializer):
    status = serializers.CharField(read_only=True)
    subscriptions_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Plan
        fields = [
            "code", "name", "description", "billing_type", "price", "currency", "sort_order",
            "status", "is_default", "limits", "modules", "features", "archived_at",
            "free_period_days", "limit_warn_percent",
            "subscriptions_count",
        ]  # fmt: skip
        read_only_fields = fields


EDIT_FIELDS = ("name", "description", "billing_type", "price", "currency", "sort_order")


class AdminPlanViewSet(ViewSet):
    """Тарифы платформы: список (все состояния), создание, правка, публикация, архив, удаление,
    тариф по умолчанию, порядок. Модули, функции и лимиты тарифа настраиваются на этапах T2-T3."""

    permission_classes = [PlatformAccess]
    platform_write = PLANS
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
        plan = plans.create_plan(code=request.data.get("code", ""), by=request.user, **data)
        response = self._out(plan)
        response.status_code = 201
        return response

    def partial_update(self, request, code=None):
        plan = plans.update_plan(self._plan(code), by=request.user, **dict(request.data.items()))
        return self._out(plan)

    def destroy(self, request, code=None):
        plans.delete_plan(self._plan(code), by=request.user)
        return Response(status=204)

    def _act(self, code, func):
        return self._out(func(self._plan(code), by=self.request.user))

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
        plans.reorder(codes, by=request.user)
        return self.list(request)


class PlatformCatalogView(APIView):
    """Что можно включать в тариф: модули (с зависимостями) и функции (с видами и уровнями)."""

    permission_classes = [PlatformAccess]

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
        rows = limits.company_usage(request.membership.company_id)
        warnings = [r for r in rows if r["state"] != limits.OK]  # владельцу: что требует внимания
        return Response({"results": rows, "warnings": warnings})


# --- подписки компаний (администратор платформы) -----------------------------------------------


def _company(company_id):
    from apps.core.models import Company

    company = Company.objects.filter(pk=company_id).first()
    if company is None or not hasattr(company, "subscription"):
        raise NotFound()
    return company


def _sub_payload(company):
    sub = company.subscription
    period = subscriptions.current_period(sub)
    return {
        "company": company.pk,
        "plan": sub.plan.code,
        "status": effective_status(sub, timezone.now()),
        "is_free_period": sub.is_free_period,
        "starts_at": sub.starts_at,
        "ends_at": sub.ends_at,
        "current_period": None
        if period is None
        else {
            "plan": period.plan_code, "reason": period.reason, "starts_at": period.starts_at,
            "ends_at": period.ends_at, "price": str(period.price), "currency": period.currency,
            "is_free": period.is_free,
        },
        "periods": [
            {"plan": p.plan_code, "reason": p.reason, "starts_at": p.starts_at,
             "ends_at": p.ends_at, "price": str(p.price), "currency": p.currency}
            for p in sub.periods.all()
        ],
    }  # fmt: skip


class PlatformSubscriptionViewSet(ViewSet):
    """Подписка компании для администратора платформы: просмотр, анализ и смена тарифа, продление.

    Платёжных интеграций нет: продление фиксирует период и цену, оплату подтверждает администратор.
    """

    permission_classes = [PlatformAccess]
    platform_write = SUBSCRIPTIONS
    platform_actions = {"block": COMPANIES, "unblock": COMPANIES}  # только владелец платформы
    lookup_field = "company_id"
    lookup_value_regex = r"\d+"

    def retrieve(self, request, company_id=None):
        return Response(_sub_payload(_company(company_id)))

    @staticmethod
    def _plan(code):
        plan = Plan.objects.filter(code=code).first() if isinstance(code, str) else None
        if plan is None:
            raise ValidationError({"plan": "Укажите существующий тариф"})
        return plan

    @action(detail=True, methods=["get"], url_path="change-plan/preview")
    def preview(self, request, company_id=None):
        plan = self._plan(request.query_params.get("plan"))
        return Response(subscriptions.preview_change(_company(company_id), plan))

    @action(detail=True, methods=["post"], url_path="change-plan")
    def change_plan(self, request, company_id=None):
        company = _company(company_id)
        plan = self._plan(request.data.get("plan"))
        subscriptions.change_plan(
            company, plan, period=request.data.get("period", subscriptions.KEEP), user=request.user
        )
        company.subscription.refresh_from_db()
        return Response(_sub_payload(company))

    @action(detail=True, methods=["post"])
    def block(self, request, company_id=None):
        company = _company(company_id)
        subscriptions.set_blocked(
            company, True, reason=request.data.get("reason"), user=request.user
        )
        company.subscription.refresh_from_db()
        return Response(_sub_payload(company))

    @action(detail=True, methods=["post"])
    def unblock(self, request, company_id=None):
        company = _company(company_id)
        subscriptions.set_blocked(
            company, False, reason=request.data.get("reason"), user=request.user
        )
        company.subscription.refresh_from_db()
        return Response(_sub_payload(company))

    @action(detail=True, methods=["post"])
    def renew(self, request, company_id=None):
        company = _company(company_id)
        subscriptions.renew(company, periods=request.data.get("periods", 1), user=request.user)
        company.subscription.refresh_from_db()
        return Response(_sub_payload(company))


class PlatformCompaniesView(APIView):
    """Компании платформы с их подписками (поиск по названию) - для управления подписками."""

    permission_classes = [PlatformAccess]

    def get(self, request):
        from apps.core.models import Company
        from apps.core.pagination import StandardPagination

        qs = Company.objects.select_related("subscription__plan").filter(subscription__isnull=False)
        if q := (request.query_params.get("q") or "").strip():
            qs = qs.filter(name__icontains=q)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs.order_by("name", "id"), request)
        now = timezone.now()
        rows = [
            {
                "id": c.pk, "name": c.name, "plan": c.subscription.plan.code,
                "plan_name": c.subscription.plan.name,
                "status": effective_status(c.subscription, now),
                "is_free_period": c.subscription.is_free_period, "ends_at": c.subscription.ends_at,
            }
            for c in page
        ]  # fmt: skip
        return paginator.get_paginated_response(rows)


class PlatformHistoryView(APIView):
    """Журнал изменений тарифов и подписок: фильтры kind (plan|subscription) и key."""

    permission_classes = [PlatformAccess]

    def get(self, request):
        from apps.core.pagination import StandardPagination

        qs = BillingEvent.objects.all()
        kind = request.query_params.get("kind")
        if kind:
            if kind not in dict(BillingEvent.KINDS):
                raise ValidationError({"kind": "Допустимо: plan, subscription, auth, company"})
            qs = qs.filter(kind=kind)
        if key := request.query_params.get("key"):
            qs = qs.filter(key=key)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        rows = [
            {"id": e.pk, "kind": e.kind, "key": e.key, "action": e.action, "changes": e.changes,
             "actor": e.actor, "created_at": e.created_at}
            for e in page
        ]  # fmt: skip
        return paginator.get_paginated_response(rows)
