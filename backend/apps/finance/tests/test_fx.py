"""Валютный слой (1.4.2): курсы, снимки, смена базовой валюты."""

import threading
from datetime import date
from decimal import Decimal

import pytest
from django.db import connection

from apps.core.audit.models import AuditLog
from apps.core.handbooks.models import HandbookValue
from apps.core.tenancy import tenant_context
from apps.finance.errors import FinanceError
from apps.finance.fx import (
    apply_snapshot,
    change_base_currency,
    fx_snapshot,
    legacy_missing_snapshot,
    quantize_rate,
    resolve_rate,
)
from apps.finance.models import CompanyFinancialSettings, ExchangeRate, Expense, Income
from apps.finance.tests.helpers import cur, first_user, make_order

pytestmark = pytest.mark.django_db
D = Decimal
D1, D2, D3 = date(2026, 6, 1), date(2026, 6, 10), date(2026, 6, 20)


def rate(company, code, value, day=D1, quote=None):
    with tenant_context(company.id):
        return ExchangeRate.objects.create(
            company=company,
            currency=cur(company, code),
            quote_currency=cur(company, quote) if quote else None,
            date=day,
            rate=D(str(value)),
        )


def settings_of(company):
    return CompanyFinancialSettings.all_objects.get(company=company)


def set_base(company, code):
    CompanyFinancialSettings.all_objects.filter(company=company).update(
        base_currency=cur(company, code)
    )


def r(company, a, b, day=D3):
    return resolve_rate(company, cur(company, a), cur(company, b), day)


def raises_code(code, fn, status=None):
    with pytest.raises(FinanceError) as exc:
        fn()
    assert exc.value.detail.code == code, exc.value.detail
    if status:
        assert exc.value.status_code == status
    return exc.value


# --- resolve_rate ---


def test_same_currency(company):
    assert r(company, "USD", "USD") == (D("1"), "same", D3)
    assert r(company, "KZT", "KZT") == (D("1"), "same", D3)


def test_direct_pair_latest_not_after_date(company):
    rate(company, "USD", "0.9", D1, quote="EUR")
    rate(company, "USD", "0.95", D2, quote="EUR")
    rate(company, "USD", "0.99", D3, quote="EUR")
    assert r(company, "USD", "EUR", D2) == (D("0.95"), "direct", D2)
    assert r(company, "USD", "EUR", date(2026, 6, 15)) == (D("0.95"), "direct", D2)
    assert r(company, "USD", "EUR", D3)[0] == D("0.99")
    raises_code("rate_missing", lambda: r(company, "USD", "EUR", date(2026, 5, 31)), 409)


def test_inverse_pair_is_reciprocal(company):
    rate(company, "EUR", "0.8", D1, quote="USD")
    got = r(company, "USD", "EUR", D2)
    assert got == (D("1.250000"), "direct", D1)
    # более свежая обратная запись предпочтительнее старой прямой
    rate(company, "USD", "1.1", date(2026, 5, 1), quote="EUR")
    assert r(company, "USD", "EUR", D2)[0] == D("1.250000")
    # при равных датах - прямая
    rate(company, "USD", "1.2", D1, quote="EUR")
    assert r(company, "USD", "EUR", D2) == (D("1.2"), "direct", D1)


def test_via_kzt_triangulation(company):
    rate(company, "USD", "480", D1)
    rate(company, "RUB", "5", D2)
    got = r(company, "USD", "RUB", D3)
    assert got == (D("96.000000"), "via_kzt", D1)  # дата - более ранняя из ног
    inv = r(company, "RUB", "USD", D3)
    assert inv[0] == quantize_rate(D("5") / D("480")) == D("0.010417") and inv[1] == "via_kzt"


def test_via_kzt_with_kzt_side(company):
    rate(company, "USD", "480", D1)
    assert r(company, "USD", "KZT", D2) == (D("480.000000"), "via_kzt", D1)
    assert r(company, "KZT", "USD", D2) == (D("0.002083"), "via_kzt", D1)


def test_latest_leg_per_date(company):
    rate(company, "USD", "470", D1)
    rate(company, "USD", "480", D2)
    rate(company, "RUB", "5", D1)
    assert r(company, "USD", "RUB", D1)[0] == D("94")
    assert r(company, "USD", "RUB", D3)[0] == D("96")


def test_missing_rate_names_currency_and_date(company):
    rate(company, "USD", "480", D1)
    exc = raises_code("rate_missing", lambda: r(company, "USD", "RUB", D3), 409)
    assert "USD" in str(exc.detail) and "RUB" in str(exc.detail) and "2026-06-20" in str(exc.detail)
    raises_code("rate_missing", lambda: r(company, "EUR", "RUB", D3))
    raises_code("rate_missing", lambda: r(company, "USD", "KZT", date(2026, 5, 1)))  # до первой


def test_rate_rounded_half_up_to_six_places(company):
    rate(company, "USD", "2", D1)
    rate(company, "RUB", "3", D1)
    assert r(company, "USD", "RUB", D2)[0] == D("0.666667")
    assert r(company, "RUB", "USD", D2)[0] == D("1.500000")
    assert quantize_rate(D("0.0000005")) == D("0.000001")
    assert quantize_rate(D("0.0000004")) == D("0.000000")
    rate(company, "EUR", "3", D1, quote="USD")
    assert r(company, "USD", "EUR", D2)[0] == D("0.333333")


def test_other_company_rates_not_used(company, make_company):
    other, _, _ = make_company("Other")
    rate(other, "USD", "480", D1)
    rate(other, "USD", "0.9", D1, quote="EUR")
    raises_code("rate_missing", lambda: r(company, "USD", "KZT", D2))
    raises_code("rate_missing", lambda: r(company, "USD", "EUR", D2))
    assert r(other, "USD", "KZT", D2)[0] == D("480")


# --- снимок ---


def test_snapshot_values_and_cents(company):
    rate(company, "USD", "481.555", D1)
    snap = fx_snapshot(company, D("10.01"), cur(company, "USD"), D2)
    assert snap["fx_base_currency"] == cur(company, "KZT")
    assert snap["fx_rate"] == D("481.555000") and snap["fx_rate_source"] == "via_kzt"
    assert snap["fx_rate_date"] == D1
    assert snap["base_amount"] == D("4820.37")  # 10.01*481.555 = 4820.36555 -> half up
    same = fx_snapshot(company, D("123.45"), cur(company, "KZT"), D2)
    assert same["fx_rate_source"] == "same" and same["base_amount"] == D("123.45")


def test_snapshot_uses_company_base_currency(company):
    rate(company, "USD", "480", D1)
    rate(company, "RUB", "5", D1)
    set_base(company, "RUB")
    snap = fx_snapshot(company, D("2"), cur(company, "USD"), D2)
    assert snap["fx_base_currency"] == cur(company, "RUB")
    assert snap["fx_rate"] == D("96") and snap["base_amount"] == D("192.00")


def test_snapshot_errors(company):
    CompanyFinancialSettings.all_objects.filter(company=company).update(base_currency=None)
    raises_code(
        "base_currency_missing",
        lambda: fx_snapshot(company, 1, cur(company, "USD"), D1),
        409,
    )
    set_base(company, "KZT")
    raises_code("rate_missing", lambda: fx_snapshot(company, 1, cur(company, "USD"), D1))


def test_apply_snapshot_and_legacy_missing(company):
    rate(company, "USD", "480", D1)
    order = make_order(company)
    with tenant_context(company.id):
        income = Income(
            company=company, order=order, kind="service", title="x", amount=D("3.00"),
            currency=cur(company, "USD"),
        )  # fmt: skip
        apply_snapshot(income, D2)
        income.save()
        income.refresh_from_db()
        assert (income.fx_rate, income.fx_rate_source, income.base_amount) == (
            D("480.000000"), "via_kzt", D("1440.00"),
        )  # fmt: skip
        legacy = legacy_missing_snapshot(company, cur(company, "USD"))
        exp = Expense(
            company=company, kind="other", title="y", amount=D("5"),
            category=HandbookValue.objects.get(handbook__code="expense_category", code="OTHER"),
            currency=cur(company, "USD"), expense_date=D1, source="migrated", **legacy,
        )  # fmt: skip
        exp.save()  # CHECK legacy_missing => base_amount NULL проходит
        assert exp.fx_rate_source == "legacy_missing" and exp.base_amount is None
        assert exp.fx_rate is None and exp.amount == D("5.00")


def test_historical_snapshots_unchanged_by_rate_changes(company):
    r1 = rate(company, "USD", "480", D1)
    order = make_order(company)
    with tenant_context(company.id):
        inc = Income(
            company=company, order=order, kind="service", title="x", amount=D("10"),
            currency=cur(company, "USD"),
        )  # fmt: skip
        apply_snapshot(inc, D2)
        inc.save()
        exp = Expense(
            company=company, kind="other", title="y", amount=D("7.77"),
            category=HandbookValue.objects.get(handbook__code="expense_category", code="OTHER"),
            currency=cur(company, "USD"), expense_date=D2, source="manual",
        )  # fmt: skip
        apply_snapshot(exp, D2)
        exp.save()

    def state():
        f = ("fx_base_currency_id", "fx_rate", "fx_rate_date", "fx_rate_source", "base_amount")
        return (
            list(Income.all_objects.values_list(*f)),
            list(Expense.all_objects.values_list(*f)),
        )

    before = state()
    assert before[0][0][4] == D("4800.00")
    with tenant_context(company.id):
        ExchangeRate.objects.filter(pk=r1.pk).update(rate=D("999"))  # изменение
        rate(company, "USD", "600", D2)  # добавление
        ExchangeRate.objects.filter(pk=r1.pk).delete()  # удаление
        ExchangeRate.objects.all().delete()
    assert state() == before


# --- смена базовой валюты ---


def audit_rows(company):
    with tenant_context(company.id):
        return list(AuditLog.objects.filter(object_type="finance.companyfinancialsettings"))


def test_change_base_currency_success(company):
    user = first_user(company)
    make_order(company, currency="USD")
    rate(company, "USD", "480", date(2026, 1, 1))
    rate(company, "RUB", "5", date(2026, 1, 1))
    old_id = settings_of(company).base_currency_id
    got = change_base_currency(company, cur(company, "RUB"), user, "Переход на рубли")
    assert got.base_currency_id == cur(company, "RUB").pk and got.updated_by_id == user.pk
    assert settings_of(company).base_currency.code == "RUB"
    rows = audit_rows(company)
    assert len(rows) == 1 and rows[0].action == "update" and rows[0].user_id == user.pk
    assert rows[0].changes == {
        "base_currency_id": [old_id, cur(company, "RUB").pk],
        "reason": "Переход на рубли",
    }
    # повтор той же валюты - без изменений и без новой записи аудита
    change_base_currency(company, cur(company, "RUB"), user, "ещё раз")
    assert len(audit_rows(company)) == 1


def test_change_base_currency_does_not_recalculate_history(company):
    user = first_user(company)
    rate(company, "USD", "480", date(2026, 1, 1))
    rate(company, "RUB", "5", date(2026, 1, 1))
    order = make_order(company)
    with tenant_context(company.id):
        inc = Income(
            company=company, order=order, kind="service", title="x", amount=D("10"),
            currency=cur(company, "USD"),
        )  # fmt: skip
        apply_snapshot(inc, D1)
        inc.save()
    change_base_currency(company, cur(company, "RUB"), user, "смена")
    inc.refresh_from_db()
    assert inc.fx_base_currency_id == cur(company, "KZT").pk and inc.base_amount == D("4800.00")


def test_change_base_currency_rate_missing_lists_pairs_and_changes_nothing(company):
    user = first_user(company)
    make_order(company, currency="USD")
    make_order(company, currency="EUR")
    rate(company, "USD", "480", date(2026, 1, 1))  # RUB-ноги нет, EUR-ноги нет
    before = settings_of(company).base_currency_id
    exc = raises_code(
        "rate_missing", lambda: change_base_currency(company, cur(company, "RUB"), user, "x"), 409
    )
    text = str(exc.detail)
    assert "USD->RUB" in text and "EUR->RUB" in text
    assert settings_of(company).base_currency_id == before and audit_rows(company) == []


def test_change_base_currency_validation(company):
    user = first_user(company)
    with tenant_context(company.id):
        cny = HandbookValue.objects.create(
            handbook=cur(company).handbook, name="Юань", code="CNY", order=9
        )
    raises_code("base_currency_invalid", lambda: change_base_currency(company, cny, user, "x"))
    raises_code(
        "base_currency_invalid",
        lambda: change_base_currency(
            company, HandbookValue.all_objects.get(handbook__code="trip_status", code="COMPLETED",
                                                   company=company), user, "x"
        ),
    )  # fmt: skip
    for reason in ("", "   ", None):
        raises_code(
            "reason_required",
            lambda reason=reason: change_base_currency(company, cur(company, "USD"), user, reason),
        )
    assert audit_rows(company) == [] and settings_of(company).base_currency.code == "KZT"


def test_change_base_currency_foreign_company_value(company, make_company):
    other, _, _ = make_company("Other")
    raises_code(
        "base_currency_invalid",
        lambda: change_base_currency(company, cur(other, "USD"), first_user(company), "x"),
    )


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_change_base_currency_is_consistent(company):
    user = first_user(company)
    for code, value in (("USD", 480), ("RUB", 5), ("EUR", 510)):
        rate(company, code, value, date(2026, 1, 1))
    start = settings_of(company).base_currency_id
    targets = ["USD", "RUB", "EUR", "USD", "RUB", "EUR"]
    errors = []
    barrier = threading.Barrier(len(targets))

    def work(code):
        try:
            barrier.wait()
            change_base_currency(company, cur(company, code), user, f"в {code}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=work, args=(c,)) for c in targets]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    rows = sorted(audit_rows(company), key=lambda a: a.id)
    # цепочка «было -> стало» непрерывна: нет потерянных обновлений и дублей перехода
    chain = [start]
    for row in rows:
        old, new = row.changes["base_currency_id"]
        assert old == chain[-1] and old != new
        chain.append(new)
    assert settings_of(company).base_currency_id == chain[-1]
    assert CompanyFinancialSettings.all_objects.filter(company=company).count() == 1
