"""Фильтры списка счетов и оплат. Неверное значение - 400 с именем параметра, не 500."""

from django.db.models import F, Q
from rest_framework.exceptions import ValidationError

from apps.forwarding.orders.filters import date_param, flag_param, int_param

STATUSES = ("draft", "issued", "partial", "paid", "overdue", "cancelled")


def status_q(status: str, today) -> Q:
    """Условие по отображаемому статусу (приоритет как в invoices.display_status);
    требует аннотации paid. Статус «issued» - нет оплат и не просрочен."""
    issued = Q(status="issued")
    unpaid = issued & Q(paid__lt=F("total_gross"))
    overdue = unpaid & Q(due_date__lt=today)
    if status in ("draft", "cancelled"):
        return Q(status=status)
    if status == "paid":
        return issued & Q(paid__gte=F("total_gross"))
    if status == "overdue":
        return overdue
    if status == "partial":
        return unpaid & ~Q(due_date__lt=today) & Q(paid__gt=0)
    return unpaid & ~Q(due_date__lt=today) & Q(paid=0)  # issued


def filter_invoices(qs, params, today):
    if direction := params.get("direction"):
        if direction not in ("out", "in"):
            raise ValidationError({"direction": "Допустимо: out или in"})
        qs = qs.filter(direction=direction)
    status = params.get("status")
    if flag_param(params, "overdue"):
        status = "overdue"
    if status:
        if status not in STATUSES:
            raise ValidationError({"status": f"Допустимо: {', '.join(STATUSES)}"})
        qs = qs.filter(status_q(status, today))
    for name in ("client", "carrier", "order", "trip"):
        if (value := int_param(params, name)) is not None:
            qs = qs.filter(**{f"{name}_id": value})
    if (day := date_param(params, "date_from")) is not None:
        qs = qs.filter(issue_date__gte=day)
    if (day := date_param(params, "date_to")) is not None:
        qs = qs.filter(issue_date__lte=day)
    if term := (params.get("search") or "").strip():
        qs = qs.filter(Q(number__icontains=term) | Q(external_number__icontains=term))
    return qs


def filter_payments(qs, params):
    if (value := int_param(params, "invoice")) is not None:
        qs = qs.filter(invoice_id=value)
    if direction := params.get("direction"):
        if direction not in ("out", "in"):
            raise ValidationError({"direction": "Допустимо: out или in"})
        qs = qs.filter(invoice__direction=direction)
    if method := params.get("method"):
        qs = qs.filter(method=method)
    if (day := date_param(params, "date_from")) is not None:
        qs = qs.filter(date__gte=day)
    if (day := date_param(params, "date_to")) is not None:
        qs = qs.filter(date__lte=day)
    return qs
