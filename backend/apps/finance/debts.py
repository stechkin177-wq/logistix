"""Долги по контрагентам: только выставленные счета; в тенге по курсу счёта.

Считается несколькими агрегатными запросами (число запросов не зависит от числа счетов):
счета и оплаты группируются по (контрагент, валюта, курс счёта, просрочен ли счёт).
"""

from collections import defaultdict
from decimal import Decimal

from django.db.models import BooleanField, ExpressionWrapper, Q, Sum

from apps.forwarding.models import Carrier, Client

from .models import Invoice, Payment
from .money import ZERO, quantize_money


def _groups(direction, party_field, today):
    overdue = ExpressionWrapper(Q(due_date__lt=today), BooleanField())
    invoices = (
        Invoice.objects.filter(direction=direction, status="issued")
        .order_by()
        .values(party_field, "currency__code", "rate_to_kzt", is_od=overdue)
        .annotate(gross=Sum("total_gross"))
    )
    paid_overdue = ExpressionWrapper(Q(invoice__due_date__lt=today), BooleanField())
    payments = (
        Payment.objects.filter(invoice__direction=direction, invoice__status="issued")
        .order_by()
        .values(
            f"invoice__{party_field}",
            "invoice__currency__code",
            "invoice__rate_to_kzt",
            is_od=paid_overdue,
        )
        .annotate(paid=Sum("amount"))
    )
    table = defaultdict(lambda: {"gross": ZERO, "paid": ZERO})
    for r in invoices:
        table[(r[party_field], r["currency__code"], r["rate_to_kzt"], r["is_od"])]["gross"] += r[
            "gross"
        ]
    for r in payments:
        key = (
            r[f"invoice__{party_field}"],
            r["invoice__currency__code"],
            r["invoice__rate_to_kzt"],
            r["is_od"],
        )
        table[key]["paid"] += r["paid"]
    return table


def _debts(direction, party_field, model, today) -> list[dict]:
    rows: dict[int, dict] = {}
    for (party_id, code, rate, is_od), v in _groups(direction, party_field, today).items():
        row = rows.setdefault(
            party_id,
            {
                "id": party_id,
                "issued_kzt": ZERO,
                "paid_kzt": ZERO,
                "balance_kzt": ZERO,
                "overdue_kzt": ZERO,
                "by_currency": {},
            },
        )
        balance = v["gross"] - v["paid"]
        row["issued_kzt"] += quantize_money(v["gross"] * rate)
        row["paid_kzt"] += quantize_money(v["paid"] * rate)
        row["balance_kzt"] += quantize_money(balance * rate)
        if is_od:
            row["overdue_kzt"] += quantize_money(balance * rate)
        cur = row["by_currency"].setdefault(code, {"issued": ZERO, "paid": ZERO, "balance": ZERO})
        cur["issued"] += v["gross"]
        cur["paid"] += v["paid"]
        cur["balance"] += balance
    parties = {p.pk: p for p in model.objects.filter(pk__in=rows)}
    for pid, row in rows.items():
        row["name"] = parties[pid].name if pid in parties else ""
        if model is Client:
            limit = parties[pid].credit_limit if pid in parties else ZERO
            row["credit_limit"] = limit
            row["limit_usage_pct"] = (
                quantize_money(row["balance_kzt"] / limit * 100) if limit else None
            )
    return sorted(rows.values(), key=lambda r: (-r["balance_kzt"], r["name"]))


def client_debts(today) -> list[dict]:
    return _debts("out", "client_id", Client, today)


def carrier_debts(today) -> list[dict]:
    return _debts("in", "carrier_id", Carrier, today)


def total(rows: list[dict], key: str) -> Decimal:
    return sum((r[key] for r in rows), ZERO)
