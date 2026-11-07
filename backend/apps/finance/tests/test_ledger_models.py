"""Ограничения и допустимые случаи новых моделей финансовой архитектуры (подзадача 1.4.1)."""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.core.handbooks.models import HandbookValue
from apps.core.handbooks.system_codes import SystemValueProtected, system_values_maintenance
from apps.core.rls import tables_missing_rls, tenant_tables
from apps.core.tenancy import set_current_company, tenant_context
from apps.finance.models import (
    CompanyFinancialSettings,
    ExchangeRate,
    Expense,
    ExpenseAllocation,
    ExpenseInvoiceAllocation,
    FinanceMigrationIssue,
    FinanceMigrationRun,
    FinancialPeriod,
    FinancialPeriodEvent,
    Income,
    IncomeTrip,
    InvoiceItem,
)
from apps.finance.tests.helpers import (
    add_line,
    cur,
    issue_invoice,
    make_carrier,
    make_order,
)
from apps.forwarding.models import Trip

pytestmark = pytest.mark.django_db

NEW_TABLES = {
    "finance_companyfinancialsettings",
    "finance_financialperiod",
    "finance_financialperiodevent",
    "finance_income",
    "finance_incometrip",
    "finance_expense",
    "finance_expenseallocation",
    "finance_expenseinvoiceallocation",
    "finance_financemigrationrun",
    "finance_financemigrationissue",
}


def violates(fn):
    """Операция должна нарушить ограничение БД (в своей точке сохранения)."""
    with pytest.raises(IntegrityError), transaction.atomic():
        fn()


def hv(company, handbook, code):
    with tenant_context(company.id):
        return HandbookValue.objects.get(handbook__code=handbook, code=code)


def make_trip(company, number="T-1", carrier=None, status_code="PLANNED"):
    with tenant_context(company.id):
        return Trip.objects.create(
            number=number,
            carrier=carrier,
            currency=cur(company),
            status=hv(company, "trip_status", status_code),
        )


def make_income(company, order, **extra):
    data = {
        "order": order,
        "kind": "freight",
        "title": "Перевозка",
        "amount": Decimal("1000.00"),
        "currency": cur(company),
    }
    data.update(extra)
    with tenant_context(company.id):
        return Income.objects.create(**data)


def make_expense(company, **extra):
    data = {
        "kind": "other",
        "title": "Расход",
        "category": hv(company, "expense_category", "OTHER"),
        "amount": Decimal("500.00"),
        "currency": cur(company),
        "expense_date": date(2026, 6, 1),
        "source": "manual",
    }
    data.update(extra)
    with tenant_context(company.id):
        return Expense.objects.create(**data)


# --- RLS-покрытие ---


def test_all_new_tables_are_tenant_tables_with_rls():
    assert NEW_TABLES <= set(tenant_tables())
    assert tables_missing_rls() == []


# --- CompanyFinancialSettings ---


def settings_of(company):
    return CompanyFinancialSettings.all_objects.get(company=company)


def test_settings_row_exists_for_new_company_and_is_unique(company):
    row = settings_of(company)
    assert row.engine == "legacy" and row.accounting_method == "ACCRUAL"
    violates(lambda: CompanyFinancialSettings.all_objects.create(company=company))


def test_settings_month_check(company):
    row = settings_of(company)
    for bad in (0, 13):
        row.fiscal_year_start_month = bad
        violates(lambda: row.save())
    row.fiscal_year_start_month = 12
    row.save()
    row.fiscal_year_start_month = 1
    row.save()


def test_settings_engine_new_requires_cutover_and_completed_status(company):
    row = settings_of(company)
    done = hv(company, "trip_status", "COMPLETED")
    with tenant_context(company.id):
        row.engine = "new"
        row.completed_status = None
        row.cutover_date = None
        violates(lambda: row.save())
        row.cutover_date = date(2026, 7, 1)
        violates(lambda: row.save())  # нет completed_status
        row.cutover_date = None
        row.completed_status = done
        violates(lambda: row.save())  # нет cutover
        row.cutover_date = date(2026, 7, 1)
        row.save()  # допустимо
        row.engine = "shadow"
        row.save()
        row.engine = "bogus"
        violates(lambda: row.save())


def test_settings_engine_shadow_and_legacy_do_not_need_cutover(company):
    row = settings_of(company)
    row.completed_status = None
    for engine in ("legacy", "shadow"):
        row.engine = engine
        row.save()


@pytest.fixture
def in_tenant(company):
    with tenant_context(company.id):
        yield


def test_settings_clean_validates_currency_and_status(company, make_company, in_tenant):
    other, _, _ = make_company("Other")
    set_current_company(company.id)  # фабрика компании сбрасывает контекст
    row = settings_of(company)
    row.base_currency = cur(company, "RUB")
    row.full_clean()  # допустимо
    # справочник валют, но не из допустимых четырёх
    with tenant_context(company.id):
        extra = HandbookValue.objects.create(
            handbook=cur(company).handbook, name="Юань", code="CNY", order=9
        )
    row.base_currency = extra
    with pytest.raises(ValidationError) as exc:
        row.full_clean()
    assert "base_currency" in exc.value.message_dict
    # значение чужого справочника / чужой компании
    row.base_currency = hv(company, "trip_status", "COMPLETED")
    with pytest.raises(ValidationError) as exc:
        row.full_clean()
    assert "base_currency" in exc.value.message_dict
    row.base_currency = cur(other)
    with pytest.raises(ValidationError) as exc:
        row.full_clean()
    assert "base_currency" in exc.value.message_dict
    row.base_currency = cur(company)
    row.completed_status = hv(company, "vat_rate", "12")
    with pytest.raises(ValidationError) as exc:
        row.full_clean()
    assert "completed_status" in exc.value.message_dict
    row.completed_status = hv(other, "trip_status", "COMPLETED")
    with pytest.raises(ValidationError) as exc:
        row.full_clean()
    assert "completed_status" in exc.value.message_dict
    row.completed_status = hv(company, "trip_status", "COMPLETED")
    row.default_vat_rate = hv(company, "currency", "KZT")
    with pytest.raises(ValidationError) as exc:
        row.full_clean()
    assert "default_vat_rate" in exc.value.message_dict
    row.default_vat_rate = hv(company, "vat_rate", "12")
    row.full_clean()


def test_settings_clean_engine_new_needs_fields(company, in_tenant):
    row = settings_of(company)
    row.engine = "new"
    row.completed_status = None
    with pytest.raises(ValidationError) as exc:
        row.full_clean()
    assert {"cutover_date", "completed_status"} <= set(exc.value.message_dict)


# --- FinancialPeriod / FinancialPeriodEvent ---


def make_period(company, year=2026, month=5, **extra):
    with tenant_context(company.id):
        return FinancialPeriod.objects.create(year=year, month=month, **extra)


def test_period_unique_per_company_and_month_range(company, make_company):
    other, _, _ = make_company("Other")
    make_period(company)
    violates(lambda: make_period(company))
    make_period(company, month=6)
    make_period(other)  # другая компания - тот же месяц допустим
    for bad in (0, 13):
        violates(lambda bad=bad: make_period(company, year=2025, month=bad))
    violates(lambda: make_period(company, year=2025, month=1, status="weird"))


def test_period_event_reopen_requires_reason(company):
    period = make_period(company)

    def event(action, reason=""):
        with tenant_context(company.id):
            return FinancialPeriodEvent.objects.create(period=period, action=action, reason=reason)

    event("close")  # причина для закрытия не нужна
    violates(lambda: event("reopen", ""))
    event("reopen", "Ошибка в проводке")
    violates(lambda: event("delete"))
    with tenant_context(company.id):
        assert period.events.count() == 2


# --- Income ---


def test_income_amount_nonnegative_and_recognized_needs_date(company):
    order = make_order(company)
    make_income(company, order, kind="service", amount=Decimal("0"))  # 0 допустим
    violates(lambda: make_income(company, order, kind="service", amount=Decimal("-0.01")))
    violates(lambda: make_income(company, order, kind="service", status="recognized"))
    ok = make_income(
        company, order, kind="service", status="recognized", recognized_on=date(2026, 6, 1)
    )
    assert ok.status == "recognized"


def test_income_one_active_freight_per_order(company):
    order = make_order(company)
    first = make_income(company, order)
    violates(lambda: make_income(company, order))  # второй неаннулированный freight
    violates(
        lambda: make_income(company, order, status="recognized", recognized_on=date(2026, 6, 1))
    )
    # услуги не ограничены
    make_income(company, order, kind="service")
    make_income(company, order, kind="service")
    # другой заказ допустим
    make_income(company, make_order(company))
    # после аннулирования можно создать новый; аннулированных может быть несколько
    first.status = "void"
    first.save()
    second = make_income(company, order)
    second.status = "void"
    second.save()
    make_income(company, order)
    make_income(company, order, status="void")


def test_income_legacy_missing_has_no_base_amount(company):
    order = make_order(company)
    violates(
        lambda: make_income(
            company,
            order,
            kind="service",
            fx_rate_source="legacy_missing",
            base_amount=Decimal("10.00"),
        )
    )
    make_income(company, order, kind="service", fx_rate_source="legacy_missing", base_amount=None)
    make_income(
        company,
        order,
        kind="service",
        fx_rate_source="direct",
        fx_base_currency=cur(company),
        fx_rate=Decimal("1.234567"),
        fx_rate_date=date(2026, 6, 1),
        base_amount=Decimal("12.34"),
    )


def test_income_legacy_line_one_to_one(company):
    order = make_order(company)
    line = add_line(company, order, income=100)
    make_income(company, order, kind="service", legacy_line=line)
    violates(lambda: make_income(company, order, kind="service", legacy_line=line))


def test_income_trip_unique_pair(company):
    order = make_order(company)
    income = make_income(company, order)
    trip = make_trip(company)

    def link(t):
        with tenant_context(company.id):
            return IncomeTrip.objects.create(income=income, trip=t)

    link(trip)
    violates(lambda: link(trip))
    link(make_trip(company, "T-2"))


def test_income_fk_protect(company):
    from django.db.models import ProtectedError

    order = make_order(company)
    income = make_income(company, order)
    with pytest.raises(ProtectedError), transaction.atomic(), tenant_context(company.id):
        order.hard_delete() if hasattr(order, "hard_delete") else order.delete()
    assert Income.all_objects.filter(pk=income.pk).exists()


# --- Expense ---


def test_expense_amount_nonnegative(company):
    make_expense(company, amount=Decimal("0"))
    violates(lambda: make_expense(company, amount=Decimal("-1")))


def test_carrier_transport_requires_trip_and_carrier(company):
    carrier = make_carrier(company)
    trip = make_trip(company, carrier=carrier)
    kwargs = {"kind": "carrier_transport", "source": "carrier_price_sync"}
    violates(lambda: make_expense(company, **kwargs))
    violates(lambda: make_expense(company, trip=trip, **kwargs))
    violates(lambda: make_expense(company, carrier=carrier, **kwargs))
    ok = make_expense(company, trip=trip, carrier=carrier, **kwargs)
    assert ok.kind == "carrier_transport"
    # прочий расход - без рейса и перевозчика
    make_expense(company)


def test_one_active_carrier_transport_per_trip(company):
    carrier = make_carrier(company)
    trip = make_trip(company, carrier=carrier)
    kwargs = {
        "kind": "carrier_transport",
        "source": "carrier_price_sync",
        "trip": trip,
        "carrier": carrier,
    }
    first = make_expense(company, **kwargs)
    violates(lambda: make_expense(company, **kwargs))
    # прочий расход на тот же рейс допустим
    make_expense(company, trip=trip)
    # аннулированный не мешает, после аннулирования можно создать новый
    first.status = "void"
    first.save()
    make_expense(company, **kwargs)
    make_expense(company, status="void", **kwargs)
    make_expense(company, status="void", **kwargs)


def test_legacy_group_key_unique_per_company(company, make_company):
    other, _, _ = make_company("Other")
    make_expense(company, legacy_group_key="g1", source="migrated")
    violates(lambda: make_expense(company, legacy_group_key="g1", source="migrated"))
    make_expense(company, legacy_group_key="g2", source="migrated")
    make_expense(company)  # пустые ключи не конфликтуют
    make_expense(company)
    make_expense(other, legacy_group_key="g1", source="migrated")  # другая компания


def test_expense_legacy_missing_has_no_base_amount(company):
    violates(
        lambda: make_expense(company, fx_rate_source="legacy_missing", base_amount=Decimal("1.00"))
    )
    make_expense(company, fx_rate_source="legacy_missing")


def test_expense_category_is_required_and_protected(company):
    with pytest.raises(IntegrityError), transaction.atomic(), tenant_context(company.id):
        Expense.objects.create(
            kind="other",
            title="x",
            amount=1,
            currency=cur(company),
            expense_date=date(2026, 6, 1),
            source="manual",
        )
    expense = make_expense(company)
    from django.db.models import ProtectedError

    # системное значение защищено ещё до PROTECT: удалить его через API/queryset нельзя
    with pytest.raises(SystemValueProtected):
        HandbookValue.all_objects.filter(pk=expense.category_id).delete()
    with pytest.raises(ProtectedError), transaction.atomic(), system_values_maintenance():
        HandbookValue.all_objects.filter(pk=expense.category_id).delete()


# --- ExpenseAllocation ---


def make_alloc(company, expense, **extra):
    data = {"expense": expense, "amount": Decimal("100.00")}
    data.update(extra)
    with tenant_context(company.id):
        return ExpenseAllocation.objects.create(**data)


def test_allocation_amount_positive_and_has_target(company):
    expense = make_expense(company)
    order = make_order(company)
    trip = make_trip(company)
    violates(lambda: make_alloc(company, expense, order=order, amount=Decimal("0")))
    violates(lambda: make_alloc(company, expense, order=order, amount=Decimal("-1")))
    violates(lambda: make_alloc(company, expense))  # ни заказа, ни рейса
    make_alloc(company, expense, order=order)
    make_alloc(company, expense, trip=trip)
    make_alloc(company, expense, order=order, trip=trip)


def test_allocation_legacy_line_one_to_one(company):
    expense = make_expense(company)
    order = make_order(company)
    line = add_line(company, order, expense=10)
    make_alloc(company, expense, order=order, legacy_line=line)
    violates(lambda: make_alloc(company, expense, order=order, legacy_line=line))


# --- ExpenseInvoiceAllocation ---


def test_invoice_allocation_constraints_and_income_link(company):
    carrier = make_carrier(company)
    order = make_order(company)
    invoice = issue_invoice(company, order=order, direction="in", carrier=carrier, amount="400")
    with tenant_context(company.id):
        item = InvoiceItem.objects.filter(invoice=invoice).first()
    expense = make_expense(company)

    def link(amount="100.00", **extra):
        with tenant_context(company.id):
            return ExpenseInvoiceAllocation.objects.create(
                expense=expense, invoice_item=item, amount=Decimal(amount), **extra
            )

    violates(lambda: link("0"))
    violates(lambda: link("-5"))
    first = link()
    assert first.released_at is None
    violates(lambda: link())  # пара (расход, позиция) уникальна
    # InvoiceItem.income: nullable FK -> Income, related_name invoice_items
    income = make_income(company, order, kind="service")
    with tenant_context(company.id):
        item.income = income
        item.save()
    with tenant_context(company.id):
        assert list(income.invoice_items.all()) == [item]
    from django.db.models import ProtectedError

    with pytest.raises(ProtectedError), transaction.atomic():
        Income.all_objects.filter(pk=income.pk).delete()


# --- ExchangeRate ---


def make_rate(company, code, quote=None, day=date(2026, 6, 1), rate="2.5", **extra):
    with tenant_context(company.id):
        return ExchangeRate.objects.create(
            company=company,
            currency=cur(company, code),
            quote_currency=cur(company, quote) if quote else None,
            date=day,
            rate=Decimal(rate),
            **extra,
        )


def test_exchange_rate_uniqueness_split(company, make_company):
    other, _, _ = make_company("Other")
    make_rate(company, "USD")
    violates(lambda: make_rate(company, "USD"))  # дубль курса к тенге
    make_rate(company, "USD", day=date(2026, 6, 2))
    make_rate(other, "USD")
    # пары: своя уникальность, не конфликтует с курсом к тенге
    make_rate(company, "USD", "EUR")
    violates(lambda: make_rate(company, "USD", "EUR"))
    make_rate(company, "EUR", "USD")  # обратная пара - отдельная запись
    make_rate(company, "USD", "RUB")
    make_rate(company, "USD", "EUR", day=date(2026, 6, 2))
    # валюта не может котироваться сама к себе
    violates(lambda: make_rate(company, "USD", "USD", day=date(2026, 7, 1)))
    violates(lambda: make_rate(company, "RUB", day=date(2026, 7, 1), rate="0"))


def test_kzt_rates_api_ignores_pair_rows(admin_client, company):
    """Парные курсы не попадают в список и поиск курсов к тенге."""
    make_rate(company, "USD", day=date(2026, 6, 1), rate="500")
    make_rate(company, "EUR", "USD", day=date(2026, 6, 1), rate="1.1")
    got = admin_client.get("/api/finance/rates/")
    assert got.status_code == 200
    body = got.json()
    rows = body["results"] if isinstance(body, dict) else body
    assert [r["currency"]["code"] for r in rows] == ["USD"]


# --- журнал переноса ---


def test_migration_run_and_issue_structure(company):
    with tenant_context(company.id):
        run = FinanceMigrationRun.objects.create(kind="migrate", mode="dry_run")
        assert run.status == "running" and run.params == {} and run.summary == {}
        issue = FinanceMigrationIssue.objects.create(
            run=run, issue_type="ambiguous_expense", message="проверить", source_model="x"
        )
        orphan = FinanceMigrationIssue.objects.create(issue_type="shadow_error", message="m")
    assert issue.severity == "warning" and issue.status == "open" and orphan.run_id is None
    from django.db.models import ProtectedError

    with pytest.raises(ProtectedError), transaction.atomic():
        FinanceMigrationRun.all_objects.filter(pk=run.pk).delete()


def test_company_isolation_of_new_models(company, make_company):
    other, _, _ = make_company("Other")
    make_expense(company)
    with tenant_context(other.id):
        assert Expense.objects.count() == 0
        assert CompanyFinancialSettings.objects.count() == 1
