# ruff: noqa: E501
"""API настроек финансов, сопоставления статусов, периодов, статуса миграции и финкарточек (1.4.12).

Права: настройки, сопоставление статусов, миграция - finance.manage_settings; закрытие периодов -
finance.close_period; открытие - finance.reopen_period; просмотр периодов и карточек -
finance.view. Все проверки на сервере.
"""

from decimal import Decimal

from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import permission_required
from apps.core.handbooks.models import HandbookValue
from apps.forwarding.finance_lines.services import order_totals
from apps.forwarding.models import Order
from apps.forwarding.trips.models import Trip

from .. import expenses as exp_svc
from .. import fx, migration, periods, settings_service, status_mapping
from .. import trip_expense as te
from ..engine import company_engine
from ..errors import FinanceError
from ..fx import get_settings
from ..models import (
    Expense,
    FinanceMigrationIssue,
    FinanceMigrationRun,
    FinancialPeriod,
    Income,
    Invoice,
)
from .ledger import _body, _date, _int, _text, ctx, expense_data, income_data
from .serializers import money


def _perm(code):
    return [ModuleRequired("finance")(), permission_required(code)()]


def _hv(value):
    return {"id": value.pk, "code": value.code, "name": value.name} if value else None


# --- настройки ---------------------------------------------------------------------------------


def settings_data(company) -> dict:
    s = get_settings(company)
    report = status_mapping.status_mapping_report(company)
    return {
        "base_currency": _hv(s.base_currency),
        "accounting_method": s.accounting_method,
        "default_vat_rate": _hv(s.default_vat_rate),
        "fiscal_year_start_month": s.fiscal_year_start_month,
        "allow_backdating": s.allow_backdating,
        "engine": s.engine,
        "cutover_date": s.cutover_date,
        "income_recognition": s.income_recognition,
        "completed_status": _hv(s.completed_status),
        "expense_creation_mode": s.expense_creation_mode,
        "sync_carrier_price": s.sync_carrier_price,
        "engine_switched_at": s.engine_switched_at,
        "financial_writes_frozen": s.financial_writes_frozen,
        "unmapped": report["unmapped_system_codes"],
        "switch_blocked": report["switch_blocked"],
        "blockers": report["blockers"],
    }


class EngineView(APIView):
    """Лёгкий признак режима учёта для интерфейса (finance.view)."""

    def get_permissions(self):
        return _perm("finance.view")

    def get(self, request):
        s = get_settings(request.membership.company)
        return Response(
            {
                "engine": s.engine,
                "financial_writes_frozen": s.financial_writes_frozen,
                "base_currency": _hv(s.base_currency),
            }
        )


class FinanceSettingsView(APIView):
    def get_permissions(self):
        return _perm("finance.manage_settings")

    def get(self, request):
        return Response(settings_data(request.membership.company))

    def patch(self, request):
        data = dict(_body(request))
        company = request.membership.company
        reason = data.pop("reason", None)
        base = data.pop("base_currency", None)
        if base is not None:
            currency = HandbookValue.objects.filter(
                pk=base, handbook__code="currency", is_active=True
            ).first()
            if currency is None:
                raise FinanceError("base_currency_invalid", "Валюта не найдена")
            fx.change_base_currency(company, currency, request.user, reason or "")
        if data:
            settings_service.update_settings(company, data, request.user)
        return Response(settings_data(company))


class StatusMappingView(APIView):
    def get_permissions(self):
        return _perm("finance.manage_settings")

    def get(self, request):
        return Response(status_mapping.status_mapping_report(request.membership.company))

    def post(self, request):
        data = _body(request)
        company = request.membership.company
        status_mapping.map_system_status(
            company, _int(data, "value"), _text(data, "code"), user=request.user
        )
        return Response(
            status_mapping.status_mapping_report(company), status=status.HTTP_201_CREATED
        )


# --- периоды ------------------------------------------------------------------------------------


def period_data(p: FinancialPeriod) -> dict:
    return {
        "id": p.pk,
        "year": p.year,
        "month": p.month,
        "status": p.status,
        "closed_at": p.closed_at,
        "closed_by": (p.closed_by.email if p.closed_by_id else None),
        "comment": p.comment,
        "events": [
            {
                "action": e.action,
                "user": e.user.email if e.user_id else None,
                "reason": e.reason,
                "created_at": e.at,
            }
            for e in p.events.all()
        ],
    }


class PeriodsView(APIView):
    def get_permissions(self):
        code = "finance.close_period" if self.request.method == "POST" else "finance.view"
        return _perm(code)

    def get(self, request):
        qs = FinancialPeriod.objects.prefetch_related("events__user").select_related("closed_by")
        return Response([period_data(p) for p in qs.order_by("-year", "-month")])

    def post(self, request):
        data = _body(request)
        period = periods.close_period(
            request.membership.company,
            _int(data, "year"),
            _int(data, "month"),
            request.user,
            _text(data, "comment", False),
        )
        fresh = FinancialPeriod.objects.prefetch_related("events__user").get(pk=period.pk)
        return Response(period_data(fresh), status=status.HTTP_201_CREATED)


class PeriodReopenView(APIView):
    def get_permissions(self):
        return _perm("finance.reopen_period")

    def post(self, request, pk):
        period = FinancialPeriod.objects.filter(pk=pk).first()
        if period is None:
            raise NotFound("Период не найден")
        periods.reopen_period(period, request.user, _text(_body(request), "reason", False))
        fresh = FinancialPeriod.objects.prefetch_related("events__user").get(pk=pk)
        return Response(period_data(fresh))


# --- миграция ------------------------------------------------------------------------------------


def run_data(r: FinanceMigrationRun) -> dict:
    s = r.summary or {}
    return {
        "id": r.pk,
        "kind": r.kind,
        "mode": r.mode,
        "status": r.status,
        "started_at": r.started_at,
        "finished_at": r.finished_at,
        "unexplained": s.get("unexplained"),
        "not_reflected": len(s.get("not_reflected") or []),
        "counters": s.get("counters"),
    }


def issue_data(i: FinanceMigrationIssue) -> dict:
    return {
        "id": i.pk,
        "issue_type": i.issue_type,
        "severity": i.severity,
        "source_model": i.source_model,
        "source_id": i.source_id,
        "message": i.message,
        "details": i.details,
        "status": i.status,
        "resolution": i.resolution,
        "resolution_note": i.resolution_note,
        "created_at": i.created_at,
    }


class MigrationView(APIView):
    def get_permissions(self):
        return _perm("finance.manage_settings")

    def get(self, request):
        runs = FinanceMigrationRun.objects.order_by("-id")[:10]
        open_issues = FinanceMigrationIssue.objects.filter(status="open").order_by("-id")[:200]
        return Response(
            {
                "runs": [run_data(r) for r in runs],
                "open_issues": [issue_data(i) for i in open_issues],
                "open_count": FinanceMigrationIssue.objects.filter(status="open").count(),
            }
        )


class MigrationIssueResolveView(APIView):
    def get_permissions(self):
        return _perm("finance.manage_settings")

    def post(self, request, pk):
        issue = FinanceMigrationIssue.objects.filter(pk=pk).first()
        if issue is None:
            raise NotFound("Проблема не найдена")
        data = _body(request)
        params = {k: data[k] for k in ("trip", "category") if data.get(k) not in (None, "")}
        resolved = migration.resolve_issue(
            issue, request.user, _text(data, "note"), data.get("resolution") or None, **params
        )
        return Response(issue_data(resolved))


# --- финкарточки -----------------------------------------------------------------------------


def _invoice_row(i: Invoice) -> dict:
    return {
        "id": i.pk,
        "number": i.number,
        "direction": i.direction,
        "status": i.status,
        "currency": _hv(i.currency),
        "total_gross": money(i.total_gross),
        "issue_date": i.issue_date,
    }


class OrderFinanceView(APIView):
    """GET /api/orders/{id}/finance/: доходы, расходы с долями, счета, итоги, needs_review."""

    def get_permissions(self):
        return _perm("finance.view")

    def get(self, request, pk):
        order = Order.objects.filter(pk=pk).select_related("currency").first()
        if order is None:
            raise NotFound("Заказ не найден")
        incomes = (
            Income.objects.filter(order=order)
            .select_related("order", "currency", "trip", "fx_base_currency")
            .order_by("-id")
        )
        expenses = (
            Expense.objects.filter(allocations__order=order)
            .select_related("category", "currency", "trip", "carrier")
            .prefetch_related("allocations__order", "allocations__trip")
            .distinct()
            .order_by("-expense_date", "-id")
        )
        invoices = Invoice.objects.filter(order=order).select_related("currency").order_by("-id")
        totals = order_totals(order)
        rows = []
        for e in expenses:
            row = expense_data(e)
            # для карточки заказа важна доля именно этого заказа
            row["order_amount"] = money(
                sum((a.amount for a in e.allocations.all() if a.order_id == order.pk), Decimal("0"))
            )
            rows.append(row)
        return Response(
            {
                "engine": company_engine(request.membership.company_id),
                "order": {"id": order.pk, "number": order.number, "currency": _hv(order.currency)},
                "incomes": [income_data(i) for i in incomes],
                "expenses": rows,
                "invoices": [_invoice_row(i) for i in invoices],
                "totals": {k: (money(v) if v is not None else None) for k, v in totals.items()},
                "needs_review": any(r["needs_review"] for r in rows),
            }
        )


class TripFinanceView(APIView):
    """GET /api/trips/{id}/finance/: расход перевозчика и расхождение со счетами."""

    def get_permissions(self):
        return _perm("finance.view")

    def get(self, request, pk):
        trip = Trip.objects.filter(pk=pk).select_related("currency", "carrier").first()
        if trip is None:
            raise NotFound("Рейс не найден")
        engine = company_engine(request.membership.company_id)
        expenses = (
            Expense.objects.filter(trip=trip)
            .select_related("category", "currency", "trip", "carrier")
            .prefetch_related("allocations__order", "allocations__trip")
            .order_by("-id")
        )
        rows = [expense_data(e) for e in expenses]
        active = next(
            (r for r in rows if r["kind"] == "carrier_transport" and r["status"] == "active"), None
        )
        invoices = Invoice.objects.filter(trip=trip, direction="in").select_related("currency")
        return Response(
            {
                "engine": engine,
                "trip": {
                    "id": trip.pk,
                    "number": trip.number,
                    "carrier": {"id": trip.carrier_id, "name": trip.carrier.name}
                    if trip.carrier_id
                    else None,
                    "carrier_price": money(trip.carrier_price),
                    "currency": _hv(trip.currency),
                },
                "expense": active,
                "expenses": rows,
                "invoices": [_invoice_row(i) for i in invoices.order_by("-id")],
                "can_create_expense": trip.carrier_id is not None and active is None,
                "needs_review": any(r["needs_review"] for r in rows),
                "invoice_variance": active["invoice_variance"] if active else None,
            }
        )


class CarrierExpenseView(APIView):
    """POST /api/finance/trips/{id}/carrier-expense/: расход из цены рейса (engine-aware)."""

    def get_permissions(self):
        return _perm("finance.create")

    def post(self, request, pk):
        trip = Trip.objects.filter(pk=pk).first()
        if trip is None:
            raise NotFound("Рейс не найден")
        data = request.data if hasattr(request.data, "get") else {}
        c = ctx(request)
        allocations = data.get("allocations")
        if company_engine(request.membership.company_id) == "new":
            expense = exp_svc.create_carrier_expense(
                trip,
                user=c["user"],
                perms=c["perms"],
                allocations=allocations,
                expense_date=_date(data, "expense_date", False),
                adjust_reason=c["adjust_reason"],
                category=data.get("category"),
                allocation_method=data.get("allocation_method"),
            )
            fresh = (
                Expense.objects.select_related("category", "currency", "trip", "carrier")
                .prefetch_related("allocations__order", "allocations__trip")
                .get(pk=expense.pk)
            )
            return Response(
                {"engine": "new", "expense": expense_data(fresh)}, status=status.HTTP_201_CREATED
            )
        if not allocations:  # прежнее поведение: предложение по заказам рейса
            allocations = [
                {"order_id": s["order_id"], "amount": s["amount"]}
                for s in te.trip_expense_lines(trip)["suggestion"]
            ]
        lines = te.create_trip_expense(
            trip,
            [{"order_id": a["order_id"], "amount": a["amount"]} for a in allocations],
            user=c["user"],
            perms=c["perms"],
            adjust_reason=c["adjust_reason"],
        )
        return Response(
            {
                "engine": company_engine(request.membership.company_id),
                "lines": [
                    {"id": ln.pk, "order": ln.order_id, "expense": money(ln.expense)}
                    for ln in lines
                ],
            },
            status=status.HTTP_201_CREATED,
        )
