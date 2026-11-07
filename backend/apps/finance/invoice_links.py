"""Связи счетов с новыми сущностями: исходящие позиции -> Income, входящие -> Expense.

- order_income_total: источник «дохода заказа» для проверки «счета не больше дохода»: при
  engine='new' это Σ Income заказа (не void, в валюте заказа, planned допустим как аванс), иначе
  прежний расчёт по строкам OrderService (поведение legacy/shadow не меняется).
- link_item_to_income: позиция ИСХОДЯЩЕГО счёта привязывается к Income (InvoiceItem.line не
  трогается); один Income - не более чем в одном активном (не отменённом) исходящем счёте.
- link_expense_to_item: часть расхода покрывается позицией ВХОДЯЩЕГО счёта
  (ExpenseInvoiceAllocation); частичные суммы допустимы; расхождение сумм ставит needs_review,
  но ничего не блокирует, счета и платежи не меняет.
- release_on_cancel: отмена счёта освобождает связи, история сохраняется.

Порядок блокировок: Order -> Trip -> Income/Expense -> доли -> Invoice -> Payment (при отмене
Income/Expense блокируются ДО счёта: lock_for_cancel).
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.audit import services as audit
from apps.core.tenancy import tenant_context
from apps.forwarding.finance_lines.models import OrderService

from .engine import current_cid, engine_is_new
from .errors import FinanceError
from .expenses import refresh_invoice_variance
from .models import Expense, ExpenseInvoiceAllocation, Income, Invoice, InvoiceItem
from .money import ZERO, quantize_money

ACTIVE_STATUSES = ("draft", "issued")


def order_income_total(order) -> Decimal:
    """Доход заказа для проверки суммы счетов (см. docstring модуля)."""
    cid = current_cid(order.company_id)
    with tenant_context(cid):
        if engine_is_new(cid):
            total = (
                Income.objects.filter(order=order, currency_id=order.currency_id)
                .exclude(status="void")
                .aggregate(t=Sum("amount"))["t"]
            )
        else:
            total = OrderService.objects.filter(order=order).aggregate(t=Sum("income"))["t"]
    return total or ZERO


@transaction.atomic
def link_item_to_income(item: InvoiceItem, income: Income, *, user=None) -> InvoiceItem:
    cid = current_cid(item.company_id)
    with tenant_context(cid):
        income = Income.objects.select_for_update().get(pk=income.pk)  # Income -> Invoice
        invoice = Invoice.objects.select_for_update().get(pk=item.invoice_id)
        item = InvoiceItem.objects.select_for_update().get(pk=item.pk)
        if invoice.direction != "out":
            raise FinanceError(
                "invoice_direction", "К доходу привязываются позиции исходящего счёта"
            )
        if invoice.status not in ACTIVE_STATUSES:
            raise FinanceError("invoice_not_active", "Счёт отменён", status_code=409)
        if income.company_id != invoice.company_id or income.order_id != invoice.order_id:
            raise FinanceError("party_mismatch", "Доход относится к другому заказу")
        if income.status == "void":
            raise FinanceError("income_void", "Доход аннулирован", status_code=409)
        if income.currency_id != invoice.currency_id:
            raise FinanceError(
                "currency_mismatch", "Валюта счёта должна совпадать с валютой дохода"
            )
        if item.income_id == income.pk:
            return item  # идемпотентно
        busy = InvoiceItem.objects.filter(
            income=income,
            invoice__direction="out",
            invoice__status__in=ACTIVE_STATUSES,
            invoice__deleted_at__isnull=True,
        ).exclude(pk=item.pk)
        if busy.exists():
            raise FinanceError(
                "item_already_invoiced", "Доход уже включён в другой счёт", status_code=409
            )
        old = item.income_id
        item.income = income
        item.save(update_fields=["income"])
        audit.log(
            "update",
            invoice,
            user,
            {
                "item_income": [
                    {"item": item.pk, "income": old},
                    {"item": item.pk, "income": income.pk},
                ]
            },
        )
        return item


@transaction.atomic
def link_expense_to_item(
    expense: Expense, item: InvoiceItem, amount, *, user=None
) -> ExpenseInvoiceAllocation:
    """Связывает часть расхода с позицией входящего счёта; повтор с той же суммой - no-op."""
    cid = current_cid(expense.company_id)
    try:
        amount = quantize_money(Decimal(str(amount)))
    except Exception:  # noqa: BLE001
        raise FinanceError("amount_invalid", "Некорректная сумма связи") from None
    if amount <= 0:
        raise FinanceError("amount_invalid", "Сумма связи должна быть положительной")
    with tenant_context(cid):
        expense = Expense.objects.select_for_update().get(pk=expense.pk)  # Expense -> Invoice
        invoice = Invoice.objects.select_for_update().get(pk=item.invoice_id)
        item = InvoiceItem.objects.get(pk=item.pk)
        if invoice.direction != "in":
            raise FinanceError(
                "invoice_direction", "К расходу привязываются позиции входящего счёта"
            )
        if invoice.status not in ACTIVE_STATUSES:
            raise FinanceError("invoice_not_active", "Счёт отменён", status_code=409)
        if expense.status != "active":
            raise FinanceError("expense_void", "Расход аннулирован", status_code=409)
        if invoice.currency_id != expense.currency_id:
            raise FinanceError(
                "currency_mismatch", "Валюта счёта должна совпадать с валютой расхода"
            )
        if expense.carrier_id is not None and invoice.carrier_id != expense.carrier_id:
            raise FinanceError(
                "party_mismatch", "Перевозчик счёта отличается от перевозчика расхода"
            )
        if invoice.trip_id and expense.trip_id and invoice.trip_id != expense.trip_id:
            raise FinanceError("party_mismatch", "Рейс счёта отличается от рейса расхода")
        others = (
            ExpenseInvoiceAllocation.objects.filter(invoice_item=item, released_at__isnull=True)
            .exclude(expense=expense)
            .aggregate(t=Sum("amount"))["t"]
            or ZERO
        )
        if others + amount > item.amount_net:
            raise FinanceError(
                "link_exceeds_item", "Сумма связей больше суммы позиции счёта", status_code=409
            )
        link = ExpenseInvoiceAllocation.objects.filter(expense=expense, invoice_item=item).first()
        if link is None:
            link = ExpenseInvoiceAllocation.objects.create(
                company_id=cid,
                expense=expense,
                invoice_item=item,
                amount=amount,
                created_by=user if getattr(user, "pk", None) else None,
            )
            audit.log("create", link, user, audit.diff({}, audit.snapshot(link)))
        elif link.released_at is not None or link.amount != amount:
            before = audit.snapshot(link)
            link.amount, link.released_at, link.release_reason = amount, None, ""
            link.save()
            audit.log("update", link, user, audit.diff(before, audit.snapshot(link)))
        refresh_invoice_variance(expense, user)
        return link


@transaction.atomic
def unlink_expense_from_item(
    link: ExpenseInvoiceAllocation, *, user=None, reason: str = ""
) -> ExpenseInvoiceAllocation:
    """Снимает связь (запись остаётся историей: released_at/release_reason)."""
    cid = current_cid(link.company_id)
    with tenant_context(cid):
        expense = Expense.objects.select_for_update().get(pk=link.expense_id)
        link = ExpenseInvoiceAllocation.objects.select_for_update().get(pk=link.pk)
        if link.released_at is None:
            before = audit.snapshot(link)
            link.released_at = timezone.now()
            link.release_reason = (reason or "unlinked")[:255]
            link.save()
            audit.log("update", link, user, audit.diff(before, audit.snapshot(link)))
        refresh_invoice_variance(expense, user)
        return link


# --- отмена счёта ----------------------------------------------------------------------


def lock_for_cancel(invoice_pk: int) -> None:
    """Блокирует Income и Expense счёта ДО самого счёта (порядок блокировок)."""
    income_ids = set(
        InvoiceItem.objects.filter(invoice_id=invoice_pk, income__isnull=False).values_list(
            "income_id", flat=True
        )
    )
    expense_ids = set(
        ExpenseInvoiceAllocation.objects.filter(
            invoice_item__invoice_id=invoice_pk, released_at__isnull=True
        ).values_list("expense_id", flat=True)
    )
    if income_ids:
        list(Income.objects.select_for_update().filter(pk__in=income_ids).order_by("pk"))
    if expense_ids:
        list(Expense.objects.select_for_update().filter(pk__in=expense_ids).order_by("pk"))


def release_on_cancel(invoice: Invoice, user=None) -> dict:
    """Освобождает связи отменяемого счёта; возвращает запись для аудита отмены (или {})."""
    changes: dict = {}
    items = InvoiceItem.objects.filter(invoice=invoice, income__isnull=False)
    released_incomes = [{"item": i.pk, "income": i.income_id} for i in items]
    if released_incomes:
        InvoiceItem.objects.filter(invoice=invoice, income__isnull=False).update(income=None)
        changes["released_incomes"] = released_incomes
    links = list(
        ExpenseInvoiceAllocation.objects.select_for_update()
        .filter(invoice_item__invoice=invoice, released_at__isnull=True)
        .order_by("pk")
    )
    if links:
        now = timezone.now()
        for link in links:
            link.released_at, link.release_reason = now, "invoice_cancelled"
            link.save(update_fields=["released_at", "release_reason"])
        changes["released_expense_links"] = [
            {"link": link.pk, "expense": link.expense_id, "amount": str(link.amount)}
            for link in links
        ]
        for expense in Expense.objects.filter(pk__in={link.expense_id for link in links}):
            refresh_invoice_variance(expense, user)
    return changes
