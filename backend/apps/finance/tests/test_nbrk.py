from decimal import Decimal

from apps.finance.nbrk import parse_rates

FEED = """<?xml version="1.0" encoding="utf-8"?>
<rates><generator>nationalbank.kz</generator><title>Official rates</title>
<item><fullname>ДОЛЛАР США</fullname><title>USD</title><description>520.50</description><quant>1</quant></item>
<item><fullname>ЕВРО</fullname><title>EUR</title><description>600.10</description><quant>1</quant></item>
<item><fullname>РОССИЙСКИЙ РУБЛЬ</fullname><title>RUB</title><description>6.50</description><quant>1</quant></item>
<item><fullname>КИТАЙСКИЙ ЮАНЬ</fullname><title>CNY</title><description>720</description><quant>10</quant></item>
<item><fullname>ФУНТ</fullname><title>GBP</title><description>700</description><quant>1</quant></item>
</rates>""".encode()


def test_parse_keeps_only_needed_currencies_per_unit():
    rates = parse_rates(FEED)
    assert set(rates) == {"USD", "EUR", "RUB", "CNY"}
    assert rates["USD"] == Decimal("520.500000")
    assert rates["CNY"] == Decimal("72.000000")  # 720 за 10 юаней
