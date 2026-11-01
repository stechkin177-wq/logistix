from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal as D

import pytest
import time_machine

from apps.core.api.auth import issue_tokens
from apps.core.tests.test_rls import app_role
from apps.finance.tests.helpers import add_line, cur, make_carrier, set_rate, vat
from apps.forwarding.tests.test_trips import make_cargos, svc_create

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 5, 20, 12, 0, tzinfo=dt_tz.utc)
F = "/api/finance"


def test_full_flow_two_currencies(admin_client, company, admin_user):
    """Заказ в USD -> счёт с НДС 16% -> две оплаты по разным курсам -> расход рейса ->
    счёт перевозчика -> оплата; сводка и долги сходятся. Всё под ролью приложения (RLS)."""
    set_rate(company, "USD", 450, day=date(2026, 5, 1))
    set_rate(company, "USD", 460, day=date(2026, 5, 5))
    set_rate(company, "USD", 470, day=date(2026, 5, 10))
    order, ids = make_cargos(company, 1, currency=cur(company, "USD"))
    line = add_line(company, order, income=1000)
    carrier = make_carrier(company)
    trip = svc_create(company, ids, carrier=carrier, data={"price": D("600"), "currency": cur(company, "USD")})
    with time_machine.travel(NOW, tick=False), app_role():
        admin_client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {issue_tokens(admin_user, company.id)['access']}"
        )
        r = admin_client.post(
            f"{F}/invoices/",
            {
                "direction": "out", "party": order.client_id, "order": order.pk,
                "currency": cur(company, "USD").pk, "vat_rate": vat(company, "16").pk,
                "due_date": "2026-06-30",
                "items": [{"title": "Перевозка", "amount_net": "1000", "line": line.pk}],
            },
            format="json",
        )
        assert r.status_code == 201, r.content
        inv = r.data["id"]
        assert admin_client.post(f"{F}/invoices/{inv}/issue/", {}, format="json").status_code == 200
        got = admin_client.get(f"{F}/invoices/{inv}/").data
        assert got["totals"]["gross"] == "1160.00" and got["rate_to_kzt"] == "470.000000"  # курс на сегодня 20.05
        for day, amount in (("2026-05-05", "600"), ("2026-05-10", "560")):
            r = admin_client.post(
                f"{F}/invoices/{inv}/payments/", {"date": day, "amount": amount, "method": "bank"}, format="json"
            )
            assert r.status_code == 201, r.content
        got = admin_client.get(f"{F}/invoices/{inv}/").data
        assert got["display_status"] == "paid" and got["balance"] == "0.00"

        # расход рейса -> счёт перевозчика
        exp = admin_client.post(
            f"{F}/trips/{trip.pk}/expense-lines/",
            {"allocations": [{"order_id": order.pk, "amount": "600"}]}, format="json",
        )
        assert exp.status_code == 201, exp.content
        r = admin_client.post(
            f"{F}/invoices/",
            {
                "direction": "in", "party": carrier.pk, "trip": trip.pk, "external_number": "К-5",
                "currency": cur(company, "USD").pk, "vat_rate": vat(company, "none").pk,
                "items": [{"title": "Рейс", "amount_net": "600", "line": exp.data["lines"][0]["id"]}],
            },
            format="json",
        )
        assert r.status_code == 201, r.content
        cin = r.data["id"]
        assert admin_client.post(f"{F}/invoices/{cin}/issue/", {}, format="json").status_code == 200

        summary = admin_client.get(f"{F}/summary/").data
        clients = admin_client.get(f"{F}/debts/clients/").data["results"]
        carriers = admin_client.get(f"{F}/debts/carriers/").data["results"]
        ops = admin_client.get(f"{F}/operations/").data["summary"]

    assert summary["client_debt_kzt"] == "0.00"  # клиент оплатил всё
    assert summary["payable_kzt"] == "282000.00"  # 600 USD * 470 (курс счёта)
    assert clients[0]["paid_kzt"] == "545200.00"  # 1160 USD * 470 по курсу счёта
    assert carriers[0]["balance_kzt"] == "282000.00"
    # курсовая разница: 600*(460-470) + 560*(470-470) = -6000
    assert summary["fx_difference_kzt"] == "-6000.00"
    assert ops["by_currency"]["USD"] == {"income": "1000.00", "expense": "600.00", "diff": "400.00"}
