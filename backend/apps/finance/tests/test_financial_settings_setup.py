"""Начальные настройки компании (сигнал company_created, миграция 0007) и миграция 0006 (курсы)."""

import ast
import importlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.core.handbooks.models import HandbookValue
from apps.core.handbooks.system_codes import system_values_maintenance
from apps.core.models import User
from apps.core.services import create_company_with_defaults
from apps.core.tenancy import tenant_context
from apps.finance.initial_settings import ensure_company_financial_settings
from apps.finance.models import CompanyFinancialSettings, ExchangeRate, InvoiceItem
from apps.finance.tests.helpers import cur, issue_invoice, make_carrier, make_order

pytestmark = pytest.mark.django_db

M5 = importlib.import_module("apps.finance.migrations.0007_company_financial_settings_backfill")
M4 = importlib.import_module("apps.finance.migrations.0006_income_link_rate_quote_currency")
MIGRATIONS = Path(M5.__file__).parent


def historical_apps(name):
    return MigrationExecutor(connection).loader.project_state(("finance", name)).apps


def row(company):
    return CompanyFinancialSettings.all_objects.get(company=company)


def sql(query, params=()):
    with connection.cursor() as c:
        c.execute(query, params)


def code_of(company, handbook, name):
    with tenant_context(company.id):
        return HandbookValue.objects.get(handbook__code=handbook, name=name)


# --- новая компания: сигнал company_created ---


def test_new_company_gets_settings_with_compatible_defaults(company):
    s = row(company)
    assert s.engine == "legacy" and s.cutover_date is None
    assert s.accounting_method == "ACCRUAL" and s.fiscal_year_start_month == 1
    assert s.allow_backdating is True
    assert s.expense_creation_mode == "manual" and s.sync_carrier_price is True
    assert s.income_recognition == "all_trips_completed"
    assert s.default_vat_rate_id is None and s.updated_by_id is None
    assert s.base_currency_id == cur(company, "KZT").pk
    assert s.completed_status_id == code_of(company, "trip_status", "Завершён").pk
    assert s.completed_status.code == "COMPLETED"


def test_each_company_has_exactly_one_row(make_company):
    a, _, _ = make_company("A")
    b, _, _ = make_company("B")
    assert CompanyFinancialSettings.all_objects.filter(company=a).count() == 1
    assert CompanyFinancialSettings.all_objects.filter(company=b).count() == 1
    assert row(a).pk != row(b).pk and row(a).completed_status_id != row(b).completed_status_id


def test_company_creation_leaves_no_tenant_context():
    from apps.core.tenancy import get_current_company_id

    owner = User.objects.create_user(email="ctx@settings.kz", password="s3cret-pass-1")
    create_company_with_defaults("Ctx", owner, ["forwarding"])
    assert get_current_company_id() is None


def test_ensure_is_idempotent_and_does_not_overwrite(company):
    first = row(company)
    CompanyFinancialSettings.all_objects.filter(pk=first.pk).update(
        engine="shadow", allow_backdating=False
    )
    again = ensure_company_financial_settings(company)
    assert again.pk == first.pk
    fresh = row(company)
    assert fresh.engine == "shadow" and fresh.allow_backdating is False


def test_completed_status_not_assigned_when_code_missing(company):
    CompanyFinancialSettings.all_objects.filter(company=company).delete()
    sql(
        "UPDATE core_handbookvalue SET code='' WHERE company_id=%s AND code='COMPLETED'",
        [company.id],
    )
    ensure_company_financial_settings(company)
    s = row(company)
    assert s.completed_status_id is None and s.base_currency_id == cur(company, "KZT").pk


def test_completed_status_not_assigned_when_inactive(company):
    CompanyFinancialSettings.all_objects.filter(company=company).delete()
    sql(
        "UPDATE core_handbookvalue SET is_active=false WHERE company_id=%s AND code='COMPLETED'",
        [company.id],
    )
    ensure_company_financial_settings(company)
    assert row(company).completed_status_id is None


def test_base_currency_empty_without_kzt(company):
    CompanyFinancialSettings.all_objects.filter(company=company).delete()
    with tenant_context(company.id), system_values_maintenance():
        sql(
            "UPDATE core_handbookvalue SET code='' WHERE company_id=%s AND code='KZT'", [company.id]
        )
    ensure_company_financial_settings(company)
    assert row(company).base_currency_id is None


# --- миграция 0007 (существующие компании) ---


def run_m5():
    M5.run_backfill(historical_apps("0007_company_financial_settings_backfill"))


def test_m5_creates_rows_for_existing_companies(company, make_company):
    other, _, _ = make_company("Other")
    CompanyFinancialSettings.all_objects.all().delete()
    run_m5()
    for c in (company, other):
        s = row(c)
        assert (s.engine, s.allow_backdating, s.expense_creation_mode) == ("legacy", True, "manual")
        assert (s.sync_carrier_price, s.income_recognition) == (True, "all_trips_completed")
        assert (s.accounting_method, s.fiscal_year_start_month) == ("ACCRUAL", 1)
        assert s.cutover_date is None
        assert s.base_currency.code == "KZT" and s.completed_status.code == "COMPLETED"
        assert s.base_currency.company_id == c.id and s.completed_status.company_id == c.id


def test_m5_ambiguous_or_missing_completed_stays_null(company, make_company):
    no_code, _, _ = make_company("NoCode")
    renamed, _, _ = make_company("Renamed")
    inactive, _, _ = make_company("Inactive")
    no_kzt, _, _ = make_company("NoKzt")
    CompanyFinancialSettings.all_objects.all().delete()
    sql(
        "UPDATE core_handbookvalue SET code='' WHERE company_id=%s AND code='COMPLETED'",
        [no_code.id],
    )
    # старое состояние: «Завершён» переименован, кода нет, рядом дубль названия
    sql(
        "UPDATE core_handbookvalue SET code='', name='Выполнен' WHERE company_id=%s "
        "AND code='COMPLETED'",
        [renamed.id],
    )
    with tenant_context(renamed.id):
        hb = HandbookValue.objects.get(handbook__code="trip_status", name="Выгрузка").handbook
        HandbookValue.objects.create(handbook=hb, name="Выполнен", order=50, is_final=True)
    sql(
        "UPDATE core_handbookvalue SET is_active=false WHERE company_id=%s AND code='COMPLETED'",
        [inactive.id],
    )
    sql("UPDATE core_handbookvalue SET code='' WHERE company_id=%s AND code='KZT'", [no_kzt.id])
    run_m5()
    for c in (no_code, renamed, inactive):
        s = row(c)
        assert s.completed_status_id is None, c.name
        assert s.base_currency.code == "KZT"
        assert s.engine == "legacy"
    assert row(company).completed_status_id is not None
    assert row(no_kzt).base_currency_id is None
    assert row(no_kzt).completed_status.code == "COMPLETED"


def test_m5_is_idempotent_and_keeps_existing_rows(company, make_company):
    other, _, _ = make_company("Other")
    CompanyFinancialSettings.all_objects.filter(company=other).delete()
    CompanyFinancialSettings.all_objects.filter(company=company).update(
        engine="shadow", allow_backdating=False, fiscal_year_start_month=4
    )
    run_m5()
    run_m5()
    assert CompanyFinancialSettings.all_objects.count() == 2
    kept = row(company)
    assert (kept.engine, kept.allow_backdating, kept.fiscal_year_start_month) == (
        "shadow",
        False,
        4,
    )
    assert row(other).engine == "legacy"


def test_m5_leaves_gucs_clean(company):
    CompanyFinancialSettings.all_objects.all().delete()
    run_m5()
    with connection.cursor() as c:
        c.execute("SELECT current_setting('app.company_id', true)")
        assert c.fetchone()[0] in ("", None)


# --- миграция 0006: preflight курсов ---


def rate_row(pk, company_id=1, currency_id=10, code="USD", day=date(2026, 6, 1)):
    return {
        "id": pk,
        "company_id": company_id,
        "currency_id": currency_id,
        "currency_code": code,
        "date": day,
    }


def test_find_rate_conflicts_pure():
    assert M4.find_rate_conflicts([]) == []
    ok = [
        rate_row(1),
        rate_row(2, day=date(2026, 6, 2)),
        rate_row(3, currency_id=11, code="EUR"),
        rate_row(4, company_id=2),
    ]
    assert M4.find_rate_conflicts(ok) == []
    dup = M4.find_rate_conflicts([rate_row(1), rate_row(2)])
    assert len(dup) == 1 and "#1" in dup[0] and "#2" in dup[0] and "дубликат" in dup[0]
    kzt = M4.find_rate_conflicts([rate_row(5, currency_id=1, code="KZT")])
    assert len(kzt) == 1 and "KZT" in kzt[0]


def run_preflight():
    M4.preflight(
        historical_apps("0005_income_expense_ledger"), SimpleNamespace(connection=connection)
    )


def test_preflight_passes_on_clean_rates_and_changes_nothing(company):
    for day, rate in ((date(2026, 6, 1), "480.5"), (date(2026, 6, 2), "481.25")):
        with tenant_context(company.id):
            ExchangeRate.objects.create(
                company=company, currency=cur(company, "USD"), date=day, rate=Decimal(rate)
            )
    before = list(ExchangeRate.all_objects.order_by("id").values_list("id", "date", "rate"))
    run_preflight()
    assert list(ExchangeRate.all_objects.order_by("id").values_list("id", "date", "rate")) == before


def test_preflight_stops_with_list_and_deletes_nothing(company):
    with tenant_context(company.id):
        ExchangeRate.objects.create(
            company=company, currency=cur(company, "USD"), date=date(2026, 6, 1), rate=Decimal("1")
        )
        bad = ExchangeRate.objects.create(
            company=company, currency=cur(company, "KZT"), date=date(2026, 6, 1), rate=Decimal("1")
        )
    before = list(ExchangeRate.all_objects.order_by("id").values_list("id", "date", "rate"))
    with pytest.raises(RuntimeError) as exc:
        run_preflight()
    assert f"#{bad.pk}" in str(exc.value) and "остановлена" in str(exc.value)
    assert list(ExchangeRate.all_objects.order_by("id").values_list("id", "date", "rate")) == before
    with connection.cursor() as c:
        c.execute("SELECT current_setting('app.company_id', true)")
        assert c.fetchone()[0] in ("", None)  # контекст сброшен и при ошибке


def run_guard():
    M4.guard_reverse(
        historical_apps("0006_income_link_rate_quote_currency"),
        SimpleNamespace(connection=connection),
    )


def test_reverse_guard_blocks_when_pair_rates_or_income_links_exist(company):
    run_guard()  # данных нет - откат допустим
    with tenant_context(company.id):
        ExchangeRate.objects.create(
            company=company,
            currency=cur(company, "USD"),
            quote_currency=cur(company, "EUR"),
            date=date(2026, 6, 1),
            rate=Decimal("1.1"),
        )
    with pytest.raises(RuntimeError, match="курсов пар валют 1"):
        run_guard()
    ExchangeRate.all_objects.filter(quote_currency__isnull=False).delete()
    run_guard()
    # позиция счёта со ссылкой на доход
    from apps.finance.models import Income

    order = make_order(company)
    invoice = issue_invoice(
        company, order=order, direction="in", carrier=make_carrier(company), amount="100"
    )
    with tenant_context(company.id):
        income = Income.objects.create(
            order=order, kind="service", title="x", amount=1, currency=cur(company)
        )
        InvoiceItem.objects.filter(invoice=invoice).update(income=income)
    with pytest.raises(RuntimeError, match="ссылкой на доход 1"):
        run_guard()


# --- новые миграции самодостаточны ---


def test_new_finance_migrations_do_not_import_application_code():
    for path in sorted(MIGRATIONS.glob("000[4-7]_*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            for name in names:
                assert not name.startswith("apps"), (path.name, name)
