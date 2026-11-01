from rest_framework import viewsets
from rest_framework.exceptions import ValidationError

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import SectionPermissionMixin
from apps.core.audit.mixins import AuditedMixin
from apps.core.pagination import StandardPagination

from ..models import OrderService
from ..orders.api import int_param
from .serializers import BASE_LINE_MESSAGE, OrderServiceSerializer


class OrderServiceViewSet(AuditedMixin, SectionPermissionMixin, viewsets.ModelViewSet):
    """Строки заказов компании. ?order=<id>: чужой или несуществующий заказ даёт пустой список
    (404 не нужен: запрос уже ограничен компанией). Строки удалённых заказов скрыты."""

    permission_section = "finance"
    serializer_class = OrderServiceSerializer
    pagination_class = StandardPagination

    def get_permissions(self):
        return [ModuleRequired("forwarding")(), *super().get_permissions()]

    def get_queryset(self):
        qs = OrderService.objects.filter(order__deleted_at__isnull=True).select_related("order")
        if self.action == "list":
            if (order := int_param(self.request.query_params, "order")) is not None:
                qs = qs.filter(order_id=order)
        return qs.order_by("date", "id")

    def perform_destroy(self, instance):
        if instance.is_base:
            raise ValidationError(BASE_LINE_MESSAGE)
        super().perform_destroy(instance)
