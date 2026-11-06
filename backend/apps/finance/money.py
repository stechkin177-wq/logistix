"""Денежная арифметика финансов: единое место округления и пересчёта (Decimal).

Все суммы - Decimal; округление до копеек только здесь (ROUND_HALF_UP).
"""

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .errors import FinanceError

CENT = Decimal("0.01")
HUNDRED = Decimal("100")
ZERO = Decimal("0.00")


def quantize_money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def vat_percent(value) -> Decimal:
    """Процент НДС из значения справочника vat_rate: code none - 0, иначе число 0..100."""
    code = (value.code or "").strip()
    if code == "none":
        return Decimal("0")
    try:
        percent = Decimal(code)
    except InvalidOperation:
        percent = None
    if percent is None or not percent.is_finite() or not (0 <= percent <= 100):
        raise FinanceError("invalid_vat", f"Некорректная ставка НДС «{value.name}»")
    return percent


def compute_totals(
    amounts: Iterable[Decimal], percent: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    """(без НДС, НДС, всего). НДС считается от общей суммы, а не по позициям."""
    net = quantize_money(sum((Decimal(a) for a in amounts), Decimal("0")))
    vat = quantize_money(net * Decimal(percent) / HUNDRED)
    return net, vat, net + vat


def to_kzt(amount: Decimal, rate: Decimal) -> Decimal:
    return quantize_money(Decimal(amount) * Decimal(rate))


def fx_difference(
    amount: Decimal, pay_rate: Decimal, invoice_rate: Decimal, direction: str
) -> Decimal:
    """Курсовая разница оплаты в тенге: плюс для out при росте курса, минус для in."""
    diff = quantize_money(Decimal(amount) * (Decimal(pay_rate) - Decimal(invoice_rate)))
    return diff if direction == "out" else -diff
