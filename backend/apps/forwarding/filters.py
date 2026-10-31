"""Фильтры и сортировка списков клиентов и перевозчиков (по образцу handbooks.api)."""

from django.db.models import F, Q
from rest_framework.exceptions import ValidationError

STATUS_VALUES = ("active", "inactive")
DEFAULT_ORDERING = "name"


def _ordering_expression(field: str):
    desc = field.startswith("-")
    name = field.lstrip("-")
    if name == "rating":  # без рейтинга всегда в конце
        return F(name).desc(nulls_last=True) if desc else F(name).asc(nulls_last=True)
    return F(name).desc() if desc else F(name).asc()


def filter_parties(qs, params, ordering_fields):
    """q (название или БИН/ИИН, без учёта регистра), type (id), status, ordering."""
    if q := (params.get("q") or "").strip():
        qs = qs.filter(Q(name__icontains=q) | Q(bin_iin__icontains=q))
    if (type_id := params.get("type")) not in (None, ""):
        if not type_id.isascii() or not type_id.isdigit():
            raise ValidationError({"type": "Ожидается числовой id"})
        qs = qs.filter(type_id=int(type_id))
    if value := params.get("status"):
        if value not in STATUS_VALUES:
            raise ValidationError({"status": "Допустимо: active, inactive"})
        qs = qs.filter(status=value)
    ordering = params.get("ordering") or DEFAULT_ORDERING
    allowed = {*ordering_fields, *(f"-{f}" for f in ordering_fields)}
    if ordering not in allowed:
        raise ValidationError({"ordering": f"Допустимо: {', '.join(sorted(allowed))}"})
    return qs.order_by(_ordering_expression(ordering), "id")
