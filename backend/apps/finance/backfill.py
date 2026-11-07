"""Заполнение снимков курса к базовой валюте у прежних счетов и оплат (1.4.14).

Только детерминированный случай: базовая валюта компании = KZT и у записи есть rate_to_kzt ->
base_currency = KZT, rate_to_base = rate_to_kzt (копия, не выдумка), дата = дата выставления
(счёт) / оплаты. Остальные случаи не трогаются и остаются «без базового курса». Идемпотентно:
затрагиваются только записи без снимка. Суммы, rate_to_kzt и прочие поля не меняются.
"""

from django.db import transaction
from django.db.models import F

from apps.core.handbooks.models import HandbookValue
from apps.core.tenancy import tenant_context

from .models import CompanyFinancialSettings, Invoice, Payment

KZT = "KZT"


def backfill_company(company_id: int, dry_run: bool = False) -> dict:
    """Результат: {'base': код|None, 'applicable': bool, 'invoices': n, 'payments': n,
    'skipped_invoices': n, 'skipped_payments': n} - сколько записей заполнено/было бы заполнено
    и сколько осталось без снимка (не детерминированный случай)."""
    with tenant_context(company_id):
        base = (
            CompanyFinancialSettings.objects.filter(company_id=company_id)
            .select_related("base_currency")
            .first()
        )
        base = base.base_currency if base is not None else None
        report = {
            "base": base.code if base else None,
            "applicable": bool(base is not None and base.code == KZT),
            "invoices": 0,
            "payments": 0,
        }
        invoices = Invoice.all_objects.filter(base_currency__isnull=True)
        payments = Payment.all_objects.filter(base_currency__isnull=True)
        fit_inv = invoices.filter(rate_to_kzt__isnull=False, issue_date__isnull=False)
        fit_pay = payments.filter(rate_to_kzt__isnull=False)
        report["skipped_invoices"] = invoices.count()
        report["skipped_payments"] = payments.count()
        if not report["applicable"]:
            return report
        kzt = HandbookValue.objects.filter(
            handbook__code="currency", code=KZT, company_id=company_id
        ).first()
        if kzt is None or kzt.pk != base.pk:
            report["applicable"] = False
            return report
        report["invoices"] = fit_inv.count()
        report["payments"] = fit_pay.count()
        if not dry_run:
            with transaction.atomic():
                fit_inv.update(
                    base_currency=kzt,
                    rate_to_base=F("rate_to_kzt"),
                    rate_to_base_date=F("issue_date"),
                )
                fit_pay.update(
                    base_currency=kzt, rate_to_base=F("rate_to_kzt"), rate_to_base_date=F("date")
                )
        report["skipped_invoices"] -= report["invoices"]
        report["skipped_payments"] -= report["payments"]
        return report
