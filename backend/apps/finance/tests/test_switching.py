# ruff: noqa: E501
"""Переключение engine, откат, заморозка, чтение из новой модели, защита OrderService (1.4.11)."""

from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal as D
from io import StringIO

import pytest
import time_machine
from django.core.management import CommandError, call_command

from apps.core.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.finance import (
    expenses,
    income,
    migration,
    periods,
    reconcile,
    switching,
)
from apps.finance import (
    invoices as inv_svc,
)
from apps.finance.engine import use_new_engine
from apps.finance.errors import FinanceError
from apps.finance.models import (
    CompanyFinancialSettings,
    Expense,
    FinanceMigrationIssue,
    FinanceMigrationRun,
    Income,
)
from apps.finance.tests.helpers import (
    add_line,
    cur,
    first_user,
    make_order,
    pay_invoice,
)
from apps.finance.tests.p2_helpers import move, new_trip, order_with_cargos, set_engine
from apps.finance.tests.test_migrate_finance import build, counts, run_cmd, snapshot
from apps.finance.tests.test_reconcile import simple
from apps.finance.tests.test_status_mapping import unmap
from apps.forwarding.finance_lines.models import OrderService

pytestmark = pytest.mark.django_db
REF = "Письмо заказчика №1 от 07.11.2026"
CUT = date(2026, 7, 1)
NOW = datetime(2026, 7, 15, 12, 0, tzinfo=dt_tz.utc)
LINES = "/api/order-lines/"


def settings_of(company):
    return CompanyFinancialSettings.all_objects.get(company=company)


def shadow_ready(company):
    """Согласованная компания в shadow (данные в мае-июне 2026), сверка успешна."""
    simple(company)
    set_engine(company, "shadow")
    return reconcile.reconcile(company.id)


def switch(company, *args, **kw):
    out = StringIO()
    call_command(
        "switch_finance_engine", "--company", str(company.id), "--to", "new", "--cutover", "2026-07-01",
        "--approval-ref", REF, *args, stdout=out, **kw,
    )  # fmt: skip
    return out.getvalue()


def refused(company, *args, target="new", **kw):
    with pytest.raises(CommandError) as exc:
        call_command(
            "switch_finance_engine", "--company", str(company.id), "--to", target, *args, **kw
        )
    return str(exc.value)


# --- gate ---------------------------------------------------------------------------------


def test_gate_refuses_every_condition_and_changes_nothing(company):
    simple(company)  # engine=legacy
    msg = refused(company)
    for code in ("engine_not_shadow", "cutover_missing", "approval_ref_missing"):
        assert code in msg
    assert settings_of(company).engine == "legacy"
    set_engine(company, "shadow")
    assert "approval_ref_missing" in refused(company, "--cutover", "2026-07-01")
    assert "cutover_missing" in refused(company, "--approval-ref", REF)
    # заморозка
    switching.set_frozen(company.id, True, reason="Остановка для проверки")
    assert "writes_frozen" in refused(company, "--cutover", "2026-07-01", "--approval-ref", REF)
    switching.set_frozen(company.id, False, reason="Снято")
    assert settings_of(company).engine == "shadow"


def test_gate_unmapped_statuses_and_completed_status(company):
    shadow_ready(company)
    unmap(company)
    msg = refused(company, "--cutover", "2026-07-01", "--approval-ref", REF)
    assert "unmapped_system_codes" in msg and "completed_status_missing" in msg
    assert settings_of(company).engine == "shadow"


def test_gate_reconcile_not_success_and_open_error_issue(company):
    shadow_ready(company)
    o = make_order(company)
    add_line(company, o, income=77, title="Не перенесена", day=date(2026, 6, 20))
    msg = refused(company, "--cutover", "2026-07-01", "--approval-ref", REF)
    assert "reconcile_not_success" in msg
    with tenant_context(company.id):
        assert FinanceMigrationRun.objects.filter(kind="reconcile").count() >= 1  # след остаётся


def test_gate_blocks_unreflected_amounts(company):
    s = build(company)
    run_cmd(company)
    set_engine(company, "shadow")
    with tenant_context(company.id):
        for issue in FinanceMigrationIssue.objects.filter(issue_type="ambiguous_trip_expense"):
            migration.resolve_issue(
                issue, None, "Обоснованное исключение по акту", "justified_exclusion"
            )
    msg = refused(company, "--cutover", "2026-07-01", "--approval-ref", REF)
    assert "not_reflected_amounts" in msg and "reconcile_not_success" in msg
    assert s


# --- успешное переключение --------------------------------------------------------------


def test_dry_run_then_switch(company):
    run = shadow_ready(company)
    assert run.status == "success"
    before = (snapshot(company), counts(company))
    with tenant_context(company.id):
        runs_before = FinanceMigrationRun.objects.count()
    out = switch(company, "--dry-run")
    assert "[dry-run]" in out and "before_cutover" in out
    assert settings_of(company).engine == "shadow"
    assert (snapshot(company), counts(company)) == before
    with tenant_context(company.id):
        assert (
            FinanceMigrationRun.objects.count() == runs_before
        )  # сверка пробного запуска откатана
    switch(company)
    row = settings_of(company)
    assert row.engine == "new" and row.cutover_date == CUT and row.engine_switched_at is not None
    assert snapshot(company) == before[0]  # данные до cutover не менялись
    assert use_new_engine(company) is True
    with tenant_context(company.id):
        entry = AuditLog.objects.filter(changes__approval_ref=REF).first()
        assert entry is not None and entry.changes["engine"] == ["shadow", "new"]
    assert "engine_not_shadow" in refused(company, "--cutover", "2026-07-01", "--approval-ref", REF)


def test_switch_to_shadow_from_legacy(company):
    simple(company)
    before = (snapshot(company), counts(company))
    with pytest.raises(CommandError):
        call_command("switch_finance_engine", "--company", str(company.id), "--to", "shadow")
    call_command(
        "switch_finance_engine", "--company", str(company.id), "--to", "shadow",
        "--approval-ref", REF, stdout=StringIO(),
    )  # fmt: skip
    assert settings_of(company).engine == "shadow"
    assert (snapshot(company), counts(company)) == before
    assert "engine_not_legacy" in refused(company, "--approval-ref", REF, target="shadow")


def cutover_orders(company):
    """Три заказа с базовым доходом 07-15 (после cutover 07-01): не завершён / завершён позже / завершён раньше."""
    set_engine(company, "shadow")
    out = {}
    with time_machine.travel(NOW, tick=False):
        for key in ("open", "later", "earlier"):
            o, ids = order_with_cargos(company, 1, client_rate=D("500"))
            out[key] = (o, new_trip(company, ids, price="0"))
    move(company, out["later"][1], "COMPLETED", when=datetime(2026, 7, 16, 12, 0, tzinfo=dt_tz.utc))
    move(
        company, out["earlier"][1], "COMPLETED", when=datetime(2026, 6, 20, 12, 0, tzinfo=dt_tz.utc)
    )
    return out


def test_cutover_rule_recognition_planned_and_boundary(company):
    shadow_ready(company)
    orders = cutover_orders(company)
    run = reconcile.reconcile(company.id)
    assert run.status == "success", [
        f["message"] for f in run.summary["findings"] if f["severity"] == "error"
    ]
    out = switch(company)
    assert "recognized: 1" in out and "to_planned: 1" in out and "boundary: 1" in out
    with tenant_context(company.id):
        by = {k: Income.objects.get(order=o, kind="freight") for k, (o, _t) in orders.items()}
        assert (
            by["open"].status == "planned"
            and by["open"].recognized_on is None
            and by["open"].base_amount is None
        )
        assert by["later"].status == "recognized" and by["later"].recognized_on == date(2026, 7, 16)
        assert (
            by["later"].recognition_basis == "trip_completed"
            and by["later"].income_trips.count() == 1
        )
        # граница: завершён 06-20 < cutover, строка 07-15 > cutover: запись как была + Issue
        assert by["earlier"].status == "recognized" and by["earlier"].recognized_on == date(
            2026, 7, 15
        )
        assert by["earlier"].recognition_basis == "legacy_line_date"
        issue = FinanceMigrationIssue.objects.get(issue_type="cutover_boundary")
        assert issue.source_id == by["earlier"].pk and issue.status == "open"
        # прошлые доходы (до cutover) нетронуты
        old = Income.objects.filter(recognized_on__lt=CUT, recognition_basis="legacy_line_date")
        assert old.count() >= 3
    with tenant_context(company.id):
        assert OrderService.objects.filter(order=orders["open"][0], is_base=True).exists()


def test_switch_rolls_back_entirely_on_closed_period(company):
    shadow_ready(company)
    cutover_orders(company)
    with time_machine.travel(datetime(2026, 8, 20, tzinfo=dt_tz.utc), tick=False):
        periods.close_period(company, 2026, 7, first_user(company))
        with pytest.raises(CommandError):
            switch(company)
    assert settings_of(company).engine == "shadow"
    with tenant_context(company.id):  # ни один доход не изменён
        assert not Income.objects.filter(recognition_basis="trip_completed").exists()


# --- откат -------------------------------------------------------------------------------


def rollback(company, to="shadow", ref=REF, *args):
    return call_command(
        "rollback_finance_engine", "--company", str(company.id), "--to", to,
        *(["--approval-ref", ref] if ref else []), *args, stdout=StringIO(),
    )  # fmt: skip


def switched(company):
    shadow_ready(company)
    switch(company)


def test_rollback_allowed_keeps_all_data(company):
    switched(company)
    before = (snapshot(company), counts(company))
    rollback(company, "shadow", REF, "--dry-run")
    assert settings_of(company).engine == "new"
    rollback(company, "legacy")
    assert settings_of(company).engine == "legacy"
    assert (snapshot(company), counts(company)) == before  # ничего не удалено
    with tenant_context(company.id):
        assert AuditLog.objects.filter(changes__source="rollback_finance_engine").exists()


def test_rollback_refusals(company):
    shadow_ready(company)
    with pytest.raises(CommandError) as exc:
        rollback(company)
    assert "engine_not_new" in str(exc.value)
    switch(company)
    with pytest.raises(CommandError) as exc:
        rollback(company, ref="")
    assert "approval_ref_missing" in str(exc.value)
    # старше 30 дней
    with time_machine.travel(
        datetime(2027, 3, 25, tzinfo=dt_tz.utc),
        tick=False,
    ):
        with pytest.raises(CommandError) as exc:
            rollback(company)
    assert "rollback_window_expired" in str(exc.value)
    assert settings_of(company).engine == "new"


def _native(company, kind):
    user = first_user(company)
    with tenant_context(company.id):
        if kind == "service":
            o = make_order(company)
            income.plan_service(o, "Новая услуга", "Прочее", D("5"), user)
        elif kind == "expense":
            from apps.core.handbooks.models import HandbookValue

            cat = HandbookValue.objects.get(handbook__code="expense_category", code="OTHER")
            expenses.create_expense(
                company, title="Новый", category=cat, amount=D("3"), currency=cur(company),
                expense_date=date(2026, 7, 20), user=user, perms=("finance.backdate",),
            )  # fmt: skip
        elif kind == "adjust":
            inc = (
                Income.objects.filter(kind="freight", status="recognized").first()
                or Income.objects.exclude(status="void").first()
            )
            Income.objects.filter(pk=inc.pk).update(recognition_basis="manual_adjustment")
        elif kind == "void_expense":
            e = Expense.objects.filter(status="active").first()
            Expense.objects.filter(pk=e.pk).update(status="void", void_reason="Ошибочный")


@pytest.mark.parametrize(
    "kind,code",
    [
        ("service", "native_income"),
        ("expense", "native_expense"),
        ("adjust", "manual_adjustment"),
        ("void_expense", "void_expense"),
    ],
)
def test_rollback_refused_for_native_records(company, kind, code):
    switched(company)
    _native(company, kind)
    with pytest.raises(CommandError) as exc:
        rollback(company, "legacy")
    assert code in str(exc.value)
    assert settings_of(company).engine == "new"


def test_rollback_refused_when_reconcile_fails(company):
    switched(company)
    with tenant_context(company.id):
        line = OrderService.objects.filter(income__gt=0).first()
        OrderService.objects.filter(pk=line.pk).update(income=line.income + D("9"))
    with pytest.raises(CommandError) as exc:
        rollback(company)
    assert "reconcile_not_success" in str(exc.value)


# --- заморозка ---------------------------------------------------------------------------


def test_freeze_blocks_all_writers_but_not_reads(company, admin_client):
    s = build(company)
    run_cmd(company)
    inv = s["out_inv"]
    call_command(
        "freeze_finance",
        "--company",
        str(company.id),
        "--on",
        "--reason",
        "Проверка",
        stdout=StringIO(),
    )
    assert settings_of(company).financial_writes_frozen is True
    o = s["o1"]
    # API строк заказа (legacy): запись -> 423, чтение работает
    r = admin_client.post(LINES, {"order": o.pk, "title": "Услуга", "income": "100"}, format="json")
    assert r.status_code == 423 and r.json()["code"] == "finance_frozen"
    assert admin_client.get(f"{LINES}?order={o.pk}").status_code == 200
    user = first_user(company)
    with tenant_context(company.id):
        for fn in (
            lambda: inv_svc.cancel(inv, user=user),
            lambda: pay_invoice(company, inv, "10"),
            lambda: income.sync_planned_freight(o),
            lambda: income.plan_service(o, "x", "", D("1"), user),
            lambda: migration.migrate_order(o),
        ):
            with pytest.raises(FinanceError) as exc:
                fn()
            assert exc.value.status_code == 423 and exc.value.detail.code == "finance_frozen"
    assert admin_client.get("/api/finance/summary/").status_code == 200
    assert admin_client.get("/api/finance/operations/").status_code == 200
    call_command(
        "freeze_finance",
        "--company",
        str(company.id),
        "--off",
        "--reason",
        "Снято",
        stdout=StringIO(),
    )
    r = admin_client.post(LINES, {"order": o.pk, "title": "Услуга", "income": "100"}, format="json")
    assert r.status_code == 201
    with tenant_context(company.id):
        assert AuditLog.objects.filter(changes__source="freeze_finance").count() == 2
    with pytest.raises(CommandError):
        call_command("freeze_finance", "--company", str(company.id), "--on", "--reason", " ")


def test_freeze_is_per_company(company, make_company, admin_client):
    other, _, other_client = make_company("Other")
    switching.set_frozen(company.id, True, reason="Только своя")
    o = make_order(other)
    r = other_client.post(LINES, {"order": o.pk, "title": "Услуга", "income": "100"}, format="json")
    assert r.status_code == 201
    assert settings_of(other).financial_writes_frozen is False


def test_shadow_mirror_is_frozen_too(company, admin_client):
    set_engine(company, "shadow")
    o = make_order(company)
    switching.set_frozen(company.id, True, reason="Проверка")
    r = admin_client.post(LINES, {"order": o.pk, "title": "Услуга", "income": "100"}, format="json")
    assert r.status_code == 423


# --- OrderService защищён в new ------------------------------------------------------------


def test_legacy_lines_readonly_in_new(company, admin_client):
    switched(company)
    with tenant_context(company.id):
        line = OrderService.objects.filter(is_base=False).first()
        order = line.order
        base = OrderService.objects.filter(order=order).first()
    before = old_lines(company)
    r = admin_client.post(
        LINES, {"order": order.pk, "title": "Услуга", "income": "100"}, format="json"
    )
    assert (
        r.status_code == 409
        and r.json()["code"] == "legacy_lines_readonly"
        and "Доходы" in r.json()["detail"]
    )
    assert (
        admin_client.patch(f"{LINES}{line.pk}/", {"income": "1"}, format="json").status_code == 409
    )
    assert admin_client.delete(f"{LINES}{line.pk}/").status_code == 409
    assert admin_client.get(f"{LINES}{line.pk}/").status_code == 200  # GET как обёртка
    assert old_lines(company) == before
    # смена ставки пользователем не пишет базовую строку (системный путь не пишет в new)
    admin_client.patch(f"/api/orders/{order.pk}/", {"client_rate": "12345"}, format="json")
    assert old_lines(company) == before and base


def old_lines(company):
    with tenant_context(company.id):
        return list(
            OrderService.objects.order_by("pk").values_list("pk", "income", "expense", "title")
        )


def test_legacy_and_shadow_unchanged(company, admin_client):
    for engine in ("legacy", "shadow"):
        set_engine(company, engine)
        o = make_order(company)
        r = admin_client.post(
            LINES, {"order": o.pk, "title": engine, "income": "10"}, format="json"
        )
        assert r.status_code == 201


def test_trip_expense_lines_refused_in_new(company, admin_client):
    switched(company)
    o, ids = order_with_cargos(company, 1)
    trip = new_trip(company, ids, price="10")
    r = admin_client.post(
        f"/api/finance/trips/{trip.pk}/expense-lines/",
        {"allocations": [{"order_id": o.pk, "amount": "10"}]}, format="json",
    )  # fmt: skip
    assert r.status_code == 409 and r.json()["code"] == "legacy_lines_readonly"


# --- чтение из новой модели -----------------------------------------------------------------


def snapshot_reads(client):
    orders = client.get("/api/orders/?page_size=100").json()
    rows = orders["results"] if "results" in orders else orders
    totals = sorted(
        (r["number"], r.get("revenue"), r.get("cost"), r.get("profit"), r.get("margin_pct"))
        for r in rows
    )
    dash = client.get("/api/dashboard/summary/").json()
    ops = client.get("/api/finance/operations/?page_size=200").json()
    fin = client.get("/api/finance/summary/").json()
    summ = {k: v for k, v in ops["summary"].items() if k != "unconverted"}
    return {
        "orders": totals,
        "dash": {k: dash[k] for k in ("month_profit", "month_margin_pct", "excluded_orders")},
        "ops_summary": summ,
        "ops_sum_rows": (
            round(sum(float(r["income"]) for r in ops["results"]), 2),
            round(sum(float(r["expense"]) for r in ops["results"]), 2),
        ),
        "fin": {k: fin[k] for k in ("month_profit_kzt", "month_margin_pct")},
    }


def login(client, user, company):
    from apps.core.api.auth import issue_tokens

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")


def test_reads_equivalent_between_old_and_new_paths(company, admin_client, admin_user):
    with time_machine.travel(datetime(2026, 6, 20, 12, 0, tzinfo=dt_tz.utc), tick=False):
        login(admin_client, admin_user, company)
        shadow_ready(company)
        old = snapshot_reads(admin_client)
        assert old["orders"] and old["ops_summary"]["income_kzt"] != "0.00"
        switch(company)
        assert use_new_engine(company)
        new = snapshot_reads(admin_client)
        xlsx = admin_client.get("/api/finance/operations/export/")
    assert new == old
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"


def test_new_engine_reads_come_from_new_tables(company, admin_client, admin_user):
    with time_machine.travel(datetime(2026, 6, 20, 12, 0, tzinfo=dt_tz.utc), tick=False):
        login(admin_client, admin_user, company)
        shadow_ready(company)
        switch(company)
        with tenant_context(company.id):
            inc = Income.objects.filter(kind="service", status="recognized").first()
            Income.objects.filter(pk=inc.pk).update(amount=inc.amount + D("1000"))
        got = admin_client.get(f"/api/orders/{inc.order_id}/").json()
        assert D(str(got["revenue"])) >= inc.amount + D("1000")  # прочитано из Income, не из строк


def test_isolation_between_companies_on_switch(company, make_company):
    other, _, _ = make_company("Other")
    shadow_ready(company)
    simple(other)
    set_engine(other, "shadow")
    switch(company)
    assert settings_of(other).engine == "shadow" and use_new_engine(other) is False
    assert use_new_engine(company) is True
    with tenant_context(other.id):
        assert not Income.objects.filter(recognition_basis="trip_completed").exists()
