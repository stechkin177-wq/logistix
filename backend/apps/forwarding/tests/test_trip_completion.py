"""Trip.completed_at и правила выхода из статуса «Завершён» (задача 1.1, блок D)."""

import importlib
from contextlib import contextmanager
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from io import StringIO

import pytest
import time_machine
from django.core.management import CommandError, call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from apps.core.api.auth import issue_tokens
from apps.core.audit.models import AuditLog
from apps.core.models import Membership, Role
from apps.core.tenancy import tenant_context
from apps.forwarding.models import Order, Trip
from apps.forwarding.tests.test_parties import client_with_role
from apps.forwarding.tests.test_trips import (
    TRIPS,
    audit_rows,
    make_cargos,
    new_trip,
    trip_status_id,
    trip_url,
)
from apps.forwarding.trips.services import change_trip_status

pytestmark = pytest.mark.django_db

T0 = datetime(2026, 6, 1, 12, 0, tzinfo=dt_tz.utc)
T1 = T0 + timedelta(hours=5)
T2 = T0 + timedelta(days=2)


def status_url(pk):
    return trip_url(pk, "status/")


def iso(value):
    """Дата-время из ответа API (ISO 8601 с часовым поясом)."""
    return parse_datetime(value)


def st(company, name):
    return trip_status_id(company, name)


def move(api, trip_id, status, **extra):
    return api.post(status_url(trip_id), {"status": status, **extra}, format="json")


def db_trip(company, pk):
    with tenant_context(company.id):
        return Trip.all_objects.select_related("status").get(pk=pk)


@pytest.fixture
def trip(admin_client, company):
    _, ids = make_cargos(company)
    return new_trip(admin_client, ids)


@contextmanager
def api_at(user, company, when):
    """Клиент API и «текущее время» when; токен выдаётся внутри того же времени."""
    with time_machine.travel(when, tick=False):
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user, company.id)['access']}")
        yield api


def complete(user, company, trip, when=T1):
    with api_at(user, company, when) as api:
        r = move(api, trip["id"], st(company, "Завершён"))
    assert r.status_code == 200, r.content
    return r


# --- completed_at при завершении ---


def test_new_trip_has_no_completed_at(trip):
    assert trip["completed_at"] is None


def test_entering_completed_sets_completed_at_once(admin_client, admin_user, company, trip):
    r = complete(admin_user, company, trip)
    assert iso(r.data["completed_at"]) == T1
    assert db_trip(company, trip["id"]).completed_at == T1
    got = admin_client.get(trip_url(trip["id"])).data
    assert iso(got["completed_at"]) == T1
    assert iso(admin_client.get(TRIPS).data["results"][0]["completed_at"]) == T1
    # повтор того же статуса запрещён и completed_at не трогает
    with api_at(admin_user, company, T2) as later:
        again = move(later, trip["id"], st(company, "Завершён"))
    assert again.status_code == 400
    assert db_trip(company, trip["id"]).completed_at == T1


def test_other_statuses_do_not_set_completed_at(admin_client, admin_user, company, trip):
    for name in ("Ожидает выезда", "В пути", "Выгрузка", "Отменён", "Планируется"):
        assert move(admin_client, trip["id"], st(company, name)).status_code == 200
        assert db_trip(company, trip["id"]).completed_at is None, name


def test_existing_completed_at_is_not_overwritten_on_entering(company, trip):
    """Если completed_at уже есть (например, заполнен backfill), вход в COMPLETED его не меняет."""
    with tenant_context(company.id):
        Trip.objects.filter(pk=trip["id"]).update(completed_at=T0)
        row = Trip.objects.get(pk=trip["id"])
        user = Membership.objects.filter(company=company).first().user
        with time_machine.travel(T2, tick=False):
            done = change_trip_status(row, st_obj(company, "Завершён"), user)
    assert done.completed_at == T0


def st_obj(company, name):
    from apps.forwarding.tests.test_orders import hv

    return hv(company, "trip_status", name)


def test_status_change_is_always_audited(admin_client, admin_user, company, trip):
    complete(admin_user, company, trip)
    rows = audit_rows(company, action="update", object_type="forwarding.trip")
    last = rows[-1]
    assert last.changes["status_id"] == [trip["status"], st(company, "Завершён")]
    assert last.changes["completed_at"] == [None, "2026-06-01T17:00:00Z"]


def test_completed_at_not_accepted_in_requests(admin_client, admin_user, company, trip):
    r = admin_client.patch(
        trip_url(trip["id"]), {"completed_at": "2026-01-01T00:00:00Z"}, format="json"
    )
    assert r.status_code == 400 and "completed_at" in r.data
    _, ids = make_cargos(company)
    r = admin_client.post(
        TRIPS, {"consignments": ids, "completed_at": "2026-01-01T00:00:00Z"}, format="json"
    )
    assert r.status_code == 400 and "completed_at" in r.data
    # и в теле смены статуса поле игнорируется
    r = move(admin_client, trip["id"], st(company, "В пути"), completed_at="2026-01-01T00:00:00Z")
    assert r.status_code == 200 and r.data["completed_at"] is None


# --- выход из COMPLETED ---


def test_leaving_completed_requires_reason(admin_client, admin_user, company, trip):
    complete(admin_user, company, trip)
    for body in ({}, {"reason": ""}, {"reason": "   "}):
        r = move(admin_client, trip["id"], st(company, "В пути"), **body)
        assert r.status_code == 400 and "reason" in r.data, body
    after = db_trip(company, trip["id"])
    assert after.status.code == "COMPLETED" and after.completed_at == T1


def test_leaving_completed_without_permission_is_403(company, trip, admin_client, admin_user):
    complete(admin_user, company, trip)
    _, dispatcher = client_with_role(company, "Диспетчер")  # trips.update есть, revert - нет
    for body in ({}, {"reason": "ошибка"}):
        r = move(dispatcher, trip["id"], st(company, "Отменён"), **body)
        assert r.status_code == 403, (body, r.content)
    after = db_trip(company, trip["id"])
    assert after.status.code == "COMPLETED" and after.completed_at == T1
    # обычные переходы у диспетчера по-прежнему работают
    _, ids = make_cargos(company)
    other = new_trip(admin_client, ids)
    assert move(dispatcher, other["id"], st(company, "В пути")).status_code == 200


def test_leaving_completed_by_admin_clears_completed_at_and_audits(
    admin_client, admin_user, company, trip
):
    complete(admin_user, company, trip)
    r = move(admin_client, trip["id"], st(company, "Отменён"), reason="  Ошибочно закрыт  ")
    assert r.status_code == 200, r.content
    assert r.data["completed_at"] is None and r.data["status_name"] == "Отменён"
    assert db_trip(company, trip["id"]).completed_at is None
    row = audit_rows(company, action="update", object_type="forwarding.trip")[-1]
    assert row.changes["status_id"] == [st(company, "Завершён"), st(company, "Отменён")]
    assert row.changes["completed_at"] == ["2026-06-01T17:00:00Z", None]
    assert row.changes["reason"] == "Ошибочно закрыт"


def test_recompleting_after_revert_sets_new_completed_at(admin_client, admin_user, company, trip):
    complete(admin_user, company, trip)
    move(admin_client, trip["id"], st(company, "В пути"), reason="нужна правка")
    r = complete(admin_user, company, trip, when=T2)
    assert iso(r.data["completed_at"]) == T2
    history = audit_rows(company, action="update", object_type="forwarding.trip")
    assert history[-2].changes["completed_at"] == ["2026-06-01T17:00:00Z", None]  # старое сохранено


def test_cancelling_unfinished_trip_has_no_new_requirements(
    admin_client, admin_user, company, trip
):
    _, dispatcher = client_with_role(company, "Диспетчер")
    orders_before = Order.all_objects.count()
    r = move(dispatcher, trip["id"], st(company, "Отменён"))  # без reason и без нового права
    assert r.status_code == 200 and r.data["completed_at"] is None
    row = audit_rows(company, action="update", object_type="forwarding.trip")[-1]
    assert "reason" not in row.changes and row.changes["status_id"][1] == st(company, "Отменён")
    assert Order.all_objects.count() == orders_before  # отмена ничего не создаёт


def test_service_requires_flag_and_reason(company, trip):
    with tenant_context(company.id):
        row = Trip.objects.get(pk=trip["id"])
        user = Membership.objects.filter(company=company).first().user
        done = change_trip_status(row, st_obj(company, "Завершён"), user)
        assert done.completed_at is not None
        from rest_framework.exceptions import PermissionDenied, ValidationError

        with pytest.raises(PermissionDenied):
            change_trip_status(done, st_obj(company, "В пути"), user, reason="x")
        with pytest.raises(ValidationError):
            change_trip_status(done, st_obj(company, "В пути"), user, can_revert=True)
        back = change_trip_status(
            done, st_obj(company, "В пути"), user, reason="x", can_revert=True
        )
        assert back.completed_at is None


def test_revert_permission_belongs_to_admin_only(company):
    with tenant_context(company.id):
        holders = [r.name for r in Role.objects.all() if "trips.revert_completed" in r.permissions]
    assert holders == ["Администратор"]


def test_permissions_migration_is_idempotent_and_adds_only_to_admin(company):
    mod = importlib.import_module("apps.core.migrations.0012_trips_revert_completed_permission")
    hist = (
        MigrationExecutor(connection)
        .loader.project_state(("core", "0012_trips_revert_completed_permission"))
        .apps
    )
    with tenant_context(company.id):
        admin = Role.objects.get(name="Администратор")
        admin.permissions = [p for p in admin.permissions if p != "trips.revert_completed"]
        admin.save()
        custom = Role.objects.create(name="Свои", permissions=["trips.update"], is_system=False)
    mod.run_backfill(hist)
    mod.run_backfill(hist)
    with tenant_context(company.id):
        admin.refresh_from_db()
        custom.refresh_from_db()
        assert admin.permissions.count("trips.revert_completed") == 1
        assert custom.permissions == ["trips.update"]
        assert "trips.revert_completed" not in Role.objects.get(name="Бухгалтер").permissions


# --- backfill_trip_completed_at ---


def run_backfill_cmd(*args):
    out = StringIO()
    call_command("backfill_trip_completed_at", *args, stdout=out)
    return out.getvalue()


def wipe_completed_at(company, pk):
    with connection.cursor() as cur:
        cur.execute("UPDATE forwarding_trip SET completed_at=NULL WHERE id=%s", [pk])


def make_completed(user, api, company, when):
    _, ids = make_cargos(company)
    t = new_trip(api, ids)
    complete(user, company, t, when=when)
    return t


def test_backfill_uses_last_audit_transition_and_is_idempotent(admin_client, admin_user, company):
    t = make_completed(admin_user, admin_client, company, T1)
    # завершён, возвращён и снова завершён позже: берём последнюю запись перехода
    move(admin_client, t["id"], st(company, "В пути"), reason="правка")
    complete(admin_user, company, t, when=T2)
    wipe_completed_at(company, t["id"])
    other = make_completed(admin_user, admin_client, company, T1)
    wipe_completed_at(company, other["id"])

    out = run_backfill_cmd("--company", str(company.id))
    assert "заполнено 2, требует проверки 0" in out
    with tenant_context(company.id):
        times = {x.pk: x.completed_at for x in Trip.all_objects.all()}
        audit_time = (
            AuditLog.objects.filter(
                object_id=str(t["id"]), changes__status_id__1=st(company, "Завершён")
            )
            .first()
            .created_at
        )
    assert times[other["id"]] == T1 and times[t["id"]] == T2 == audit_time
    again = run_backfill_cmd()
    assert "заполнено 0, требует проверки 0" in again
    assert {x.pk: x.completed_at for x in Trip.all_objects.filter(company=company)} == times


def test_backfill_without_audit_record_goes_to_review_and_is_not_invented(
    admin_client, admin_user, company
):
    t = make_completed(admin_user, admin_client, company, T1)
    wipe_completed_at(company, t["id"])
    with connection.cursor() as cur:
        cur.execute(
            "DELETE FROM core_auditlog "
            "WHERE object_type='forwarding.trip' AND object_id=%s AND action='update'",
            [str(t["id"])],
        )
    # у заказа есть своё completed_at - резервный источник не используется
    with connection.cursor() as cur:
        cur.execute("UPDATE forwarding_order SET completed_at=%s", [T2])
    out = run_backfill_cmd("--company", str(company.id))
    assert "требует проверки 1" in out and f"рейс #{t['id']}" in out
    assert db_trip(company, t["id"]).completed_at is None


def test_backfill_dry_run_writes_nothing(admin_client, admin_user, company):
    t = make_completed(admin_user, admin_client, company, T1)
    wipe_completed_at(company, t["id"])
    out = run_backfill_cmd("--dry-run")
    assert "[dry-run]" in out and "будет заполнено 1" in out
    assert db_trip(company, t["id"]).completed_at is None
    run_backfill_cmd()
    assert db_trip(company, t["id"]).completed_at == T1


def test_backfill_ignores_not_completed_and_filters_by_company(make_company):
    (a, ua, api_a), (b, ub, api_b) = make_company("A"), make_company("B")
    ta, tb = make_completed(ua, api_a, a, T1), make_completed(ub, api_b, b, T1)
    for c, t in ((a, ta), (b, tb)):
        wipe_completed_at(c, t["id"])
    _, ids = make_cargos(a)
    running = new_trip(api_a, ids)
    move(api_a, running["id"], st(a, "В пути"))
    run_backfill_cmd("--company", str(a.id))
    assert db_trip(a, ta["id"]).completed_at == T1
    assert db_trip(b, tb["id"]).completed_at is None  # другая компания не затронута
    assert db_trip(a, running["id"]).completed_at is None


def test_backfill_unknown_company():
    with pytest.raises(CommandError):
        run_backfill_cmd("--company", "999999")


# --- право trips.revert_completed назначается штатно и не привязано к названию роли ---


def test_custom_role_with_revert_permission_can_leave_completed(
    admin_client, admin_user, company, trip
):
    complete(admin_user, company, trip)
    r = admin_client.post(
        "/api/roles/",
        {
            "name": "Старший диспетчер",
            "permissions": ["trips.view", "trips.update", "trips.revert_completed"],
        },
        format="json",
    )
    assert r.status_code == 201, r.content
    _, senior = client_with_role(company, "Старший диспетчер")
    assert move(senior, trip["id"], st(company, "В пути")).status_code == 400  # причина обязательна
    ok = move(senior, trip["id"], st(company, "В пути"), reason="правка данных")
    assert ok.status_code == 200 and ok.data["completed_at"] is None

    # такая же роль без права: 403, статус и completed_at не меняются
    complete(admin_user, company, trip, when=T2)
    admin_client.post(
        "/api/roles/",
        {"name": "Диспетчер-2", "permissions": ["trips.view", "trips.update"]},
        format="json",
    )
    _, plain = client_with_role(company, "Диспетчер-2")
    assert move(plain, trip["id"], st(company, "В пути"), reason="x").status_code == 403
    after = db_trip(company, trip["id"])
    assert after.status.code == "COMPLETED" and after.completed_at == T2


def test_permission_can_be_added_to_role_later_and_takes_effect(
    admin_client, admin_user, company, trip
):
    complete(admin_user, company, trip)
    created = admin_client.post(
        "/api/roles/",
        {"name": "Учётчик", "permissions": ["trips.view", "trips.update"]},
        format="json",
    )
    role_id = created.data["id"]
    _, api = client_with_role(company, "Учётчик")
    assert move(api, trip["id"], st(company, "Отменён"), reason="x").status_code == 403
    patched = admin_client.patch(
        f"/api/roles/{role_id}/",
        {"permissions": ["trips.view", "trips.update", "trips.revert_completed"]},
        format="json",
    )
    assert patched.status_code == 200, patched.content
    _, api2 = client_with_role(company, "Учётчик")  # новый токен с обновлённой ролью
    assert move(api2, trip["id"], st(company, "Отменён"), reason="x").status_code == 200


def test_cannot_grant_revert_permission_higher_than_own(company):
    """Правило «нельзя выдать право выше своих» действует и для нового права."""
    with tenant_context(company.id):
        Role.objects.create(
            name="Кадровик", permissions=["roles.view", "roles.create", "roles.update"]
        )
    _, hr = client_with_role(company, "Кадровик")
    r = hr.post(
        "/api/roles/", {"name": "Тайная", "permissions": ["trips.revert_completed"]}, format="json"
    )
    assert r.status_code in (400, 403)
    with tenant_context(company.id):
        assert not Role.objects.filter(name="Тайная").exists()


# --- backfill не использует Order.completed_at ---


def test_backfill_never_uses_order_completed_at_for_multi_trip_order(
    admin_client, admin_user, company
):
    order, ids = make_cargos(company, 2)
    trips = [new_trip(admin_client, [ids[0]]), new_trip(admin_client, [ids[1]])]
    for t in trips:
        complete(admin_user, company, t, when=T1)
        wipe_completed_at(company, t["id"])
        with connection.cursor() as cur:
            cur.execute(
                "DELETE FROM core_auditlog WHERE object_type='forwarding.trip' "
                "AND object_id=%s AND action='update'",
                [str(t["id"])],
            )
    with connection.cursor() as cur:
        cur.execute("UPDATE forwarding_order SET completed_at=%s WHERE id=%s", [T2, order.pk])
    out = run_backfill_cmd("--company", str(company.id))
    assert "заполнено 0, требует проверки 2" in out
    for t in trips:
        assert f"рейс #{t['id']}" in out and "требует проверки" in out
        assert db_trip(company, t["id"]).completed_at is None


def test_backfill_help_states_order_completed_at_is_not_used():
    from apps.forwarding.management.commands import backfill_trip_completed_at as mod

    assert "Order.completed_at" in mod.Command.help
    assert "Order.completed_at" in mod.__doc__


def test_end_to_end_trip_scenario_via_api(admin_client, admin_user, company):
    """Создание (старый и новый клиент), завершение, повтор, отмена завершения с аудитом."""
    _, ids = make_cargos(company, 3)
    old = new_trip(admin_client, [ids[0]], price="1500.00")  # старый клиент: только price
    assert old["carrier_price"] == old["price"] == "1500.00"
    new = new_trip(admin_client, [ids[1]], carrier_price="2500.00")
    assert new["price"] == "2500.00"
    bad = admin_client.post(
        TRIPS, {"consignments": [ids[2]], "price": "1", "carrier_price": "2"}, format="json"
    )
    assert bad.status_code == 400 and "price" in bad.data

    done = complete(admin_user, company, new)
    first = db_trip(company, new["id"]).completed_at
    assert first == T1 and done.data["carrier_price"] == "2500.00"
    again = move(admin_client, new["id"], st(company, "Завершён"))
    assert again.status_code == 400 and db_trip(company, new["id"]).completed_at == first

    assert move(admin_client, new["id"], st(company, "Отменён")).status_code == 400  # без причины
    ok = move(admin_client, new["id"], st(company, "Отменён"), reason="Ошибка оформления")
    assert ok.status_code == 200 and db_trip(company, new["id"]).completed_at is None
    row = audit_rows(company, action="update", object_type="forwarding.trip")[-1]
    assert row.changes["reason"] == "Ошибка оформления"
    assert row.changes["completed_at"][1] is None and row.changes["completed_at"][0] is not None
