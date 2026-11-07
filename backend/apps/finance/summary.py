"""Финансовые плитки дашборда (всё в тенге)."""

from datetime import timedelta

from apps.core.models import Company
from apps.core.tenancy import get_current_company_id
from apps.forwarding.dashboard import month_bounds
from apps.forwarding.finance_lines.services import margin_pct
from apps.forwarding.orders.services import BASE_CURRENCY_CODE

from . import debts, operations
from .models import Payment
from .money import ZERO
from .payments import payment_fx_difference


def finance_summary(today) -> dict:
    clients, carriers = debts.client_debts(today), debts.carrier_debts(today)
    first, nxt = month_bounds(today)
    company = Company.objects.get(pk=get_current_company_id())
    month = operations.journal_summary(
        company.pk,
        date_from=first,
        date_to=nxt - timedelta(days=1),
        accounting_start=company.accounting_start,
    )
    fx = ZERO
    for payment in Payment.objects.filter(
        invoice__status="issued", date__gte=first, date__lt=nxt
    ).select_related("invoice"):
        fx += payment_fx_difference(payment)
    return {
        # currency - валюта итога месяца (базовая валюта компании при engine=new, иначе KZT);
        # долги и курсовая разница считаются в тенге (debts_currency), их перевод - отдельная задача
        "currency": month.get("currency") or BASE_CURRENCY_CODE,
        "debts_currency": BASE_CURRENCY_CODE,
        "excluded": month.get("excluded"),
        "client_debt_kzt": debts.total(clients, "balance_kzt"),
        "overdue_kzt": debts.total(clients, "overdue_kzt"),
        "payable_kzt": debts.total(carriers, "balance_kzt"),
        "month_profit_kzt": month["diff_kzt"],
        "month_margin_pct": margin_pct(month["income_kzt"], month["diff_kzt"]),
        "fx_difference_kzt": fx,
        "unconverted": month["unconverted"],
    }
