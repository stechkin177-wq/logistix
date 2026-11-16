"""Сводка дашборда: GET /api/dashboard/summary/.

Права: orders.view; финансовые поля (month_profit, month_margin_pct) - только с finance.view,
иначе null. Месяц и «сегодня» считаются в часовом поясе компании. В прибыль месяца входят строки
заказов с датой в текущем месяце и не раньше Company.accounting_start; строки отменённых
(код статуса cancelled) и мягко удалённых заказов исключены. Суммируются только заказы в
базовой валюте (BASE_CURRENCY_CODE, currency в ответе); число заказов с данными в других
валютах - excluded_orders (null без finance.view). При engine == 'new' итог считается в базовой
валюте компании (settings.base_currency) по сохранённым снимкам курса; записи прежней базовой
валюты и без курса не конвертируются задним числом, а перечисляются в excluded. Запросов к БД
фиксированное число (не зависит от числа заказов).

Период прибыли настраивается: ?profit_from=YYYY-MM-DD&profit_to=YYYY-MM-DD (границы включительно, не
более 3 лет); без параметров - текущий месяц. В ответе profit_from/profit_to - фактический период.
"""

from datetime import date, datetime, time, timedelta

from django.db.models import Count, Exists, Q, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.permissions import ModuleRequired
from apps.core.api_permissions import permission_required
from apps.core.handbooks.models import HandbookValue
from apps.core.models import Company

from .finance_lines.models import OrderService, company_zone
from .finance_lines.services import ZERO, margin_pct
from .models import Carrier, Client, Order
from .orders.services import BASE_CURRENCY_CODE, COMPLETED_CODE, carried_with_carrier

CANCELLED_CODE = "cancelled"


def _money(value) -> str:
    return format(value, "f")


def month_bounds(today):
    first = today.replace(day=1)
    nxt = (
        first.replace(year=first.year + 1, month=1)
        if first.month == 12
        else first.replace(month=first.month + 1)
    )
    return first, nxt


MAX_PROFIT_PERIOD_DAYS = 3 * 366


def _month_finance(company, today, bounds=None) -> dict:
    """Прибыль месяца (или выбранного периода bounds = [первый день, день после последнего));
    engine == 'new' читает из Income / долей расходов (finance.reports_new)."""
    from apps.finance import reports_new
    from apps.finance.engine import use_new_engine

    if use_new_engine(company):
        first, nxt = bounds or month_bounds(today)
        new = reports_new.month_totals_new(company, first, nxt)
        return {
            k: new[k]
            for k in ("month_profit", "month_margin_pct", "currency", "excluded_orders", "excluded")
        }
    return _month_finance_legacy(company, today, bounds)


def _month_finance_legacy(company, today, bounds=None) -> dict:
    """Прибыль месяца только по заказам в базовой валюте; заказы в других валютах не
    суммируются (разные валюты нельзя складывать) и считаются в excluded_orders."""
    first, nxt = bounds or month_bounds(today)
    start = max(first, company.accounting_start) if company.accounting_start else first
    lines = OrderService.objects.filter(
        order__deleted_at__isnull=True, date__gte=start, date__lt=nxt
    ).exclude(order__status__code=CANCELLED_CODE)
    base = Q(order__currency__code=BASE_CURRENCY_CODE)
    sums = lines.aggregate(
        revenue=Sum("income", filter=base),
        cost=Sum("expense", filter=base),
        excluded=Count("order_id", filter=~base, distinct=True),
    )
    revenue, cost = sums["revenue"] or ZERO, sums["cost"] or ZERO
    profit = revenue - cost
    return {
        "month_profit": profit,
        "month_margin_pct": margin_pct(revenue, profit),
        "currency": BASE_CURRENCY_CODE,
        "excluded_orders": sums["excluded"],
    }


def dashboard_summary(company: Company, *, with_finance: bool, period=None) -> dict:
    """Сводка компании (в её контексте). Деньги - Decimal; сериализует представление.

    period - (первый день, последний день) прибыли включительно; по умолчанию текущий месяц."""
    zone = company_zone(company.pk)
    today = timezone.now().astimezone(zone).date()
    counts = dict(Order.objects.values_list("status_id").annotate(n=Count("pk")))
    statuses = list(HandbookValue.objects.filter(handbook__code="order_status"))
    completed = Order.objects.filter(
        status__handbook__code="order_status", status__code=COMPLETED_CODE
    )
    if company.accounting_start:
        since = datetime.combine(company.accounting_start, time.min, tzinfo=zone)
        completed = completed.filter(completed_at__gte=since)
    unassigned = (
        Order.objects.filter(status__is_final=False)
        .annotate(has_carrier=Exists(carried_with_carrier()))
        .filter(has_carrier=False)
    )
    result = {
        "month": f"{today.year:04d}-{today.month:02d}",
        "active_orders": sum(counts.get(s.pk, 0) for s in statuses if not s.is_final),
        "completed_orders": completed.count(),
        "clients": Client.objects.count(),
        "carriers": Carrier.objects.count(),
        "orders_by_status": [
            {"status_id": s.pk, "status": s.name, "count": counts.get(s.pk, 0)} for s in statuses
        ],
        "unassigned_orders": unassigned.count(),
        "profit_from": None,
        "profit_to": None,
        "month_profit": None,
        "month_margin_pct": None,
        "currency": None,
        "excluded_orders": None,
        "excluded": None,
        "is_partial": False,
    }
    if with_finance:
        bounds = (period[0], period[1] + timedelta(days=1)) if period else month_bounds(today)
        result.update(_month_finance(company, today, bounds))
        result["profit_from"] = bounds[0].isoformat()
        result["profit_to"] = (bounds[1] - timedelta(days=1)).isoformat()
    return result


def parse_profit_period(params) -> tuple[date, date] | None:
    """Период прибыли из query-параметров; ни одного параметра - None (текущий месяц)."""
    raw_from, raw_to = params.get("profit_from"), params.get("profit_to")
    if not raw_from and not raw_to:
        return None
    if not (raw_from and raw_to):
        raise ValidationError({"profit_from": ["Укажите обе даты: profit_from и profit_to"]})
    try:
        first, last = date.fromisoformat(raw_from), date.fromisoformat(raw_to)
    except ValueError:
        raise ValidationError({"profit_from": ["Дата в формате ГГГГ-ММ-ДД"]}) from None
    if first > last:
        raise ValidationError({"profit_to": ["Конец периода раньше начала"]})
    if (last - first).days > MAX_PROFIT_PERIOD_DAYS:
        raise ValidationError({"profit_to": ["Период не может быть длиннее трёх лет"]})
    return first, last


class DashboardSummaryView(APIView):
    def get_permissions(self):
        return [ModuleRequired("logistics")(), permission_required("orders.view")()]

    def get(self, request):
        membership = request.membership
        with_finance = "finance.view" in membership.role.permissions
        period = parse_profit_period(request.query_params) if with_finance else None
        data = dashboard_summary(membership.company, with_finance=with_finance, period=period)
        for key in ("month_profit", "month_margin_pct"):
            if data[key] is not None:
                data[key] = _money(data[key])
        if data["excluded"] is not None:
            from apps.finance.api.serializers import excluded_data

            data["excluded"] = excluded_data(data["excluded"])
        data["is_partial"] = data["excluded"] is not None
        return Response(data)
