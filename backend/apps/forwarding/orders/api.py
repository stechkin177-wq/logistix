from django.db import transaction
from django.db.models import Exists, Prefetch
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import SectionPermissionMixin, permission_required
from apps.core.audit.mixins import AuditedMixin
from apps.core.audit.services import client_ip
from apps.core.pagination import StandardPagination

from ..finance_lines.models import zone_from_name
from ..finance_lines.services import annotate_order_totals
from ..models import Order, OrderStatusHistory
from .board import build_board, limit_param
from .export import AnyAcceptNegotiation, export_orders
from .filters import filter_orders
from .serializers import OrderSerializer, StatusChangeSerializer, consignments_prefetch
from .services import carried_with_carrier


class OrderViewSet(AuditedMixin, SectionPermissionMixin, viewsets.ModelViewSet):
    permission_section = "orders"
    serializer_class = OrderSerializer
    pagination_class = StandardPagination

    def get_permissions(self):
        if self.action == "change_status":
            return [ModuleRequired("forwarding")(), permission_required("orders.update")()]
        if self.action in ("board", "export"):  # читают то же, что и список
            return [ModuleRequired("forwarding")(), permission_required("orders.view")()]
        return [ModuleRequired("forwarding")(), *super().get_permissions()]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["with_history"] = self.action != "list"
        context["with_finance"] = self.with_finance()
        return context

    def with_finance(self) -> bool:
        """Выручка, расходы и прибыль видны только с finance.view (иначе поля равны null)."""
        return "finance.view" in self.request.membership.role.permissions

    def get_queryset(self):
        qs = (
            Order.objects.select_related("client", "status", "manager")
            .prefetch_related("extra_managers", consignments_prefetch())
            .annotate(has_carrier=Exists(carried_with_carrier()))
        )
        if self.with_finance():  # без права подзапросы итогов не нужны
            qs = annotate_order_totals(qs)
        if self.action != "list":
            qs = qs.prefetch_related(
                Prefetch(
                    "history",
                    queryset=OrderStatusHistory.objects.select_related("from_status", "to_status"),
                )
            )
        else:
            qs = filter_orders(qs, self.request.query_params, self.company_zone())
        return qs

    def company_zone(self):
        # компания уже загружена вместе с членством: без лишнего запроса
        return zone_from_name(self.request.membership.company.timezone)

    @action(detail=False, methods=["get"], url_path="board")
    def board(self, request):
        """Канбан: колонки по справочнику order_status с карточками; те же фильтры, что у списка."""
        params = request.query_params
        limit = limit_param(params)
        return Response(build_board(params, self.company_zone(), limit))

    @action(
        detail=False,
        methods=["get"],
        url_path="export",
        content_negotiation_class=AnyAcceptNegotiation,
    )
    def export(self, request):
        """Выгрузка заказов (те же фильтры, что у списка) в .xlsx."""
        with_finance = "finance.view" in request.membership.role.permissions
        return export_orders(request.query_params, self.company_zone(), with_finance=with_finance)

    def perform_destroy(self, instance):
        from apps.finance import hooks  # engine=new: блокировка при деньгах, void плановых доходов

        with transaction.atomic():
            hooks.before_order_delete(instance, self.request.user)
            super().perform_destroy(instance)

    def perform_create(self, serializer):
        serializer.save()  # create_order сам пишет аудит заказа и его грузов

    def audit_extra_changes(self, instance):
        diff = getattr(instance, "_extra_managers_diff", None)
        return {"extra_managers": diff} if diff else {}

    @action(detail=True, methods=["post"], url_path="status")
    def change_status(self, request, pk=None):
        """Смена статуса: тело {"status": id значения order_status}."""
        order = self.get_object()
        serializer = StatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(order, request.user, ip=client_ip(request))
        fresh = self.get_queryset().get(pk=order.pk)
        return Response(self.get_serializer(fresh).data)
