# ruff: noqa: E501
"""API новых сущностей: /api/finance/incomes/ и /api/finance/expenses/ (1.4.12).

Все проверки (права, периоды, обратное датирование, заморозка) выполняют сервисы на сервере; здесь
только разбор запроса, фильтры и представление. Списки без N+1 (select_related / prefetch /
аннотации). Формат ошибок {detail, code}, пагинация как в проекте.
"""

from datetime import date
from decimal import Decimal

from django.db.models import DecimalField, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce, TruncDate
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import permission_required
from apps.core.audit import services as audit
from apps.core.handbooks.models import HandbookValue
from apps.core.pagination import StandardPagination
from apps.forwarding.models import Order
from apps.forwarding.orders.filters import date_param, int_param

from .. import expenses as exp_svc
from .. import income as inc_svc
from .. import invoice_links, periods
from ..errors import FinanceError
from ..models import Expense, ExpenseAllocation, ExpenseInvoiceAllocation, Income, InvoiceItem
from .serializers import money

_MONEY = DecimalField(max_digits=18, decimal_places=2)


def ctx(request) -> dict:
    return {
        "user": request.user,
        "perms": periods.request_perms(request),
        "adjust_reason": periods.request_adjust_reason(request),
    }


def _currency(handbook) -> dict | None:
    return {"id": handbook.pk, "code": handbook.code, "name": handbook.name} if handbook else None


def _body(request) -> dict:
    data = request.data
    if not hasattr(data, "get"):
        raise FinanceError("body_invalid", "Ожидается объект JSON")
    return data


def _int(data, key, required=True):
    value = data.get(key)
    if value is None or value == "":
        if required:
            raise FinanceError("field_required", f"Поле {key} обязательно")
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise FinanceError("field_invalid", f"Поле {key}: нужно целое число")
    return value


def _date(data, key, required=True) -> date | None:
    value = data.get(key)
    if value in (None, ""):
        if required:
            raise FinanceError("field_required", f"Поле {key} обязательно")
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise FinanceError("field_invalid", f"Поле {key}: дата в формате ГГГГ-ММ-ДД") from None


def _text(data, key, required=True) -> str:
    value = data.get(key)
    if not isinstance(value, str) or (required and not value.strip()):
        if required:
            raise FinanceError("field_required", f"Поле {key} обязательно")
        return ""
    return value.strip()


# --- доходы ----------------------------------------------------------------------------------


def income_data(inc: Income) -> dict:
    return {
        "id": inc.pk,
        "order": {"id": inc.order_id, "number": inc.order.number},
        "kind": inc.kind,
        "title": inc.title,
        "category": inc.category,
        "amount": money(inc.amount),
        "currency": _currency(inc.currency),
        "status": inc.status,
        "recognized_on": inc.recognized_on,
        "recognition_basis": inc.recognition_basis,
        "delivered_on": inc.delivered_on,
        "base_amount": money(inc.base_amount) if inc.base_amount is not None else None,
        "base_currency": _currency(inc.fx_base_currency) if inc.fx_base_currency_id else None,
        "fx_rate": money(inc.fx_rate) if inc.fx_rate is not None else None,
        "fx_rate_source": inc.fx_rate_source,
        "trip": {"id": inc.trip_id, "number": inc.trip.number} if inc.trip_id else None,
        "void_reason": inc.void_reason,
        "legacy": inc.legacy_line_id is not None,
        "created_at": inc.created_at,
    }


class IncomeViewSet(viewsets.GenericViewSet):
    """Доходы: список/карточка, плановая услуга, оказание, подтверждение, корректировка, аннулирование."""

    pagination_class = StandardPagination
    PERMISSIONS = {
        "list": "finance.view",
        "retrieve": "finance.view",
        "create": "finance.create",
        "deliver": "finance.update",
        "confirm": "finance.update",
        "adjust": "finance.update",
        "void": "finance.delete",
    }

    def get_permissions(self):
        code = self.PERMISSIONS.get(self.action, "finance.delete")
        return [ModuleRequired("finance")(), permission_required(code)()]

    def get_queryset(self):
        qs = Income.objects.select_related(
            "order", "currency", "trip", "fx_base_currency"
        ).annotate(day=Coalesce("recognized_on", TruncDate("created_at")))
        if self.action == "list":
            p = self.request.query_params
            if (v := int_param(p, "order")) is not None:
                qs = qs.filter(order_id=v)
            if v := (p.get("status") or "").strip():
                qs = qs.filter(status=v)
            if v := (p.get("kind") or "").strip():
                qs = qs.filter(kind=v)
            if v := (p.get("currency") or "").strip():
                qs = qs.filter(Q(currency__code=v) | Q(currency_id=v if v.isdigit() else -1))
            if (v := date_param(p, "date_from")) is not None:
                qs = qs.filter(day__gte=v)
            if (v := date_param(p, "date_to")) is not None:
                qs = qs.filter(day__lte=v)
        return qs.order_by("-day", "-id")

    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response([income_data(i) for i in page])

    def retrieve(self, request, pk=None):
        return Response(income_data(self.get_object()))

    def _respond(self, inc, code=status.HTTP_200_OK):
        return Response(income_data(self.get_queryset().get(pk=inc.pk)), status=code)

    def create(self, request):
        data = _body(request)
        order = Order.objects.filter(pk=_int(data, "order")).first()
        if order is None:
            raise NotFound("Заказ не найден")
        try:
            amount = Decimal(str(data.get("amount")))
        except Exception:  # noqa: BLE001
            raise FinanceError("amount_invalid", "Некорректная сумма") from None
        inc = inc_svc.plan_service(
            order, _text(data, "title"), _text(data, "category", False), amount, request.user
        )
        return self._respond(inc, status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def deliver(self, request, pk=None):
        data = _body(request)
        c = ctx(request)
        inc = inc_svc.mark_service_delivered(
            self.get_object(),
            _date(data, "delivered_on"),
            c["user"],
            c["perms"],
            c["adjust_reason"],
        )
        return self._respond(inc)

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        c = ctx(request)
        inc = inc_svc.confirm_service(self.get_object(), c["user"], c["perms"], c["adjust_reason"])
        return self._respond(inc)

    @action(detail=True, methods=["post"])
    def adjust(self, request, pk=None):
        data = _body(request)
        inc = inc_svc.adjust_recognized_income(
            self.get_object(),
            data.get("new_amount"),
            user=request.user,
            reason=_text(data, "reason"),
            can_adjust=periods.ADJUST_PERMISSION in periods.request_perms(request),
        )
        return self._respond(inc)

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        data = _body(request)
        inc = inc_svc.void_income(self.get_object(), _text(data, "reason"), request.user)
        return self._respond(inc)


# --- расходы -------------------------------------------------------------------------------


def allocation_data(a: ExpenseAllocation) -> dict:
    return {
        "id": a.pk,
        "order": {"id": a.order_id, "number": a.order.number} if a.order_id else None,
        "trip": {"id": a.trip_id, "number": a.trip.number} if a.trip_id else None,
        "amount": money(a.amount),
    }


def expense_data(e: Expense) -> dict:
    allocs = list(e.allocations.all())
    linked = getattr(e, "linked_total", None)
    allocated = sum((a.amount for a in allocs), Decimal("0"))
    return {
        "id": e.pk,
        "kind": e.kind,
        "title": e.title,
        "category": {"id": e.category_id, "code": e.category.code, "name": e.category.name},
        "amount": money(e.amount),
        "currency": _currency(e.currency),
        "expense_date": e.expense_date,
        "status": e.status,
        "source": e.source,
        "trip": {"id": e.trip_id, "number": e.trip.number} if e.trip_id else None,
        "carrier": {"id": e.carrier_id, "name": e.carrier.name} if e.carrier_id else None,
        "needs_review": e.needs_review,
        "review_reason": e.review_reason,
        "requires_full_allocation": e.requires_full_allocation,
        "allocation_method": e.allocation_method,
        "base_amount": money(e.base_amount) if e.base_amount is not None else None,
        "fx_rate_source": e.fx_rate_source,
        "allocations": [allocation_data(a) for a in allocs],
        "allocated": money(allocated),
        "unallocated": money(e.amount - allocated),
        "linked_total": money(linked) if linked is not None else None,
        # расхождение со счётом: связанная сумма - сумма расхода (None - связей нет)
        "invoice_variance": money(linked - e.amount) if linked is not None else None,
        "void_reason": e.void_reason,
        "created_at": e.created_at,
    }


class ExpenseViewSet(viewsets.GenericViewSet):
    """Расходы: список, ручное создание, ограниченный PATCH, доли, аннулирование, связи со счетами."""

    pagination_class = StandardPagination
    PERMISSIONS = {
        "list": "finance.view",
        "retrieve": "finance.view",
        "create": "finance.create",
        "partial_update": "finance.update",
        "allocations": "finance.update",
        "reallocate": "finance.update",
        "link_invoice_item": "finance.update",
        "unlink_invoice_item": "finance.update",
        "void": "finance.delete",
    }
    EDITABLE = {"title", "category"}

    def get_permissions(self):
        code = self.PERMISSIONS.get(self.action, "finance.delete")
        return [ModuleRequired("finance")(), permission_required(code)()]

    def get_queryset(self):
        active_links = (
            ExpenseInvoiceAllocation.objects.filter(
                expense=OuterRef("pk"), released_at__isnull=True
            )
            .order_by()
            .values("expense")
            .annotate(t=Sum("amount"))
            .values("t")
        )
        qs = (
            Expense.objects.select_related("category", "currency", "trip", "carrier")
            .prefetch_related("allocations__order", "allocations__trip")
            .annotate(linked_total=Subquery(active_links, output_field=_MONEY))
        )
        if self.action == "list":
            p = self.request.query_params
            if (v := int_param(p, "trip")) is not None:
                qs = qs.filter(trip_id=v)
            if (v := int_param(p, "order")) is not None:
                qs = qs.filter(allocations__order_id=v).distinct()
            if v := (p.get("category") or "").strip():
                qs = qs.filter(Q(category__code=v) | Q(category_id=v if v.isdigit() else -1))
            if v := (p.get("status") or "").strip():
                qs = qs.filter(status=v)
            if (v := (p.get("needs_review") or "").strip().lower()) in ("true", "1", "false", "0"):
                qs = qs.filter(needs_review=v in ("true", "1"))
            if (v := date_param(p, "date_from")) is not None:
                qs = qs.filter(expense_date__gte=v)
            if (v := date_param(p, "date_to")) is not None:
                qs = qs.filter(expense_date__lte=v)
        return qs.order_by("-expense_date", "-id")

    def _respond(self, e, code=status.HTTP_200_OK):
        return Response(expense_data(self.get_queryset().get(pk=e.pk)), status=code)

    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response([expense_data(e) for e in page])

    def retrieve(self, request, pk=None):
        return Response(expense_data(self.get_object()))

    def create(self, request):
        data = _body(request)
        company = request.membership.company
        currency = HandbookValue.objects.filter(
            pk=_int(data, "currency"), handbook__code="currency"
        ).first()
        c = ctx(request)
        try:
            amount = Decimal(str(data.get("amount")))
        except Exception:  # noqa: BLE001
            raise FinanceError("amount_invalid", "Некорректная сумма") from None
        expense = exp_svc.create_expense(
            company,
            title=_text(data, "title"),
            category=_int(data, "category"),
            amount=amount,
            currency=currency,
            expense_date=_date(data, "expense_date"),
            user=c["user"],
            perms=c["perms"],
            adjust_reason=c["adjust_reason"],
            requires_full_allocation=bool(data.get("requires_full_allocation", False)),
            allocations=data.get("allocations"),
        )
        return self._respond(expense, status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        expense = self.get_object()
        data = _body(request)
        extra = sorted(set(data) - self.EDITABLE - {"adjust_reason"})
        if extra:
            raise FinanceError(
                "field_not_editable",
                "Эти поля расхода не редактируются (меняйте через доли, аннулирование или цену "
                "рейса): " + ", ".join(extra),
            )
        if expense.status != "active":
            raise FinanceError("expense_void", "Расход аннулирован", status_code=409)
        before = audit.snapshot(expense)
        if "title" in data:
            title = _text(data, "title")
            expense.title = title[:255]
        if "category" in data:
            cat = HandbookValue.objects.filter(
                pk=_int(data, "category"), handbook__code="expense_category", is_active=True
            ).first()
            if cat is None:
                raise FinanceError("category_not_found", "Категория расходов не найдена")
            expense.category = cat
        periods.assert_finance_writable(request.membership.company_id)
        expense.save()
        audit.log(
            "update",
            expense,
            request.user,
            audit.diff(before, audit.snapshot(expense)),
        )
        return self._respond(expense)

    @action(detail=True, methods=["put"])
    def allocations(self, request, pk=None):
        data = _body(request)
        items = data.get("allocations")
        if not isinstance(items, list):
            raise FinanceError("field_required", "Поле allocations обязательно (список)")
        expense = exp_svc.set_allocations(
            self.get_object(),
            items,
            user=request.user,
            perms=periods.request_perms(request),
            reason=periods.request_adjust_reason(request),
        )
        return self._respond(expense)

    @action(detail=True, methods=["post"])
    def reallocate(self, request, pk=None):
        """Смена метода распределения: {"method": "equal"|"proportional"|"manual"}."""
        data = _body(request)
        expense = exp_svc.reallocate(
            self.get_object(),
            data.get("method"),
            user=request.user,
            perms=periods.request_perms(request),
            reason=periods.request_adjust_reason(request),
        )
        return self._respond(expense)

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        data = _body(request)
        expense = exp_svc.void_expense(
            self.get_object(),
            user=request.user,
            reason=_text(data, "reason"),
            can_adjust=periods.ADJUST_PERMISSION in periods.request_perms(request),
        )
        return self._respond(expense)

    @action(detail=True, methods=["post"], url_path="link-invoice-item")
    def link_invoice_item(self, request, pk=None):
        data = _body(request)
        item = InvoiceItem.objects.filter(pk=_int(data, "invoice_item")).first()
        if item is None:
            raise NotFound("Позиция счёта не найдена")
        invoice_links.link_expense_to_item(
            self.get_object(), item, data.get("amount"), user=request.user
        )
        return self._respond(self.get_object())

    @action(detail=True, methods=["post"], url_path="unlink-invoice-item")
    def unlink_invoice_item(self, request, pk=None):
        data = _body(request)
        expense = self.get_object()
        link = ExpenseInvoiceAllocation.objects.filter(
            pk=_int(data, "link"), expense=expense
        ).first()
        if link is None:
            raise NotFound("Связь не найдена")
        invoice_links.unlink_expense_from_item(
            link, user=request.user, reason=_text(data, "reason", False)
        )
        return self._respond(expense)
