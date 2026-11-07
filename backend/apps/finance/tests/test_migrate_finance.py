"""migrate_finance (1.4.8): перенос OrderService в Income / Expense / доли / связи."""

from datetime import date
from decimal import Decimal as D
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db.models import Sum

from apps.core.tenancy import tenant_context
from apps.finance import invoices as inv_svc
from apps.finance import migration
from apps.finance.models import (
    CompanyFinancialSettings,
    Expense,
    ExpenseAllocation,
    ExpenseInvoiceAllocation,
    FinanceMigrationIssue,
    FinanceMigrationRun,
    Income,
    Invoice,
    InvoiceItem,
    Payment,
)
from apps.finance.tests.helpers import (
    add_line,
    cur,
    first_user,
    issue_invoice,
    make_order,
    pay_invoice,
    vat,
)
from apps.finance.tests.p2_helpers import new_trip, order_with_cargos, rate, set_engine
from apps.forwarding.finance_lines.models import OrderService
from apps.forwarding.models import Order, Trip

pytestmark = pytest.mark.django_db
D1, D2 = date(2026, 5, 10), date(2026, 6, 12)


def run_cmd(company, *args):
    out = StringIO()
    call_command("migrate_finance", "--company", str(company.id), *args, stdout=out)
    return out.getvalue()


def counts(company):
    with tenant_context(company.id):
        return {
            "income": Income.objects.count(),
            "expense": Expense.objects.count(),
            "alloc": ExpenseAllocation.objects.count(),
            "links": ExpenseInvoiceAllocation.objects.count(),
            "issues": FinanceMigrationIssue.objects.count(),
        }


def old_state(company):
    with tenant_context(company.id):
        return (
            list(
                OrderService.objects.order_by("pk").values_list(
                    "pk", "income", "expense", "title", "date"
                )
            ),
            list(
                Invoice.objects.order_by("pk").values_list(
                    "pk", "status", "total_gross", "rate_to_kzt"
                )
            ),
            list(
                InvoiceItem.objects.order_by("pk").values_list(
                    "pk", "line_id", "amount_net", "title"
                )
            ),
            list(Payment.objects.order_by("pk").values_list("pk", "amount", "rate_to_kzt")),
        )


def snapshot(company):
    with tenant_context(company.id):
        return (
            list(
                Income.objects.order_by("pk").values_list(
                    "pk",
                    "amount",
                    "status",
                    "legacy_line_id",
                    "base_amount",
                    "fx_rate_source",
                    "recognized_on",
                )
            ),
            list(
                Expense.objects.order_by("pk").values_list(
                    "pk",
                    "amount",
                    "status",
                    "legacy_group_key",
                    "needs_review",
                    "review_reason",
                    "base_amount",
                )
            ),
            list(
                ExpenseAllocation.objects.order_by("pk").values_list(
                    "pk", "amount", "legacy_line_id", "expense_id"
                )
            ),
            list(
                ExpenseInvoiceAllocation.objects.order_by("pk").values_list(
                    "pk", "amount", "expense_id", "invoice_item_id"
                )
            ),
            list(InvoiceItem.objects.order_by("pk").values_list("pk", "income_id")),
        )


def build(company):
    """Сценарная компания в engine=legacy. Возвращает словарь ключевых объектов."""
    rate(company, "USD", "480", date(2026, 6, 1))  # на 10 мая курса нет -> legacy_missing
    s = {}
    o1 = make_order(company)
    s["o1"] = o1
    with tenant_context(company.id):
        Order.all_objects.filter(pk=o1.pk).update(client_rate=D("1000"))
        from apps.forwarding.finance_lines.services import sync_base_line

        sync_base_line(Order.all_objects.get(pk=o1.pk))
        OrderService.objects.filter(order=o1, is_base=True).update(date=D1)
    s["svc"] = add_line(company, o1, income=200, title="Услуга", day=D1, category="Допуслуга")
    s["manual"] = add_line(company, o1, expense=50, title="Склад", day=D2, category="Прочее")
    s["both"] = add_line(company, o1, income=30, expense=20, title="Оба", day=D2)
    s["zero"] = add_line(company, o1, title="Пусто", day=D2)
    # сборный рейс из 3 заказов
    orders, ids = [], []
    for _ in range(3):
        o, cids = order_with_cargos(company, 1)
        orders.append(o)
        ids += cids
    trip = new_trip(company, ids, price="100.00")
    s["trip"], s["trip_orders"] = trip, sorted(orders, key=lambda o: o.pk)
    title = f"Перевозка {trip.number}"
    s["group"] = [
        add_line(company, o, expense=a, title=title, day=d, category="Перевозка")
        for o, a, d in zip(s["trip_orders"], ("33.34", "33.33", "33.33"), (D1, D2, D2))
    ]
    # спорные строки
    ox, _ = order_with_cargos(company, 1)
    s["no_trip"] = add_line(
        company, ox, expense=10, title="Перевозка X-999", day=D2, category="Перевозка"
    )
    on, idn = order_with_cargos(company, 1)
    trip_nc = new_trip(company, idn, price="5", carrier=False)
    s["no_carrier"] = add_line(
        company, on, expense=5, title=f"Перевозка {trip_nc.number}", day=D2, category="Перевозка"
    )
    ot, idt = order_with_cargos(company, 1)
    trip_ok = new_trip(company, idt, price="7")
    foreign, _ = order_with_cargos(company, 1)
    s["foreign"] = add_line(
        company,
        foreign,
        expense=7,
        title=f"Перевозка {trip_ok.number}",
        day=D2,
        category="Перевозка",
    )
    s["foreign_ok"] = add_line(
        company, ot, expense=7, title=f"Перевозка {trip_ok.number}", day=D2, category="Перевозка"
    )
    ou, idu = order_with_cargos(company, 1)
    trip_usd = new_trip(company, idu, price="9", currency="USD")
    s["currency"] = add_line(
        company, ou, expense=9, title=f"Перевозка {trip_usd.number}", day=D2, category="Перевозка"
    )
    # мультивалюта
    ousd = make_order(company, currency="USD")
    s["usd_missing"] = add_line(company, ousd, income=10, expense=4, title="USD до курса", day=D1)
    s["usd_ok"] = add_line(company, ousd, income=20, title="USD с курсом", day=D2)
    # счета
    s["out_inv"] = issue_invoice(company, order=o1, amount="300", day=D2)  # по новой строке
    carrier = trip.carrier
    with tenant_context(company.id):
        draft = inv_svc.create_draft(
            direction="in", party=carrier, order=s["trip_orders"][0], trip=trip,
            currency=cur(company), vat_rate=vat(company, "0"), due_date=None,
            user=first_user(company),
            items=[{"title": "Перевозка", "amount_net": D("33.34"), "line": s["group"][0]}],
        )  # fmt: skip
        s["in_inv"] = inv_svc.issue(draft, user=first_user(company), issue_date=D2)
    pay_invoice(company, s["out_inv"], "100", day=D2)
    cancelled = issue_invoice(company, order=o1, amount="40", day=D2)
    with tenant_context(company.id):
        inv_svc.cancel(cancelled, user=first_user(company))
    s["cancelled"] = cancelled
    return s


def disputed_lines(s):
    return {
        s["no_trip"].pk,
        s["no_carrier"].pk,
        s["foreign"].pk,
        s["foreign_ok"].pk,
        s["currency"].pk,
    }


def test_dry_run_writes_nothing_but_run(company):
    build(company)
    before, state = counts(company), old_state(company)
    out = run_cmd(company, "--dry-run")
    assert counts(company) == before and old_state(company) == state
    assert "[dry-run]" in out and "СПОРНО" in out and "Перевозка X-999" in out
    with tenant_context(company.id):
        run = FinanceMigrationRun.objects.get()
    assert run.kind == "migrate" and run.mode == "dry_run"
    assert run.summary["counters"]["income_created"] > 0 and run.summary["created"] == {}
    assert FinanceMigrationIssue.all_objects.count() == 0


def test_apply_creates_everything_and_second_run_changes_nothing(company):
    s = build(company)
    state = old_state(company)
    out = run_cmd(company)
    assert "needs_review" in out
    with tenant_context(company.id):
        run = FinanceMigrationRun.objects.get()
        assert run.mode == "apply" and run.status == "needs_review"
        # доходы: база, услуга, "Оба", 2 USD, строки счетов 300 и 40 (нулевая строка - нет)
        inc = {i.legacy_line_id: i for i in Income.objects.exclude(legacy_line=None)}
        assert len(inc) == 7
        base_line = OrderService.objects.get(order=s["o1"], is_base=True)
        assert inc[base_line.pk].kind == "freight" and inc[s["svc"].pk].kind == "service"
        assert (
            inc[base_line.pk].status == "recognized"
            and inc[base_line.pk].recognition_basis == "legacy_line_date"
        )
        assert inc[base_line.pk].recognized_on == D1 and inc[base_line.pk].fx_rate_source == "same"
        assert inc[s["usd_missing"].pk].fx_rate_source == "legacy_missing"
        assert inc[s["usd_missing"].pk].base_amount is None and inc[
            s["usd_missing"].pk
        ].amount == D("10.00")
        assert inc[s["usd_ok"].pk].fx_rate_source == "via_kzt" and inc[
            s["usd_ok"].pk
        ].base_amount == D("9600.00")
        # ручные расходы
        manual = Expense.objects.get(legacy_group_key=f"line:{s['manual'].pk}")
        assert (
            manual.kind == "other" and manual.source == "migrated" and manual.amount == D("50.00")
        )
        assert manual.category.code == "OTHER" and manual.requires_full_allocation is False
        both = Expense.objects.get(legacy_group_key=f"line:{s['both'].pk}")
        assert both.amount == D("20.00") and inc[s["both"].pk].amount == D("30.00")
        assert ExpenseAllocation.objects.get(legacy_line=s["both"]).expense_id == both.pk
        # расход перевозчика: один на группу, доли по строкам
        group = Expense.objects.get(kind="carrier_transport")
        assert group.legacy_group_key == f"trip:{s['trip'].pk}" and group.amount == D("100.00")
        assert group.carrier_id == s["trip"].carrier_id and group.expense_date == D1
        assert group.requires_full_allocation and group.needs_review is False
        assert ExpenseAllocation.objects.filter(expense=group).aggregate(t=Sum("amount"))["t"] == D(
            "100.00"
        )
        assert ExpenseAllocation.objects.filter(expense=group).count() == 3
        # спорные строки: не перенесены и не стали ручными
        migrated_lines = set(ExpenseAllocation.objects.values_list("legacy_line_id", flat=True))
        assert not disputed_lines(s) & migrated_lines
        issues = FinanceMigrationIssue.objects.filter(issue_type="ambiguous_trip_expense")
        assert {i.source_id for i in issues} == disputed_lines(s) and all(
            i.severity == "error" for i in issues
        )
        assert not Expense.objects.filter(
            legacy_group_key__in=[f"line:{x}" for x in disputed_lines(s)]
        ).exists()
        # связи со счетами
        out_item = InvoiceItem.objects.get(invoice=s["out_inv"])
        in_item = InvoiceItem.objects.get(invoice=s["in_inv"])
        assert out_item.income.legacy_line_id == out_item.line_id
        link = ExpenseInvoiceAllocation.objects.get(invoice_item=in_item)
        assert (
            link.expense_id == group.pk and link.amount == D("33.34") and link.released_at is None
        )
        assert InvoiceItem.objects.get(invoice=s["cancelled"]).income_id is None
    assert old_state(company) == state  # старые данные не изменены
    snap, cnt = snapshot(company), counts(company)
    out2 = run_cmd(company)
    assert snapshot(company) == snap and counts(company) == cnt  # повтор - ноль изменений
    with tenant_context(company.id):
        last = FinanceMigrationRun.objects.order_by("-id").first()
    c = last.summary["counters"]
    assert c.get("income_created", 0) == 0 and c.get("manual_expense_created", 0) == 0
    assert c.get("group_expense_created", 0) == 0 and c.get("links_created", 0) == 0
    assert c.get("issues_new", 0) == 0 and c["issues_existing"] == len(disputed_lines(s))
    assert "needs_review" in out2


def test_sums_match_source_by_currency_and_month(company):
    s = build(company)
    run_cmd(company)
    with tenant_context(company.id):
        run = FinanceMigrationRun.objects.get()
        disputed = disputed_lines(s)
        src_income, src_expense = {}, {}
        for line in OrderService.objects.select_related("order__currency"):
            key = (line.order.currency.code, f"{line.date:%Y-%m}")
            src_income[key] = src_income.get(key, D("0")) + line.income
            if line.pk not in disputed:
                src_expense[key] = src_expense.get(key, D("0")) + line.expense
    created = run.summary["created"]
    got_income, got_expense = {}, {}
    for ccy, months in created.items():
        for month, v in months.items():
            got_income[(ccy, month)] = D(v["income"])
            got_expense[(ccy, month)] = D(v["expense"])
    assert {k: v for k, v in src_income.items() if v} == {k: v for k, v in got_income.items() if v}
    assert {k: v for k, v in src_expense.items() if v} == {
        k: v for k, v in got_expense.items() if v
    }
    assert ("USD", "2026-05") in got_income  # legacy_missing не выпадает из сумм
    assert run.summary["source"]["USD"]["2026-05"]["income"] == "10.00"


def test_group_sum_differs_from_carrier_price_needs_review(company):
    s = build(company)
    with tenant_context(company.id):
        Trip.objects.filter(pk=s["trip"].pk).update(carrier_price=D("120.00"))
    run_cmd(company)
    with tenant_context(company.id):
        group = Expense.objects.get(kind="carrier_transport")
    assert group.amount == D("100.00") and group.carrier_price_snapshot == D("120.00")
    assert group.needs_review is True and group.review_reason == "migrated_mismatch"


def test_engine_new_refused_and_unknown_company(company):
    set_engine(company, "new", cutover_date=date(2026, 1, 1))
    with pytest.raises(CommandError, match="engine=new"):
        run_cmd(company)
    with pytest.raises(CommandError):
        call_command("migrate_finance", "--company", "999999")
    assert counts(company)["income"] == 0


def test_shadow_company_can_be_migrated(company):
    build(company)
    set_engine(company, "shadow")
    run_cmd(company)
    assert counts(company)["income"] == 7
    assert (
        CompanyFinancialSettings.all_objects.get(company=company).engine == "shadow"
    )  # engine не меняется


def test_resolve_issue_command_and_service(company):
    s = build(company)
    run_cmd(company)
    with tenant_context(company.id):
        issue = FinanceMigrationIssue.objects.filter(source_id=s["no_trip"].pk).get()
    with pytest.raises(CommandError):
        call_command("resolve_finance_issue", "--issue", str(issue.pk), "--note", "  ")
    with pytest.raises(CommandError):  # для спорной строки нужно решение
        call_command("resolve_finance_issue", "--issue", str(issue.pk), "--note", "Проверено")
    with pytest.raises(CommandError):  # слишком короткое обоснование
        call_command(
            "resolve_finance_issue", "--issue", str(issue.pk), "--note", "ок",
            "--resolution", "justified_exclusion",
        )  # fmt: skip
    call_command(
        "resolve_finance_issue",
        "--issue",
        str(issue.pk),
        "--note",
        "Рейс удалён, расход списан",
        "--resolution",
        "justified_exclusion",
        stdout=StringIO(),
    )
    issue = FinanceMigrationIssue.all_objects.get(pk=issue.pk)
    assert issue.status == "resolved" and issue.resolution_note == "Рейс удалён, расход списан"
    assert issue.resolution == "justified_exclusion" and issue.resolved_at is not None
    with pytest.raises(CommandError):
        call_command("resolve_finance_issue", "--issue", "999999", "--note", "x")
    # решение сохранено: повторный перенос НЕ открывает проблему заново и не создаёт дубль
    run_cmd(company)
    with tenant_context(company.id):
        assert FinanceMigrationIssue.objects.filter(source_id=s["no_trip"].pk).count() == 1
        assert not FinanceMigrationIssue.objects.filter(
            source_id=s["no_trip"].pk, status="open"
        ).exists()


def test_isolation_between_companies(company, make_company):
    other, _, _ = make_company("Other")
    build(company)
    o = make_order(other)
    add_line(other, o, income=70, title="Своя", day=D1)
    before_other = counts(other)
    run_cmd(company)
    assert counts(other) == before_other  # чужая компания не затронута
    run_cmd(other)
    with tenant_context(other.id):
        assert Income.objects.filter(legacy_line__isnull=False).count() == 1
        assert Income.objects.get(legacy_line__isnull=False).amount == D("70.00")
        assert not Income.objects.filter(
            order__in=Order.all_objects.filter(company=company)
        ).exists()
    with tenant_context(company.id):
        assert Income.objects.filter(legacy_line__isnull=False).count() == 7


def test_deleted_and_cancelled_orders_are_migrated_too(company):
    o = make_order(company)
    add_line(company, o, income=15, title="В корзину", day=D1)
    with tenant_context(company.id):
        o.delete()  # мягкое удаление
    run_cmd(company)
    with tenant_context(company.id):
        assert Income.objects.filter(order_id=o.pk, legacy_line__isnull=False).exists()


def test_order_without_changes_in_apply_is_noop_via_service(company):
    o = make_order(company)
    add_line(company, o, income=15, expense=5, title="X", day=D1)
    first = migration.migrate_order(Order.all_objects.get(pk=o.pk))
    assert first.counters["income_created"] == 1 and first.counters["manual_expense_created"] == 1
    snap = snapshot(company)
    again = migration.migrate_order(Order.all_objects.get(pk=o.pk))
    assert again.counters["income_created"] == 0 and again.counters["manual_expense_created"] == 0
    assert snapshot(company) == snap
    assert vat and cur
