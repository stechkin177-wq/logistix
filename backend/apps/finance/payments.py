"""Оплаты по счетам (ручные отметки)."""

from datetime import date
from decimal import Decimal

from django.db import transaction

from apps.core.audit import services as audit

from . import periods
from .errors import FinanceError
from .invoices import balance
from .models import Invoice, Payment
from .money import fx_difference
from .rates import rate_on


@transaction.atomic
def add_payment(
    invoice: Invoice,
    *,
    date: date,
    amount: Decimal,
    method: str,
    payment_ref: str = "",
    comment: str = "",
    user,
    perms=(),
    adjust_reason: str | None = None,
) -> Payment:
    """Оплата в валюте счёта. Счёт блокируется: параллельные оплаты не превысят остаток."""
    periods.assert_finance_writable(invoice.company_id)
    locked = Invoice.objects.select_for_update().select_related("currency").get(pk=invoice.pk)
    if locked.status != "issued":
        raise FinanceError(
            "invoice_not_editable", "Оплату можно внести только по выставленному счёту"
        )
    if amount > balance(locked):
        raise FinanceError("payment_exceeds_balance", "Сумма оплаты больше остатка по счёту")
    # дата оплаты вводится пользователем: закрытый период и обратное датирование - обе проверки
    adjusted = periods.check_user_date(locked.company_id, date, perms, adjust_reason)
    payment = Payment.objects.create(
        invoice=locked,
        date=date,
        amount=amount,
        rate_to_kzt=rate_on(locked.currency, date),
        method=method,
        payment_ref=payment_ref,
        comment=comment,
        created_by=user,
    )
    changes = {"invoice": locked.pk, "amount": str(amount)}
    if adjusted:
        changes.update(
            periods.adjustment_changes(
                adjust_reason, None, {"date": date.isoformat(), "amount": str(amount)}
            )
        )
    audit.log("create", payment, user, changes)
    return payment


@transaction.atomic
def delete_payment(payment: Payment, *, user, perms=(), adjust_reason: str | None = None) -> None:
    periods.assert_finance_writable(payment.company_id)
    Invoice.objects.select_for_update().get(pk=payment.invoice_id)  # сериализует с оплатами
    adjusted = periods.check_system_date(payment.company_id, payment.date, perms, adjust_reason)
    payment.delete()
    changes = {"invoice": payment.invoice_id, "amount": str(payment.amount)}
    if adjusted:
        changes.update(
            periods.adjustment_changes(
                adjust_reason,
                {"date": payment.date.isoformat(), "amount": str(payment.amount)},
                None,
            )
        )
    audit.log("delete", payment, user, changes)


def payment_fx_difference(payment: Payment) -> Decimal:
    """Курсовая разница оплаты в тенге (курс платежа против курса счёта)."""
    invoice = payment.invoice
    return fx_difference(
        payment.amount, payment.rate_to_kzt, invoice.rate_to_kzt, invoice.direction
    )
