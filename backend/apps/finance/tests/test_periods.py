"""Закрытые периоды, запрет обратного датирования и сервис настроек (1.4.3)."""

from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal as D

import pytest
import time_machine

from apps.core.audit.models import AuditLog
from apps.core.handbooks.models import HandbookValue
from apps.core.models import Company, Role
from apps.core.tenancy import tenant_context
from apps.finance import invoices as inv_svc
from apps.finance import periods, settings_service
from apps.finance import trip_expense as te
from apps.finance.errors import FinanceError
from apps.finance.models import (
    CompanyFinancialSettings,
    FinancialPeriod,
    FinancialPeriodEvent,
    Payment,
)
from apps.finance.tests.helpers import (
    add_line,
    cur,
    first_user,
    issue_invoice,
    make_carrier,
    make_order,
    pay_invoice,
)
from apps.forwarding.finance_lines.models import OrderService
from apps.forwarding.tests.test_parties import client_with_role
from apps.forwarding.tests.test_trips import make_cargos, svc_create

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=dt_tz.utc)  # 15 июля, Алматы
MAY, JUNE = date(2026, 5, 10), date(2026, 6, 10)
ADJ, BACK = "finance.adjust_closed", "finance.backdate"


@pytest.fixture(autouse=True)
def frozen():
    with time_machine.travel(NOW, tick=False):
        yield


def code(exc):
    return exc.value.detail.code


def close(company, year=2026, month=5, user=None):
    return periods.close_period(company, year, month, user or first_user(company))


def set_backdating(company, value):
    CompanyFinancialSettings.all_objects.filter(company=company).update(allow_backdating=value)


def audit_rows(company, **filters):
    with tenant_context(company.id):
        return list(AuditLog.objects.filter(**filters).order_by("id"))


def role_client(company, perms, name="Роль"):
    with tenant_context(company.id):
        Role.objects.create(name=name, permissions=list(perms))
    return client_with_role(company, name)[1]


BASE = ["finance.view", "finance.create", "finance.update", "finance.delete", "orders.view"]


# --- закрытие и повторное открытие ---


def test_close_creates_period_event_and_audit(company):
    user = first_user(company)
    period = periods.close_period(company, 2026, 5, user, "закрыли")
    assert (period.status, period.closed_by_id, period.comment) == ("closed", user.pk, "закрыли")
    assert period.closed_at is not None
    with tenant_context(company.id):
        events = list(period.events.all())
    assert [(e.action, e.user_id) for e in events] == [("close", user.pk)]
    assert periods.is_period_closed(company, MAY) and not periods.is_period_closed(company, JUNE)
    rows = audit_rows(company, object_type="finance.financialperiod")
    assert len(rows) == 1 and rows[0].changes["status"] == ["open", "closed"]


def test_close_is_idempotent_without_duplicate_event(company):
    first = close(company)
    again = close(company)
    assert first.pk == again.pk
    with tenant_context(company.id):
        assert FinancialPeriod.objects.count() == 1
        assert FinancialPeriodEvent.objects.count() == 1
    assert len(audit_rows(company, object_type="finance.financialperiod")) == 1


def test_cannot_close_current_or_future_month(company):
    for y, m in ((2026, 7), (2026, 8), (2027, 1)):
        with pytest.raises(FinanceError) as exc:
            periods.close_period(company, y, m, first_user(company))
        assert code(exc) == "period_not_finished" and exc.value.status_code == 409
    close(company, 2026, 6)  # прошедший - можно
    for y, m in ((2026, 0), (2026, 13)):
        with pytest.raises(FinanceError) as exc:
            periods.close_period(company, y, m, first_user(company))
        assert code(exc) == "period_invalid"


def test_close_uses_company_timezone(company):
    """В Алматы (UTC+5) 31 июля 20:00 UTC - уже 1 августа: июль полностью прошёл."""
    with time_machine.travel(datetime(2026, 7, 31, 20, 0, tzinfo=dt_tz.utc), tick=False):
        assert periods.close_period(company, 2026, 7, first_user(company)).status == "closed"
    other = Company.objects.get(pk=company.pk)
    other.timezone = "America/Los_Angeles"
    other.save()
    with time_machine.travel(datetime(2026, 8, 1, 3, 0, tzinfo=dt_tz.utc), tick=False):
        # в Лос-Анджелесе ещё 31 июля вечером: август не начался, июль не закрыть
        with pytest.raises(FinanceError) as exc:
            periods.close_period(company, 2026, 7, first_user(company))
        assert code(exc) == "period_not_finished"


def test_reopen_requires_reason_and_closed_state_keeps_history(company):
    user = first_user(company)
    period = close(company)
    for reason in ("", "  ", None):
        with pytest.raises(FinanceError) as exc:
            periods.reopen_period(period, user, reason)
        assert code(exc) == "reason_required"
    reopened = periods.reopen_period(period, user, "ошибка в проводке")
    assert (
        reopened.status == "open" and reopened.closed_at is None and reopened.closed_by_id is None
    )
    assert not periods.is_period_closed(company, MAY)
    with pytest.raises(FinanceError) as exc:  # уже открыт
        periods.reopen_period(period, user, "ещё")
    assert code(exc) == "period_not_closed" and exc.value.status_code == 409
    again = close(company)  # повторное закрытие того же периода
    assert again.pk == period.pk
    periods.reopen_period(again, user, "вторая правка")
    with tenant_context(company.id):
        events = list(FinancialPeriodEvent.objects.filter(period=period).order_by("id"))
        assert FinancialPeriod.objects.count() == 1  # период один, история не потеряна
    assert [(e.action, e.reason) for e in events] == [
        ("close", ""),
        ("reopen", "ошибка в проводке"),
        ("close", ""),
        ("reopen", "вторая правка"),
    ]
    reopen_audit = [r for r in audit_rows(company, object_type="finance.financialperiod")]
    assert reopen_audit[1].changes == {"status": ["closed", "open"], "reason": "ошибка в проводке"}


def test_period_isolation_between_companies(company, make_company):
    other, _, _ = make_company("Other")
    close(company)
    assert periods.is_period_closed(company, MAY) and not periods.is_period_closed(other, MAY)
    close(other)  # у другой компании свой период за тот же месяц
    with tenant_context(other.id):
        assert FinancialPeriod.objects.count() == 1
    with tenant_context(company.id):
        assert FinancialPeriod.objects.count() == 1


def test_reopen_cannot_reach_other_company_period(company, make_company):
    other, _, _ = make_company("Other")
    period = close(company)
    with tenant_context(other.id), pytest.raises(Exception) as exc:
        periods.reopen_period(period, first_user(other), "чужой")
    assert exc.type.__name__ == "DoesNotExist"
    assert periods.is_period_closed(company, MAY)


# --- assert_period_open ---


def test_assert_period_open_matrix(company):
    close(company)
    assert periods.assert_period_open(company, JUNE) is False  # открыт
    with pytest.raises(FinanceError) as exc:
        periods.assert_period_open(company, MAY)
    assert code(exc) == "period_closed" and exc.value.status_code == 409
    with pytest.raises(FinanceError) as exc:
        periods.assert_period_open(company, MAY, can_adjust=True)
    assert code(exc) == "period_reason_required" and exc.value.status_code == 400
    with pytest.raises(FinanceError):
        periods.assert_period_open(company, MAY, can_adjust=True, reason="   ")
    assert periods.assert_period_open(company, MAY, can_adjust=True, reason="правка") is True
    # граница месяца
    assert periods.is_period_closed(company, date(2026, 5, 31))
    assert periods.is_period_closed(company, date(2026, 5, 1))
    assert not periods.is_period_closed(company, date(2026, 4, 30))
    assert not periods.is_period_closed(company, date(2026, 6, 1))


# --- обратное датирование ---


def test_backdating_rules(company):
    set_backdating(company, False)
    today = date(2026, 7, 15)
    periods.assert_backdating_ok(company, today)
    periods.assert_backdating_ok(company, date(2026, 7, 16))
    periods.assert_backdating_ok(company, date(2027, 1, 1))
    with pytest.raises(FinanceError) as exc:
        periods.assert_backdating_ok(company, date(2026, 7, 14))
    assert code(exc) == "backdating_forbidden" and exc.value.status_code == 409
    periods.assert_backdating_ok(company, date(2026, 7, 14), can_backdate=True)
    set_backdating(company, True)
    periods.assert_backdating_ok(company, date(2020, 1, 1))


def test_backdating_company_timezone_midnight(company):
    set_backdating(company, False)
    # 14 июля 20:00 UTC = 15 июля 01:00 в Алматы: 14 июля уже вчера
    with time_machine.travel(datetime(2026, 7, 14, 20, 0, tzinfo=dt_tz.utc), tick=False):
        periods.assert_backdating_ok(company, date(2026, 7, 15))
        with pytest.raises(FinanceError):
            periods.assert_backdating_ok(company, date(2026, 7, 14))
    # 14 июля 18:59 UTC = 14 июля 23:59 Алматы: 14 июля - сегодня
    with time_machine.travel(datetime(2026, 7, 14, 18, 59, tzinfo=dt_tz.utc), tick=False):
        periods.assert_backdating_ok(company, date(2026, 7, 14))
        with pytest.raises(FinanceError):
            periods.assert_backdating_ok(company, date(2026, 7, 13))


def test_adjust_closed_does_not_cancel_backdating_and_checks_are_independent(company):
    set_backdating(company, False)
    close(company)
    # одно adjust_closed: период пройден, а обратное датирование - нет
    with pytest.raises(FinanceError) as exc:
        periods.check_user_date(company, MAY, {ADJ}, reason="правка")
    assert code(exc) == "backdating_forbidden"
    # одно backdate: период закрыт
    with pytest.raises(FinanceError) as exc:
        periods.check_user_date(company, MAY, {BACK})
    assert code(exc) == "period_closed"
    # оба права, но нет причины
    with pytest.raises(FinanceError) as exc:
        periods.check_user_date(company, MAY, {ADJ, BACK})
    assert code(exc) == "period_reason_required"
    assert periods.check_user_date(company, MAY, {ADJ, BACK}, reason="правка") is True
    # открытый месяц, вчера: нужно backdate
    with pytest.raises(FinanceError):
        periods.check_user_date(company, date(2026, 7, 14), set())
    assert periods.check_user_date(company, date(2026, 7, 14), {BACK}) is False
    set_backdating(company, True)
    assert periods.check_user_date(company, date(2026, 7, 14), set()) is False


def test_company_without_settings_row_or_periods_behaves_as_before(company):
    CompanyFinancialSettings.all_objects.filter(company=company).delete()
    periods.assert_backdating_ok(company, date(2020, 1, 1))
    assert periods.check_user_date(company, date(2020, 1, 1), set()) is False


# --- защищённые операции (сервисы и API) ---


@pytest.fixture
def issued(company):
    """Выставленный счёт клиенту (дата выставления в мае) и оплата в мае."""
    invoice = issue_invoice(company, amount="1000", day=MAY)
    payment = pay_invoice(company, invoice, "100", day=MAY)
    return invoice, payment


def pay_url(invoice):
    return f"/api/finance/invoices/{invoice.pk}/payments/"


def pay_body(day, **extra):
    return {"date": day.isoformat(), "amount": "50", "method": "bank", **extra}


def adjusted_entries(company, **filters):
    return [r for r in audit_rows(company, **filters) if "closed_period_adjustment" in r.changes]


def test_payment_create_in_closed_period(admin_client, company, issued):
    invoice, _ = issued
    close(company)
    plain = role_client(company, BASE)  # без finance.adjust_closed
    for body in (pay_body(MAY), pay_body(MAY, adjust_reason="не поможет")):
        r = plain.post(pay_url(invoice), body, format="json")
        assert r.status_code == 409 and r.data["code"] == "period_closed", r.content
    # администратор (право есть), но без причины
    r = admin_client.post(pay_url(invoice), pay_body(MAY), format="json")
    assert r.status_code == 400 and r.data["code"] == "period_reason_required"
    with tenant_context(company.id):
        assert Payment.objects.count() == 1  # ничего не создано
    # право и причина
    r = admin_client.post(
        pay_url(invoice), pay_body(MAY, adjust_reason="Поздно пришла выписка"), format="json"
    )
    assert r.status_code == 201, r.content
    rows = adjusted_entries(company, object_type="finance.payment")
    assert len(rows) == 1 and rows[0].action == "create"
    adj = rows[0].changes["closed_period_adjustment"]
    assert adj["reason"] == "Поздно пришла выписка" and adj["old"] is None
    assert adj["new"] == {"date": "2026-05-10", "amount": "50.00"}
    # открытый месяц - как прежде, без записи о корректировке
    r = admin_client.post(pay_url(invoice), pay_body(date(2026, 7, 15)), format="json")
    assert r.status_code == 201
    assert len(adjusted_entries(company, object_type="finance.payment")) == 1


def test_payment_backdating_only_when_forbidden(admin_client, company, issued):
    invoice, _ = issued
    set_backdating(company, False)
    plain = role_client(company, BASE)
    r = plain.post(pay_url(invoice), pay_body(date(2026, 7, 14)), format="json")
    assert r.status_code == 409 and r.data["code"] == "backdating_forbidden"
    assert (
        plain.post(pay_url(invoice), pay_body(date(2026, 7, 15)), format="json").status_code == 201
    )
    with_back = role_client(company, [*BASE, BACK], name="С backdate")
    assert (
        with_back.post(pay_url(invoice), pay_body(date(2026, 7, 14)), format="json").status_code
        == 201
    )
    only_adjust = role_client(company, [*BASE, ADJ], name="Только adjust")
    r = only_adjust.post(pay_url(invoice), pay_body(date(2026, 7, 13)), format="json")
    assert r.status_code == 409 and r.data["code"] == "backdating_forbidden"


def test_payment_delete_in_closed_period(admin_client, company, issued):
    _, payment = issued
    close(company)
    plain = role_client(company, BASE)
    r = plain.delete(f"/api/finance/payments/{payment.pk}/")
    assert r.status_code == 409 and r.data["code"] == "period_closed"
    r = admin_client.delete(f"/api/finance/payments/{payment.pk}/")
    assert r.status_code == 400 and r.data["code"] == "period_reason_required"
    with tenant_context(company.id):
        assert Payment.objects.count() == 1
    r = admin_client.delete(
        f"/api/finance/payments/{payment.pk}/", {"adjust_reason": "дубль"}, format="json"
    )
    assert r.status_code == 204
    rows = adjusted_entries(company, object_type="finance.payment")
    assert len(rows) == 1 and rows[0].action == "delete"
    adj = rows[0].changes["closed_period_adjustment"]
    assert adj["old"] == {"date": "2026-05-10", "amount": "100.00"} and adj["new"] is None
    with tenant_context(company.id):
        assert Payment.objects.count() == 0


def test_cancel_issued_invoice_by_issue_date(admin_client, company):
    invoice = issue_invoice(company, amount="500", day=MAY)
    close(company)
    url = f"/api/finance/invoices/{invoice.pk}/cancel/"
    plain = role_client(company, [*BASE, "finance.cancel_invoice"])
    r = plain.post(url, {}, format="json")
    assert r.status_code == 409 and r.data["code"] == "period_closed"
    r = admin_client.post(url, {}, format="json")
    assert r.status_code == 400 and r.data["code"] == "period_reason_required"
    r = admin_client.post(url, {"adjust_reason": "ошибочный счёт"}, format="json")
    assert r.status_code == 200, r.content
    rows = adjusted_entries(company, object_type="finance.invoice")
    assert len(rows) == 1
    assert rows[0].changes["closed_period_adjustment"]["old"] == {"status": "issued"}
    assert rows[0].changes["closed_period_adjustment"]["new"] == {"status": "cancelled"}


def test_issue_invoice_in_closed_period_service(company):
    from apps.finance.invoices import create_draft
    from apps.finance.tests.helpers import make_client, vat

    user = first_user(company)
    order = make_order(company)
    close(company)
    with tenant_context(company.id):
        line = add_line(company, order, income=300)
        draft = create_draft(
            direction="out",
            party=order.client,
            order=order,
            currency=cur(company),
            vat_rate=vat(company, "0"),
            due_date=None,
            items=[{"title": "x", "amount_net": D("300"), "line": line}],
            user=user,
        )
        with pytest.raises(FinanceError) as exc:
            inv_svc.issue(draft, user=user, issue_date=MAY)
        assert code(exc) == "period_closed"
        with pytest.raises(FinanceError) as exc:
            inv_svc.issue(draft, user=user, issue_date=MAY, perms={ADJ})
        assert code(exc) == "period_reason_required"
        issued_inv = inv_svc.issue(
            draft, user=user, issue_date=MAY, perms={ADJ}, adjust_reason="поздняя отгрузка"
        )
    assert issued_inv.status == "issued"
    assert len(adjusted_entries(company, object_type="finance.invoice")) == 1
    _ = make_client


def test_issue_in_open_period_is_unchanged(company):
    invoice = issue_invoice(company, amount="100", day=date(2026, 7, 1))
    assert invoice.status == "issued"
    assert adjusted_entries(company) == []


# --- строки заказа /api/order-lines/ ---


def lines_url(pk=None):
    return "/api/order-lines/" + (f"{pk}/" if pk else "")


def line_body(order, day, **extra):
    return {"order": order.pk, "title": "Услуга", "income": "100", "date": day.isoformat(), **extra}


def test_order_line_create_update_delete_in_closed_period(admin_client, company):
    order = make_order(company)
    line = add_line(company, order, income=100, day=MAY)  # строка в мае, до закрытия
    open_line = add_line(company, order, income=50, day=JUNE)
    close(company)
    plain = role_client(company, BASE)
    # создание
    r = plain.post(lines_url(), line_body(order, MAY), format="json")
    assert r.status_code == 409 and r.data["code"] == "period_closed"
    r = admin_client.post(lines_url(), line_body(order, MAY), format="json")
    assert r.status_code == 400 and r.data["code"] == "period_reason_required"
    r = admin_client.post(
        lines_url(), line_body(order, MAY, adjust_reason="доначисление"), format="json"
    )
    assert r.status_code == 201, r.content
    # изменение суммы старой строки (старая дата в закрытом месяце)
    r = plain.patch(lines_url(line.pk), {"income": "120"}, format="json")
    assert r.status_code == 409 and r.data["code"] == "period_closed"
    r = admin_client.patch(
        lines_url(line.pk), {"income": "120", "adjust_reason": "уточнение"}, format="json"
    )
    assert r.status_code == 200, r.content
    # перенос строки из открытого месяца в закрытый (новая дата)
    r = plain.patch(lines_url(open_line.pk), {"date": MAY.isoformat()}, format="json")
    assert r.status_code == 409 and r.data["code"] == "period_closed"
    r = admin_client.patch(lines_url(open_line.pk), {"date": MAY.isoformat()}, format="json")
    assert r.status_code == 400 and r.data["code"] == "period_reason_required"
    # перенос из закрытого в открытый тоже защищён (старая дата)
    r = plain.patch(lines_url(line.pk), {"date": JUNE.isoformat()}, format="json")
    assert r.status_code == 409
    # удаление
    r = plain.delete(lines_url(line.pk))
    assert r.status_code == 409 and r.data["code"] == "period_closed"
    r = admin_client.delete(lines_url(line.pk))
    assert r.status_code == 400 and r.data["code"] == "period_reason_required"
    r = admin_client.delete(lines_url(line.pk), {"adjust_reason": "лишняя"}, format="json")
    assert r.status_code == 204
    rows = adjusted_entries(company, object_type="forwarding.orderservice")
    assert [r.action for r in rows] == ["create", "update", "delete"]
    upd = rows[1].changes["closed_period_adjustment"]
    assert upd["reason"] == "уточнение"
    assert upd["old"]["income"] == "100.00" and upd["new"]["income"] == "120.00"
    assert rows[2].changes["closed_period_adjustment"]["new"] is None
    # открытый месяц - как прежде
    assert plain.patch(lines_url(open_line.pk), {"income": "55"}, format="json").status_code == 200


def test_order_line_backdating_uses_entered_date_only(admin_client, company):
    order = make_order(company)
    set_backdating(company, False)
    plain = role_client(company, BASE)
    r = plain.post(lines_url(), line_body(order, date(2026, 7, 14)), format="json")
    assert r.status_code == 409 and r.data["code"] == "backdating_forbidden"
    # дата не указана: строка получает «сегодня» компании
    r = plain.post(
        lines_url(), {"order": order.pk, "title": "Без даты", "income": "1"}, format="json"
    )
    assert r.status_code == 201
    assert (
        plain.post(lines_url(), line_body(order, date(2026, 7, 15)), format="json").status_code
        == 201
    )
    with_back = role_client(company, [*BASE, BACK], name="Backdate")
    assert (
        with_back.post(lines_url(), line_body(order, date(2026, 7, 14)), format="json").status_code
        == 201
    )
    # правка суммы строки со старой датой без смены даты не считается вводом даты
    old = add_line(company, order, income=5, day=date(2026, 7, 1))
    assert plain.patch(lines_url(old.pk), {"income": "6"}, format="json").status_code == 200
    r = plain.patch(lines_url(old.pk), {"date": "2026-06-30"}, format="json")
    assert r.status_code == 409 and r.data["code"] == "backdating_forbidden"


def test_company_without_periods_lines_as_before(admin_client, company):
    order = make_order(company)
    r = admin_client.post(lines_url(), line_body(order, date(2020, 1, 1)), format="json")
    assert r.status_code == 201
    assert adjusted_entries(company) == []


# --- расход по рейсу ---


def test_trip_expense_blocked_when_current_month_closed(company):
    order, ids = make_cargos(company, 1)
    trip = svc_create(company, ids, carrier=make_carrier(company), data={"carrier_price": D("100")})
    user = first_user(company)
    with tenant_context(company.id):
        FinancialPeriod.objects.create(
            year=2026, month=7, status="closed"
        )  # напрямую, для проверки
        alloc = [{"order_id": order.pk, "amount": D("100")}]
        with pytest.raises(FinanceError) as exc:
            te.create_trip_expense(trip, alloc, user=user)
        assert code(exc) == "period_closed"
        with pytest.raises(FinanceError) as exc:
            te.create_trip_expense(trip, alloc, user=user, perms={ADJ})
        assert code(exc) == "period_reason_required"
        assert OrderService.objects.filter(order=order, category="Перевозка").count() == 0
        lines = te.create_trip_expense(trip, alloc, user=user, perms={ADJ}, adjust_reason="правка")
        assert len(lines) == 1
    assert len(adjusted_entries(company, object_type="forwarding.orderservice")) == 1


def test_trip_expense_open_period_unchanged(company):
    order, ids = make_cargos(company, 1)
    trip = svc_create(company, ids, carrier=make_carrier(company), data={"carrier_price": D("100")})
    with tenant_context(company.id):
        lines = te.create_trip_expense(
            trip, [{"order_id": order.pk, "amount": D("100")}], user=first_user(company)
        )
    assert len(lines) == 1 and adjusted_entries(company) == []


# --- update_settings ---


def vh(company, handbook, code_):
    with tenant_context(company.id):
        return HandbookValue.objects.get(handbook__code=handbook, code=code_)


def test_update_settings_changes_and_audit(company):
    user = first_user(company)
    vat12 = vh(company, "vat_rate", "12")
    st = update = settings_service.update_settings(
        company,
        {
            "allow_backdating": False,
            "default_vat_rate": vat12.pk,
            "fiscal_year_start_month": 4,
            "expense_creation_mode": "on_assign",
            "sync_carrier_price": False,
        },
        user,
    )
    assert update is st
    row = CompanyFinancialSettings.all_objects.get(company=company)
    assert (row.allow_backdating, row.default_vat_rate_id, row.fiscal_year_start_month) == (
        False,
        vat12.pk,
        4,
    )
    assert (row.expense_creation_mode, row.sync_carrier_price, row.updated_by_id) == (
        "on_assign",
        False,
        user.pk,
    )
    rows = audit_rows(company, object_type="finance.companyfinancialsettings")
    assert len(rows) == 1
    assert rows[0].changes == {
        "allow_backdating": [True, False],
        "default_vat_rate_id": [None, vat12.pk],
        "expense_creation_mode": ["manual", "on_assign"],
        "fiscal_year_start_month": [1, 4],
        "sync_carrier_price": [True, False],
    }
    # без реальных изменений - без новой записи аудита
    settings_service.update_settings(company, {"allow_backdating": False}, user)
    assert len(audit_rows(company, object_type="finance.companyfinancialsettings")) == 1
    # сброс ставки НДС
    settings_service.update_settings(company, {"default_vat_rate": None}, user)
    assert CompanyFinancialSettings.all_objects.get(company=company).default_vat_rate_id is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("engine", "new"),
        ("cutover_date", "2026-01-01"),
        ("income_recognition", "all_trips_completed"),
        ("accounting_method", "ACCRUAL"),
        ("base_currency", 1),
    ],
)
def test_update_settings_forbidden_fields(company, field, value):
    before = CompanyFinancialSettings.all_objects.values().get(company=company)
    with pytest.raises(FinanceError) as exc:
        settings_service.update_settings(
            company, {"allow_backdating": False, field: value}, first_user(company)
        )
    assert code(exc) == "setting_forbidden"
    assert CompanyFinancialSettings.all_objects.values().get(company=company) == before
    assert audit_rows(company, object_type="finance.companyfinancialsettings") == []


def test_update_settings_unknown_and_invalid_values(company):
    user = first_user(company)
    cases = [
        ({"bogus": 1}, "setting_unknown"),
        ({"allow_backdating": "yes"}, "setting_invalid"),
        ({"allow_backdating": 1}, "setting_invalid"),
        ({"fiscal_year_start_month": 0}, "setting_invalid"),
        ({"fiscal_year_start_month": 13}, "setting_invalid"),
        ({"fiscal_year_start_month": True}, "setting_invalid"),
        ({"expense_creation_mode": "auto"}, "setting_invalid"),
        ({"default_vat_rate": 999999}, "setting_invalid"),
    ]
    for changes, expected in cases:
        with pytest.raises(FinanceError) as exc:
            settings_service.update_settings(company, changes, user)
        assert code(exc) == expected, changes


def test_update_settings_completed_status_validation(company, make_company):
    other, _, _ = make_company("Other")
    user = first_user(company)
    done = vh(company, "trip_status", "COMPLETED")
    cancelled = vh(company, "trip_status", "CANCELLED")
    settings_service.update_settings(company, {"completed_status": cancelled.pk}, user)
    assert (
        CompanyFinancialSettings.all_objects.get(company=company).completed_status_id
        == cancelled.pk
    )
    settings_service.update_settings(company, {"completed_status": done}, user)  # объект тоже
    for bad in (
        vh(other, "trip_status", "COMPLETED").pk,  # чужая компания
        vh(company, "vat_rate", "12").pk,  # не trip_status
        "abc",
        True,
    ):
        with pytest.raises(FinanceError) as exc:
            settings_service.update_settings(company, {"completed_status": bad}, user)
        assert code(exc) == "setting_invalid", bad
    # неактивное значение (прямое обновление: системное значение защищено в ORM)
    with tenant_context(company.id):
        custom = HandbookValue.objects.create(
            handbook=done.handbook, name="Доставлен", order=9, is_active=False
        )
    with pytest.raises(FinanceError) as exc:
        settings_service.update_settings(company, {"completed_status": custom.pk}, user)
    assert code(exc) == "setting_invalid"
    assert CompanyFinancialSettings.all_objects.get(company=company).completed_status_id == done.pk


def test_update_settings_clear_completed_status_blocked_for_new_engine(company):
    CompanyFinancialSettings.all_objects.filter(company=company).update(
        engine="new", cutover_date=date(2026, 1, 1)
    )
    with pytest.raises(FinanceError) as exc:
        settings_service.update_settings(company, {"completed_status": None}, first_user(company))
    assert code(exc) == "setting_invalid"
    assert CompanyFinancialSettings.all_objects.get(company=company).completed_status_id is not None


def test_update_settings_isolated_between_companies(company, make_company):
    other, _, _ = make_company("Other")
    settings_service.update_settings(company, {"fiscal_year_start_month": 7}, first_user(company))
    assert CompanyFinancialSettings.all_objects.get(company=other).fiscal_year_start_month == 1
    assert audit_rows(other, object_type="finance.companyfinancialsettings") == []
