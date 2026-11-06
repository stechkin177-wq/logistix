"""Оплаты по счетам (ручные отметки)."""

from datetime import date
from decimal import Decimal

from django.db import transaction

from apps.core.audit import services as audit

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
) -> Payment:
    """Оплата в валюте счёта. Счёт блокируется: параллельные оплаты не превысят остаток."""
    locked = Invoice.objects.select_for_update().select_related("currency").get(pk=invoice.pk)
    if locked.status != "issued":
        raise FinanceError(
            "invoice_not_editable", "Оплату можно внести только по выставленному счёту"
        )
    if amount > balance(locked):
        raise FinanceError("payment_exceeds_balance", "Сумма оплаты больше остатка по счёту")
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
    audit.log("create", payment, user, {"invoice": locked.pk, "amount": str(amount)})
    return payment


@transaction.atomic
def delete_payment(payment: Payment, *, user) -> None:
    Invoice.objects.select_for_update().get(pk=payment.invoice_id)  # сериализует с оплатами
    payment.delete()
    audit.log(
        "delete", payment, user, {"invoice": payment.invoice_id, "amount": str(payment.amount)}
    )


def payment_fx_difference(payment: Payment) -> Decimal:
    """Курсовая разница оплаты в тенге (курс платежа против курса счёта)."""
    invoice = payment.invoice
    return fx_difference(
        payment.amount, payment.rate_to_kzt, invoice.rate_to_kzt, invoice.direction
    )
