from decimal import Decimal as D

import pytest

from apps.core.handbooks.models import HandbookValue
from apps.core.tenancy import tenant_context
from apps.finance.errors import FinanceError
from apps.finance.money import (
    compute_totals,
    fx_difference,
    quantize_money,
    to_kzt,
    vat_percent,
)


def test_round_half_up():
    assert quantize_money(D("0.005")) == D("0.01")
    assert quantize_money(D("2.675")) == D("2.68")
    assert quantize_money(D("-0.005")) == D("-0.01")
    assert quantize_money(D("1")) == D("1.00")


def test_totals_vat_on_sum():
    net, vat, gross = compute_totals([D("0.33"), D("0.33"), D("0.33")], D("16"))
    assert (net, vat, gross) == (D("0.99"), D("0.16"), D("1.15"))


def test_totals_zero():
    assert compute_totals([], D("16")) == (D("0.00"), D("0.00"), D("0.00"))


@pytest.mark.django_db
def test_vat_percent_from_handbook(company):
    with tenant_context(company.id):
        by_code = {v.code: v for v in HandbookValue.objects.filter(handbook__code="vat_rate")}
        assert vat_percent(by_code["none"]) == D("0")
        assert vat_percent(by_code["12"]) == D("12")
        assert vat_percent(by_code["16"]) == D("16")


@pytest.mark.parametrize("code", ["abc", "101", "-1", ""])
@pytest.mark.django_db
def test_vat_bad_code_raises(company, code):
    with tenant_context(company.id):
        value = HandbookValue.objects.filter(handbook__code="vat_rate").first()
        value.code = code
        with pytest.raises(FinanceError) as exc:
            vat_percent(value)
    assert exc.value.detail.code == "invalid_vat"


def test_to_kzt():
    assert to_kzt(D("100.00"), D("480.123456")) == D("48012.35")


def test_fx_difference_sign():
    assert fx_difference(D("100"), D("470"), D("450"), "out") == D("2000.00")
    assert fx_difference(D("100"), D("470"), D("450"), "in") == D("-2000.00")
