"""Счета: черновик, выставление, отмена, производные суммы и статус.

Правила - в спецификации 2026-11-01-finance-3a-design.md, раздел 4. Все изменяющие функции
вызываются внутри контекста компании (tenant_context) и работают в транзакции.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import DecimalField, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from apps.core.audit import services as audit
from apps.core.numbering.services import next_number
from apps.forwarding.finance_lines.models import OrderService, company_today
from apps.forwarding.models import Carrier, Client, Trip
from apps.forwarding.orders.models import Order

from . import periods
from .errors import FinanceError
from .models import Invoice, InvoiceItem, Payment
from .money import ZERO, compute_totals, to_kzt, vat_percent
from .rates import rate_on

CANCELLED_ORDER_CODE = "cancelled"
MAX_TOTAL = Decimal("999999999999.99")  # предел max_digits=14, decimal_places=2
LIGHT_FIELDS = ("due_date", "external_number", "comment")
DRAFT_FIELDS = (
    "party",
    "order",
    "trip",
    "currency",
    "vat_rate",
    "due_date",
    "external_number",
    "comment",
)
_MONEY = DecimalField(max_digits=18, decimal_places=2)


# --- проверки ------------------------------------------------------------------------


def _not_editable():
    return FinanceError("invoice_not_editable", "Выставленный счёт нельзя изменить")


def _order_ids_of_trip(trip: Trip) -> set[int]:
    return set(trip.consignments.values_list("order_id", flat=True))


def _check_header(direction, party, order, trip, currency):
    """Контрагент, заказ/рейс и валюта согласованы между собой."""
    if direction == "out":
        if not isinstance(party, Client):
            raise FinanceError("party_mismatch", "Счёт клиенту выставляется клиенту")
        if order is None:
            raise FinanceError("party_mismatch", "Укажите заказ счёта")
        if order.client_id != party.pk:
            raise FinanceError("party_mismatch", "Заказ принадлежит другому клиенту")
    else:
        if not isinstance(party, Carrier):
            raise FinanceError("party_mismatch", "Счёт от перевозчика принимается от перевозчика")
        if trip is None and order is None:
            raise FinanceError("party_mismatch", "Укажите рейс или заказ счёта")
        if trip is not None and trip.carrier_id != party.pk:
            raise FinanceError("party_mismatch", "Рейс выполняет другой перевозчик")
    if order is not None and order.currency_id != currency.pk:
        raise FinanceError("currency_mismatch", "Валюта счёта должна совпадать с валютой заказа")
    if trip is not None and trip.currency_id != currency.pk:
        raise FinanceError("currency_mismatch", "Валюта счёта должна совпадать с валютой рейса")


def _check_items(invoice_like: dict, items: list[dict], exclude: Invoice | None, currency):
    """Строки принадлежат заказу (рейса), заказ доступен, строка не в другом активном счёте."""
    direction, order, trip = invoice_like["direction"], invoice_like["order"], invoice_like["trip"]
    allowed = {order.pk} if order is not None else _order_ids_of_trip(trip)
    ids = [it["line"].pk for it in items]
    if len(set(ids)) != len(ids):
        raise FinanceError("item_already_invoiced", "Строка заказа указана в счёте дважды")
    lines = {
        ln.pk: ln
        for ln in OrderService.objects.select_for_update(of=("self",))
        .select_related("order__status")
        .filter(pk__in=ids)
        .order_by("pk")
    }
    for item in items:
        line = lines.get(item["line"].pk)
        if line is None or line.order_id not in allowed:
            raise FinanceError("party_mismatch", "Строка не относится к заказу счёта")
        if line.order.deleted_at is not None or line.order.status.code == CANCELLED_ORDER_CODE:
            raise FinanceError("line_unavailable", "Заказ удалён или отменён")
        if line.order.currency_id != currency.pk:
            raise FinanceError(
                "currency_mismatch", "Валюта счёта должна совпадать с валютой заказа строки"
            )
    busy = InvoiceItem.objects.filter(
        line_id__in=ids,
        invoice__direction=direction,
        invoice__deleted_at__isnull=True,
    ).exclude(invoice__status="cancelled")
    if exclude is not None:
        busy = busy.exclude(invoice=exclude)
    if busy.exists():
        raise FinanceError("item_already_invoiced", "Строка заказа уже включена в другой счёт")


def _totals(items: list, vat_rate):
    """(без НДС, НДС, всего) по позициям; сумма выше предела хранения - ошибка 400, не 500."""
    net, vat, gross = compute_totals([i["amount_net"] for i in items], vat_percent(vat_rate))
    if gross > MAX_TOTAL:
        raise FinanceError("amount_too_large", "Сумма счёта слишком велика")
    return net, vat, gross


def _write_items(invoice: Invoice, items: list[dict]):
    InvoiceItem.objects.filter(invoice=invoice).delete()
    InvoiceItem.objects.bulk_create(
        InvoiceItem(
            company_id=invoice.company_id,
            invoice=invoice,
            title=it["title"],
            amount_net=it["amount_net"],
            line_id=it["line"].pk,
            trip=invoice.trip,
        )
        for it in items
    )


# --- черновик ------------------------------------------------------------------------


@transaction.atomic
def create_draft(
    *,
    direction,
    party,
    order=None,
    trip=None,
    currency,
    vat_rate,
    due_date=None,
    external_number="",
    comment="",
    items,
    user,
) -> Invoice:
    """Создаёт черновик счёта; party - Client (out) или Carrier (in)."""
    _check_header(direction, party, order, trip, currency)
    _check_items({"direction": direction, "order": order, "trip": trip}, items, None, currency)
    _totals(items, vat_rate)
    invoice = Invoice.objects.create(
        direction=direction,
        client=party if direction == "out" else None,
        carrier=party if direction == "in" else None,
        order=order,
        trip=trip,
        currency=currency,
        vat_rate=vat_rate,
        due_date=due_date,
        external_number=external_number,
        comment=comment,
        created_by=user,
    )
    _write_items(invoice, items)
    return invoice


def _party(invoice: Invoice):
    return invoice.client if invoice.direction == "out" else invoice.carrier


@transaction.atomic
def update_draft(invoice: Invoice, *, items=None, **fields) -> Invoice:
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status != "draft":
        raise _not_editable()
    unknown = set(fields) - set(DRAFT_FIELDS)
    if unknown:
        raise ValueError(f"Недопустимые поля черновика: {sorted(unknown)}")
    party = fields.pop("party", None) or _party(invoice)
    for name, value in fields.items():
        setattr(invoice, name, value)
    if party is not None:
        invoice.client = party if invoice.direction == "out" else None
        invoice.carrier = party if invoice.direction == "in" else None
    _check_header(invoice.direction, party, invoice.order, invoice.trip, invoice.currency)
    if items is None:
        items = [
            {"title": i.title, "amount_net": i.amount_net, "line": i.line}
            for i in invoice.items.select_related("line")
        ]
    _check_items(
        {"direction": invoice.direction, "order": invoice.order, "trip": invoice.trip},
        items,
        invoice,
        invoice.currency,
    )
    _totals(items, invoice.vat_rate)
    invoice.save()
    _write_items(invoice, items)
    return invoice


@transaction.atomic
def update_issued(invoice: Invoice, **fields) -> Invoice:
    """У выставленного счёта правятся только срок оплаты, внешний номер и комментарий."""
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status != "issued":
        raise _not_editable()
    if set(fields) - set(LIGHT_FIELDS):
        raise _not_editable()
    for name, value in fields.items():
        setattr(invoice, name, value)
    invoice.save(update_fields=[*fields, "updated_at"])
    return invoice


@transaction.atomic
def delete_draft(invoice: Invoice) -> None:
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status != "draft":
        raise _not_editable()
    invoice.hard_delete()  # черновик без оплат: позиции каскадом, строки заказа освобождаются


# --- выставление и отмена ---------------------------------------------------------------


def _order_income(order: Order) -> Decimal:
    total = OrderService.objects.filter(order=order).aggregate(t=Sum("income"))["t"]
    return total or ZERO


def _active_out_net(order: Order, exclude: Invoice) -> Decimal:
    total = (
        Invoice.objects.filter(order=order, direction="out", status="issued")
        .exclude(pk=exclude.pk)
        .aggregate(t=Sum("total_net"))["t"]
    )
    return total or ZERO


def client_debt_kzt(client: Client) -> Decimal:
    """Долг клиента в тенге: остатки выставленных счетов по курсу счёта."""
    paid = Coalesce(
        Subquery(
            Payment.objects.filter(invoice=OuterRef("pk"))
            .order_by()
            .values("invoice")
            .annotate(s=Sum("amount"))
            .values("s"),
            output_field=_MONEY,
        ),
        Value(ZERO),
        output_field=_MONEY,
    )
    debt = Decimal("0")
    for gross, paid_amount, rate in (
        Invoice.objects.filter(client=client, direction="out", status="issued")
        .annotate(paid=paid)
        .values_list("total_gross", "paid", "rate_to_kzt")
    ):
        debt += to_kzt(gross - paid_amount, rate)
    return debt


@transaction.atomic
def issue(
    invoice: Invoice,
    *,
    user,
    issue_date: date | None = None,
    can_override: bool = False,
    override_reason: str | None = None,
    perms=(),
    adjust_reason: str | None = None,
) -> Invoice:
    invoice = (
        Invoice.objects.select_for_update(of=("self",))
        .select_related("currency", "vat_rate", "client", "order", "trip")
        .get(pk=invoice.pk)
    )
    if invoice.status != "draft":
        raise _not_editable()
    items = list(invoice.items.select_related("line"))
    if not items:
        raise FinanceError("invoice_empty", "В счёте нет позиций")
    if invoice.direction == "out":
        # заказ блокируется ДО подсчёта выставленных сумм: параллельные счета заказа выстраиваются
        # в очередь и не превысят его доход вдвоём
        invoice.order = Order.all_objects.select_for_update().get(pk=invoice.order_id)
    # к моменту выставления заказ, клиент и строки могли измениться
    _check_header(invoice.direction, _party(invoice), invoice.order, invoice.trip, invoice.currency)
    _check_items(
        {"direction": invoice.direction, "order": invoice.order, "trip": invoice.trip},
        [{"title": i.title, "amount_net": i.amount_net, "line": i.line} for i in items],
        invoice,
        invoice.currency,
    )
    issue_date = issue_date or company_today(invoice.company_id)
    adjusted = periods.check_system_date(invoice.company_id, issue_date, perms, adjust_reason)
    rate = rate_on(invoice.currency, issue_date)
    net, vat, gross = _totals([{"amount_net": i.amount_net} for i in items], invoice.vat_rate)
    override_used = None
    if invoice.direction == "out":
        order = invoice.order
        if _active_out_net(order, invoice) + net > _order_income(order):
            raise FinanceError(
                "invoice_exceeds_order_income", "Сумма счетов превышает доход заказа"
            )
        client = Client.objects.select_for_update().get(pk=invoice.client_id)
        if (
            client.credit_limit
            and client_debt_kzt(client) + to_kzt(gross, rate) > client.credit_limit
        ):
            reason = (override_reason or "").strip()
            if not (can_override and reason):
                raise FinanceError("credit_limit_exceeded", "Превышен кредитный лимит клиента")
            override_used = reason
    invoice.number = next_number("invoice_out" if invoice.direction == "out" else "invoice_in")
    if invoice.due_date is None:
        days = invoice.order.payment_delay_days if invoice.order_id else None
        invoice.due_date = issue_date + timedelta(days=days or 0)
    invoice.issue_date, invoice.rate_to_kzt = issue_date, rate
    invoice.total_net, invoice.total_vat, invoice.total_gross = net, vat, gross
    invoice.status = "issued"
    invoice.save()
    changes = {"status": ["draft", "issued"], "number": ["", invoice.number]}
    if override_used:
        changes["credit_limit_override"] = override_used
    if adjusted:
        changes.update(
            periods.adjustment_changes(
                adjust_reason,
                None,
                {"issue_date": issue_date.isoformat(), "number": invoice.number},
            )
        )
    audit.log("update", invoice, user, changes)
    return invoice


@transaction.atomic
def cancel(invoice: Invoice, *, user, perms=(), adjust_reason: str | None = None) -> Invoice:
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status != "issued":
        raise _not_editable()
    adjusted = False
    if invoice.issue_date is not None:  # отмена выставленного счёта - по дате выставления
        adjusted = periods.check_system_date(
            invoice.company_id, invoice.issue_date, perms, adjust_reason
        )
    if Payment.objects.filter(invoice=invoice).exists():
        raise FinanceError("invoice_has_payments", "По счёту есть оплаты: сначала удалите их")
    invoice.status = "cancelled"
    invoice.save(update_fields=["status", "updated_at"])
    # строки освобождаются (можно удалить или выставить заново); название и сумма остаются
    InvoiceItem.objects.filter(invoice=invoice).update(line=None)
    changes = {"status": ["issued", "cancelled"]}
    if adjusted:
        changes.update(
            periods.adjustment_changes(adjust_reason, {"status": "issued"}, {"status": "cancelled"})
        )
    audit.log("update", invoice, user, changes)
    return invoice


# --- производные значения ---------------------------------------------------------------


def paid_amount(invoice: Invoice) -> Decimal:
    return Payment.objects.filter(invoice=invoice).aggregate(t=Sum("amount"))["t"] or ZERO


def balance(invoice: Invoice, paid: Decimal | None = None) -> Decimal:
    return invoice.total_gross - (paid_amount(invoice) if paid is None else paid)


def annotate_paid(queryset):
    """Добавляет счетам paid (сумма неудалённых оплат) подзапросом - без N+1."""
    per_invoice = (
        Payment.objects.filter(invoice=OuterRef("pk"))
        .order_by()
        .values("invoice")
        .annotate(s=Sum("amount"))
        .values("s")
    )
    return queryset.annotate(
        paid=Coalesce(Subquery(per_invoice, output_field=_MONEY), Value(ZERO), output_field=_MONEY)
    )


def display_status(invoice: Invoice, today: date | None, paid: Decimal | None = None) -> str:
    """draft | cancelled | paid | partial | overdue | issued (просрочка - по сегодняшней дате
    в часовом поясе компании, если today не передана)."""
    if invoice.status in ("draft", "cancelled"):
        return invoice.status
    paid = getattr(invoice, "paid", None) if paid is None else paid
    paid = paid_amount(invoice) if paid is None else paid
    remaining = invoice.total_gross - paid
    if remaining <= 0:
        return "paid"
    today = today or company_today(invoice.company_id)
    if invoice.due_date and invoice.due_date < today:
        return "overdue"
    return "partial" if paid > 0 else "issued"
