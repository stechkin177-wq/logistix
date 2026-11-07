"""Доходы (1.4.4): плановый доход, признание по рейсам, возврат, услуги, корректировка."""

import threading
from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal as D

import pytest
import time_machine
from django.db import connection
from rest_framework.exceptions import ValidationError

from apps.core.audit.models import AuditLog
from apps.core.tenancy import tenant_context
from apps.finance import hooks, periods
from apps.finance import income as inc
from apps.finance.errors import FinanceError
from apps.finance.models import CompanyFinancialSettings, Income, IncomeTrip
from apps.finance.tests.helpers import cur, first_user
from apps.finance.tests.p2_helpers import (
    enable_new,
    freight,
    move,
    new_trip,
    order_with_cargos,
    rate,
    reload,
    set_engine,
)
from apps.forwarding.models import Trip
from apps.forwarding.orders.services import create_order
from apps.forwarding.tests.test_orders import make_client
from apps.forwarding.tests.test_trips import make_cargos

pytestmark = pytest.mark.django_db
T1 = datetime(2026, 6, 1, 10, 0, tzinfo=dt_tz.utc)
T2 = datetime(2026, 6, 3, 21, 0, tzinfo=dt_tz.utc)  # 4 июня 02:00 в Алматы
T3 = datetime(2026, 6, 5, 9, 0, tzinfo=dt_tz.utc)


def code(exc):
    return exc.value.detail.code


def one(order):
    rows = freight(order)
    assert len(rows) == 1, rows
    return rows[0]


def planned_order(company, n=1, rate_="1000.00"):
    enable_new(company)
    order, ids = order_with_cargos(company, n, client_rate=D(rate_))
    return order, ids


def audit_of(company, obj):
    with tenant_context(company.id):
        return list(
            AuditLog.objects.filter(
                object_type=obj._meta.label_lower, object_id=str(obj.pk)
            ).order_by("id")
        )


# --- плановый доход и хук заказа ---


def test_hook_creates_planned_freight_on_order_create_only_for_new_engine(company):
    legacy_order, _ = order_with_cargos(company, 1, client_rate=D("500"))
    assert freight(legacy_order) == []  # engine=legacy: хук спит
    enable_new(company)
    order, _ = order_with_cargos(company, 1, client_rate=D("750.50"))
    income = one(order)
    assert (income.status, income.amount, income.currency_id) == (
        "planned", D("750.50"), order.currency_id,
    )  # fmt: skip
    assert income.recognized_on is None and income.kind == "freight"


def test_planned_follows_client_rate_until_recognized(company):
    order, ids = planned_order(company)
    with tenant_context(company.id):
        order.client_rate = D("1500.00")
        order.save()
        inc.sync_planned_freight(order)
        inc.sync_planned_freight(order)  # идемпотентно
    income = one(order)
    assert income.amount == D("1500.00")
    trip = new_trip(company, ids)
    move(company, trip, "COMPLETED", T1)
    income = one(order)
    assert income.status == "recognized" and income.amount == D("1500.00")
    with tenant_context(company.id):
        order.client_rate = D("9999.00")
        order.save()
        inc.sync_planned_freight(order)
    assert one(order).amount == D("1500.00")  # признанный не меняется автоматически


# --- признание ---


def test_single_trip_recognition_values(company):
    order, ids = planned_order(company)
    trip = new_trip(company, ids)
    move(company, trip, "COMPLETED", T2)
    income = one(order)
    assert income.status == "recognized" and income.recognition_basis == "trip_completed"
    assert income.recognized_on == date(2026, 6, 4)  # дата по часовому поясу компании
    assert income.trip_id == trip.pk
    assert (income.fx_rate_source, income.fx_rate, income.base_amount) == (
        "same", D("1.000000"), D("1000.00"),
    )  # fmt: skip
    assert income.fx_base_currency_id == cur(company, "KZT").pk
    with tenant_context(company.id):
        assert list(IncomeTrip.objects.filter(income=income).values_list("trip_id", flat=True)) == [
            trip.pk
        ]


def test_multiple_trips_recognized_only_after_all_completed(company):
    order, ids = planned_order(company, n=2)
    t1 = new_trip(company, [ids[0]])
    t2 = new_trip(company, [ids[1]])
    move(company, t1, "COMPLETED", T1)
    assert one(order).status == "planned"  # завершён только один рейс
    move(company, t2, "COMPLETED", T3)
    income = one(order)
    assert income.status == "recognized" and income.recognized_on == date(2026, 6, 5)
    assert income.trip_id == t2.pk
    with tenant_context(company.id):
        assert sorted(
            IncomeTrip.objects.filter(income=income).values_list("trip_id", flat=True)
        ) == sorted([t1.pk, t2.pk])


def test_consolidated_trip_recognizes_every_order(company):
    enable_new(company)
    orders, ids = [], []
    for rate_ in ("100", "200", "300"):
        o, cids = make_cargos(company, 1, client_rate=D(rate_))
        orders.append(o)
        ids += cids
    trip = new_trip(company, ids)
    move(company, trip, "COMPLETED", T1)
    for o, amount in zip(orders, ("100.00", "200.00", "300.00")):
        income = one(o)
        assert income.status == "recognized" and income.amount == D(amount)
    with tenant_context(company.id):
        assert Income.objects.filter(status="recognized").count() == 3


def test_cancelled_trip_is_not_counted(company):
    order, ids = planned_order(company, n=2)
    t1 = new_trip(company, [ids[0]])
    t2 = new_trip(company, [ids[1]])
    move(company, t1, "COMPLETED", T1)
    assert one(order).status == "planned"
    move(company, t2, "CANCELLED", T2)  # остался один действующий и он завершён
    income = one(order)
    assert income.status == "recognized" and income.recognized_on == date(2026, 6, 1)
    with tenant_context(company.id):
        assert list(IncomeTrip.objects.filter(income=income).values_list("trip_id", flat=True)) == [
            t1.pk
        ]


def test_all_trips_cancelled_means_no_recognition(company):
    order, ids = planned_order(company, n=2)
    for cid in ids:
        move(company, new_trip(company, [cid]), "CANCELLED", T1)
    assert one(order).status == "planned"
    # заказ без рейсов тоже не признаётся
    order2, _ = planned_order(company)
    with tenant_context(company.id):
        assert inc.recognize_order_income(order2).status == "planned"


def test_unfinished_cancelled_waits_for_remaining(company):
    order, ids = planned_order(company, n=2)
    t1 = new_trip(company, [ids[0]])
    t2 = new_trip(company, [ids[1]])
    move(company, t2, "CANCELLED", T1)
    assert one(order).status == "planned"  # t1 ещё не завершён
    move(company, t1, "COMPLETED", T2)
    assert one(order).status == "recognized"


def test_repeated_calls_do_not_duplicate_or_change(company):
    order, ids = planned_order(company)
    trip = new_trip(company, ids)
    move(company, trip, "COMPLETED", T1)
    first = one(order)
    audits = len(audit_of(company, first))
    with tenant_context(company.id):
        for _ in range(3):
            assert inc.recognize_order_income(order).pk == first.pk
            inc.reconcile_order_income(order)
    again = one(order)
    assert (again.recognized_on, again.base_amount, again.fx_rate) == (
        first.recognized_on, first.base_amount, first.fx_rate,
    )  # fmt: skip
    assert len(audit_of(company, again)) == audits
    with pytest.raises(ValidationError):  # повторное завершение рейса отвергается
        move(company, trip, "COMPLETED", T2)
    assert len(freight(order)) == 1


def test_revert_from_completed_and_complete_again(company):
    order, ids = planned_order(company)
    trip = new_trip(company, ids)
    move(company, trip, "COMPLETED", T1)
    assert one(order).status == "recognized"
    move(company, trip, "IN_PROGRESS", T2, reason="правка данных")
    back = one(order)
    assert back.status == "planned" and back.recognized_on is None
    assert back.recognition_basis == "" and back.trip_id is None and back.base_amount is None
    assert back.fx_rate is None and back.fx_rate_source == ""
    with tenant_context(company.id):  # связь с рейсом сохранена
        assert IncomeTrip.objects.filter(income=back).count() == 1
    trail = audit_of(company, back)
    assert any(
        "recognition" in a.changes and a.changes["recognition"][0]["status"] == "recognized"
        for a in trail
    )
    move(company, trip, "COMPLETED", T3)
    final = one(order)
    assert (
        final.pk == back.pk
        and final.status == "recognized"
        and final.recognized_on == date(2026, 6, 5)
    )
    assert len(freight(order)) == 1


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_recognize_one_income(company):
    enable_new(company)
    order, ids = order_with_cargos(company, 1, client_rate=D("100"))
    trip = new_trip(company, ids)
    with tenant_context(company.id):
        Trip.objects.filter(pk=trip.pk).update(status=hooks_status(company), completed_at=T1)
    errors = []
    barrier = threading.Barrier(4)

    def work():
        try:
            barrier.wait()
            inc.recognize_order_income(order)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=work) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    rows = freight(order)
    assert len(rows) == 1 and rows[0].status == "recognized"
    with tenant_context(company.id):
        assert IncomeTrip.objects.filter(income=rows[0]).count() == 1


def hooks_status(company):
    from apps.finance.tests.p2_helpers import status

    return status(company, "COMPLETED")


# --- хуки: engine, completed_status, FX, периоды ---


def test_legacy_and_shadow_engines_do_not_recognize(company):
    for engine in ("legacy", "shadow"):
        set_engine(company, engine)
        order, ids = order_with_cargos(company, 1, client_rate=D("10"))
        move(company, new_trip(company, ids), "COMPLETED", T1)
        assert freight(order) == []


def test_engine_new_without_completed_status_aborts_operation(company):
    order, ids = planned_order(company)
    CompanyFinancialSettings.all_objects.filter(company=company).update(
        engine="shadow", completed_status=None
    )
    trip = new_trip(company, ids)
    # engine != new: основная операция проходит без финансовой записи
    move(company, trip, "COMPLETED", T1)
    # engine=new с пустым completed_status недопустим (БД не даёт); имитируем на уровне сервиса
    with tenant_context(company.id):
        settings = CompanyFinancialSettings.objects.get()
        assert settings.completed_status_id is None
        with pytest.raises(FinanceError) as exc:
            inc.completion_state(order, settings)
    assert code(exc) == "completed_status_missing" and exc.value.status_code == 409


def test_hook_error_aborts_trip_status_change(company, monkeypatch):
    order, ids = planned_order(company)
    trip = new_trip(company, ids)

    def boom(*a, **k):
        raise FinanceError("boom", "ошибка финансовой записи", status_code=409)

    monkeypatch.setattr(inc, "reconcile_order_income", boom)
    with pytest.raises(FinanceError):
        move(company, trip, "COMPLETED", T1)
    fresh = Trip.all_objects.get(pk=trip.pk)
    assert fresh.status.code == "PLANNED" and fresh.completed_at is None  # откат основной операции


def test_missing_rate_blocks_completion_and_changes_nothing(company):
    enable_new(company)
    order, ids = order_with_cargos(company, 1, client_rate=D("10"))
    with tenant_context(company.id):
        from apps.forwarding.models import Order

        Order.all_objects.filter(pk=order.pk).update(currency=cur(company, "USD"))
        inc.sync_planned_freight(Order.all_objects.get(pk=order.pk))
    trip = new_trip(company, ids)
    with pytest.raises(FinanceError) as exc:
        move(company, trip, "COMPLETED", T1)
    assert code(exc) == "rate_missing" and exc.value.status_code == 409
    assert Trip.all_objects.get(pk=trip.pk).completed_at is None
    assert one(order).status == "planned"
    rate(company, "USD", "480", date(2026, 1, 1))
    move(company, trip, "COMPLETED", T1)
    done = one(order)
    assert done.status == "recognized" and done.base_amount == D("4800.00")
    assert done.fx_rate_source == "via_kzt" and done.fx_rate == D("480")


def test_closed_period_blocks_recognition_and_unrecognition(company):
    order, ids = planned_order(company)
    trip = new_trip(company, ids)
    move(company, trip, "COMPLETED", datetime(2026, 5, 20, 10, 0, tzinfo=dt_tz.utc))
    assert one(order).recognized_on == date(2026, 5, 20)
    user = first_user(company)
    with time_machine.travel(datetime(2026, 7, 15, 10, 0, tzinfo=dt_tz.utc), tick=False):
        periods.close_period(company, 2026, 5, user)
        # возврат из COMPLETED без права на закрытый период - откат всей операции
        with pytest.raises(FinanceError) as exc:
            move(company, trip, "IN_PROGRESS", None, reason="правка")
        assert code(exc) == "period_closed"
        assert Trip.all_objects.get(pk=trip.pk).status.code == "COMPLETED"
        with pytest.raises(FinanceError) as exc:
            move(
                company,
                trip,
                "IN_PROGRESS",
                None,
                reason="правка",
                perms={"finance.adjust_closed"},
                adjust_reason=" ",
            )
        assert code(exc) == "period_reason_required"
        move(
            company,
            trip,
            "IN_PROGRESS",
            None,
            reason="правка",
            perms={"finance.adjust_closed"},
            adjust_reason="поправка",
        )
    back = one(order)
    assert back.status == "planned"
    assert any("closed_period_adjustment" in a.changes for a in audit_of(company, back))


def test_recognition_in_closed_period_is_rejected(company):
    order, ids = planned_order(company)
    trip = new_trip(company, ids)
    with time_machine.travel(datetime(2026, 7, 15, 10, 0, tzinfo=dt_tz.utc), tick=False):
        periods.close_period(company, 2026, 5, first_user(company))
    with tenant_context(company.id):
        from apps.finance.tests.p2_helpers import status

        Trip.objects.filter(pk=trip.pk).update(
            status=status(company, "COMPLETED"), completed_at=datetime(2026, 5, 5, tzinfo=dt_tz.utc)
        )
        with pytest.raises(FinanceError) as exc:
            inc.recognize_order_income(order)
    assert code(exc) == "period_closed"
    assert one(order).status == "planned"


def test_isolation_between_companies(company, make_company):
    other, _, _ = make_company("Other")
    order, ids = planned_order(company)
    enable_new(other)
    other_order, other_ids = order_with_cargos(other, 1, client_rate=D("5"))
    move(company, new_trip(company, ids), "COMPLETED", T1)
    assert one(order).status == "recognized"
    assert one(other_order).status == "planned"
    with tenant_context(other.id):
        assert Income.objects.filter(order=order).count() == 0
        assert Income.objects.filter(status="recognized").count() == 0


# --- услуги ---


def test_service_flow_and_trip_completion_does_not_recognize(company):
    order, ids = planned_order(company)
    user = first_user(company)
    service = inc.plan_service(order, "Страховка", "Прочее", "250.555", user)
    assert (
        service.kind == "service" and service.status == "planned" and service.amount == D("250.56")
    )
    with pytest.raises(FinanceError) as exc:  # confirm без delivered
        inc.confirm_service(service, user)
    assert code(exc) == "service_not_delivered"
    move(company, new_trip(company, ids), "COMPLETED", T1)
    assert reload(service).status == "planned"  # завершение рейса услугу не признаёт
    delivered = inc.mark_service_delivered(service, date(2026, 6, 20), user, set())
    assert delivered.delivered_on == date(2026, 6, 20) and delivered.status == "planned"
    done = inc.confirm_service(delivered, user)
    assert done.status == "recognized" and done.recognized_on == date(2026, 6, 20)
    assert done.recognition_basis == "service_confirmed" and done.confirmed_by_id == user.pk
    assert done.confirmed_at is not None and done.base_amount == D("250.56")
    assert inc.confirm_service(done, user).pk == done.pk  # идемпотентно
    with pytest.raises(FinanceError):
        inc.mark_service_delivered(done, date(2026, 6, 21), user, set())
    with pytest.raises(FinanceError) as exc:  # услуга не рейс
        inc.void_income(done, "x", user)
    assert code(exc) == "income_not_planned"


def test_service_delivery_date_rules(company):
    order, _ = planned_order(company)
    user = first_user(company)
    service = inc.plan_service(order, "Хранение", "", "10", user)
    CompanyFinancialSettings.all_objects.filter(company=company).update(allow_backdating=False)
    with time_machine.travel(T3, tick=False):
        with pytest.raises(FinanceError) as exc:
            inc.mark_service_delivered(service, date(2026, 6, 1), user, set())
        assert code(exc) == "backdating_forbidden"
        inc.mark_service_delivered(service, date(2026, 6, 1), user, {"finance.backdate"})
    with pytest.raises(FinanceError) as exc:
        inc.plan_service(order, "  ", "", "1", user)
    assert code(exc) == "title_required"
    with pytest.raises(FinanceError):
        inc.plan_service(order, "x", "", "-1", user)


def test_mark_delivered_in_closed_period(company):
    order, _ = planned_order(company)
    user = first_user(company)
    service = inc.plan_service(order, "Хранение", "", "10", user)
    with time_machine.travel(datetime(2026, 7, 15, 10, 0, tzinfo=dt_tz.utc), tick=False):
        periods.close_period(company, 2026, 5, user)
        with pytest.raises(FinanceError) as exc:
            inc.mark_service_delivered(service, date(2026, 5, 3), user, set())
        assert code(exc) == "period_closed"
        with pytest.raises(FinanceError) as exc:
            inc.mark_service_delivered(service, date(2026, 5, 3), user, {"finance.adjust_closed"})
        assert code(exc) == "period_reason_required"
        inc.mark_service_delivered(
            service, date(2026, 5, 3), user, {"finance.adjust_closed"}, "поздняя отметка"
        )


# --- корректировка и аннулирование ---


def recognized_income(company, amount="1000.00"):
    order, ids = planned_order(company, rate_=amount)
    rate(company, "USD", "480")
    move(company, new_trip(company, ids), "COMPLETED", T1)
    return order, one(order)


def test_adjust_recognized_income_keeps_rate_and_recalculates_base(company):
    order, income = recognized_income(company)
    user = first_user(company)
    with tenant_context(company.id):
        from apps.finance.fx import fx_snapshot

        Income.objects.filter(pk=income.pk).update(
            currency=cur(company, "USD"),
            **fx_snapshot(company, D("1000"), cur(company, "USD"), date(2026, 6, 1)),
        )
    before = reload(income)
    assert before.fx_rate == D("480") and before.base_amount == D("480000.00")
    for reason in ("", None, "  "):
        with pytest.raises(FinanceError) as exc:
            inc.adjust_recognized_income(before, "900", user=user, reason=reason)
        assert code(exc) == "reason_required"
    rate(company, "USD", "999", date(2026, 6, 2))  # новый курс не влияет на снимок
    done = inc.adjust_recognized_income(before, "900.10", user=user, reason="скидка")
    assert (
        done.amount == D("900.10")
        and done.fx_rate == D("480")
        and done.base_amount == D("432048.00")
    )
    assert len(freight(order)) == 1
    last = audit_of(company, done)[-1]
    assert (
        last.changes["reason"] == "скидка" and last.changes["adjustment"][0]["amount"] == "1000.00"
    )
    with pytest.raises(FinanceError):
        inc.adjust_recognized_income(before, "-1", user=user, reason="x")


def test_adjust_requires_recognized_and_period_rules(company):
    order, income = recognized_income(company)
    user = first_user(company)
    planned = inc.plan_service(order, "x", "", "1", user)
    with pytest.raises(FinanceError) as exc:
        inc.adjust_recognized_income(planned, "2", user=user, reason="r")
    assert code(exc) == "income_not_recognized"
    with time_machine.travel(datetime(2026, 7, 15, 10, 0, tzinfo=dt_tz.utc), tick=False):
        periods.close_period(company, 2026, 6, user)
        with pytest.raises(FinanceError) as exc:
            inc.adjust_recognized_income(income, "5", user=user, reason="r")
        assert code(exc) == "period_closed"
        done = inc.adjust_recognized_income(income, "5", user=user, reason="r", can_adjust=True)
    assert done.amount == D("5.00")
    assert "closed_period_adjustment" in audit_of(company, done)[-1].changes


def test_void_only_planned(company):
    order, income = recognized_income(company)
    user = first_user(company)
    with pytest.raises(FinanceError) as exc:
        inc.void_income(income, "x", user)
    assert code(exc) == "income_not_planned"
    planned = inc.plan_service(order, "x", "", "1", user)
    with pytest.raises(FinanceError):
        inc.void_income(planned, " ", user)
    voided = inc.void_income(planned, "ошибочно", user)
    assert voided.status == "void" and voided.void_reason == "ошибочно"
    with pytest.raises(FinanceError):
        inc.void_income(voided, "ещё", user)


def test_voided_freight_allows_new_planned_one(company):
    order, _ = planned_order(company)
    user = first_user(company)
    first = one(order)
    inc.void_income(first, "пересоздать", user)
    with tenant_context(company.id):
        again = inc.sync_planned_freight(order)
    assert again.pk != first.pk and again.status == "planned"
    with tenant_context(company.id):
        assert Income.objects.filter(order=order, kind="freight").count() == 2


def test_hooks_helper_unused_import_guard():
    assert hooks and create_order and make_client
