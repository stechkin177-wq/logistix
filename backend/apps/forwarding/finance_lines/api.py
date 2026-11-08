from django.db.models import ProtectedError
from rest_framework import status, viewsets
from rest_framework.exceptions import APIException, ValidationError

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import SectionPermissionMixin
from apps.core.audit import services
from apps.core.audit.mixins import AuditedMixin
from apps.core.pagination import StandardPagination

from ..models import OrderService
from ..orders.filters import int_param
from .models import company_today
from .serializers import BASE_LINE_MESSAGE, OrderServiceSerializer


class LineInvoiced(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Строка включена в счёт: сначала исключите её из счёта"
    default_code = "line_invoiced"


class OrderServiceViewSet(AuditedMixin, SectionPermissionMixin, viewsets.ModelViewSet):
    """Строки заказов компании. ?order=<id>: чужой или несуществующий заказ даёт пустой список
    (404 не нужен: запрос уже ограничен компанией). Строки удалённых заказов скрыты."""

    permission_section = "finance"
    serializer_class = OrderServiceSerializer
    pagination_class = StandardPagination

    def get_permissions(self):
        return [ModuleRequired("logistics")(), *super().get_permissions()]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            # engine=new: строки только для чтения (409 до валидации тела)
            from apps.finance.engine import assert_legacy_lines_writable

            assert_legacy_lines_writable(request.membership.company_id)

    def get_queryset(self):
        qs = OrderService.objects.filter(order__deleted_at__isnull=True).select_related("order")
        if self.action == "list":
            if (order := int_param(self.request.query_params, "order")) is not None:
                qs = qs.filter(order_id=order)
        return qs.order_by("date", "id")

    # --- защита закрытого периода и обратного датирования (apps.finance.periods) ---
    # Импорт внутри методов: finance зависит от forwarding, обратная зависимость - только здесь.

    _adjustment: dict | None = None

    def audit_extra_changes(self, instance) -> dict:
        return self._adjustment or {}

    def audit_deleted(self, copy_before_delete):
        if not self._adjustment:
            return super().audit_deleted(copy_before_delete)
        services.log(
            "delete",
            copy_before_delete,
            self.request.user,
            {
                **services.diff(services.snapshot(copy_before_delete), {}),
                **self._adjustment,
            },
            ip=services.client_ip(self.request),
        )

    @staticmethod
    def _line_state(line) -> dict:
        return {
            "date": line.date.isoformat(),
            "income": str(line.income),
            "expense": str(line.expense),
            "title": line.title,
        }

    def _guard(self, old_date, new_date):
        """Проверки дат строки. Возвращает (корректировка?, причина, права)."""
        from apps.finance import periods
        from apps.finance.engine import assert_legacy_lines_writable

        request = self.request
        cid = request.membership.company_id
        assert_legacy_lines_writable(cid)  # engine=new: строки только для чтения (409)
        periods.assert_finance_writable(cid)  # безопасная остановка (423)
        perms = periods.request_perms(request)
        reason = periods.request_adjust_reason(request)
        adjusted = False
        if old_date is not None:
            adjusted |= periods.check_system_date(cid, old_date, perms, reason)
        if new_date is not None and new_date != old_date:
            adjusted |= periods.check_user_date(cid, new_date, perms, reason)
        return adjusted, reason

    def perform_create(self, serializer):
        new_date = serializer.validated_data.get("date")
        # дата не указана - строка получит «сегодня»; закрытый месяц всё равно проверяется
        adjusted, reason = self._guard(
            None, new_date or company_today(self.request.membership.company_id)
        )
        serializer.save(**self.get_create_kwargs(serializer))
        from apps.finance import hooks  # Shadow-зеркало (только engine=shadow)

        hooks.after_line_saved(serializer.instance)
        if adjusted:
            from apps.finance import periods

            self._adjustment = periods.adjustment_changes(
                reason, None, self._line_state(serializer.instance)
            )
        self.audit_created(serializer.instance)

    def perform_update(self, serializer):
        instance = serializer.instance
        old_state = self._line_state(instance)
        adjusted, reason = self._guard(instance.date, serializer.validated_data.get("date"))
        before = services.snapshot(instance)
        serializer.save()
        from apps.finance import hooks  # Shadow-зеркало (только engine=shadow)

        hooks.after_line_saved(serializer.instance)
        if adjusted:
            from apps.finance import periods

            self._adjustment = periods.adjustment_changes(
                reason, old_state, self._line_state(serializer.instance)
            )
        self.audit_updated(before, serializer.instance)

    def perform_destroy(self, instance):
        from apps.finance.engine import assert_legacy_lines_writable

        assert_legacy_lines_writable(self.request.membership.company_id)
        if instance.is_base:
            raise ValidationError(BASE_LINE_MESSAGE)
        adjusted, reason = self._guard(instance.date, None)
        if adjusted:
            from apps.finance import periods

            self._adjustment = periods.adjustment_changes(reason, self._line_state(instance), None)
        from apps.finance import hooks  # Shadow: зеркало отвязывается ДО удаления строки

        order = instance.order
        hooks.before_line_delete(instance)
        try:
            super().perform_destroy(instance)
        except ProtectedError:  # строка входит в счёт (finance.InvoiceItem, PROTECT)
            raise LineInvoiced() from None
        hooks.after_line_deleted(order)
