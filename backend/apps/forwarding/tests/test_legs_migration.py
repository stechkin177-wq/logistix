"""Этап 1.5-B1/C1: данные миграций остановок и участков (функции заполнения, идемпотентность)."""

import importlib
from datetime import datetime
from datetime import timezone as dt_tz
from types import SimpleNamespace

import pytest
from django.apps import apps as global_apps
from django.db import connection

from apps.core.handbooks.models import HandbookValue
from apps.core.tenancy import tenant_context
from apps.forwarding.models import ConsignmentPoint, Trip, TripConsignment
from apps.forwarding.tests.test_legs import make_cargos, mk_trip

pytestmark = pytest.mark.django_db

T = datetime(2026, 6, 2, 9, 0, tzinfo=dt_tz.utc)
SHIM = SimpleNamespace(connection=connection)


def migration(name):
    return importlib.import_module(f"apps.forwarding.migrations.{name}")


def run(name):
    migration(name).forwards(global_apps, SHIM)


def set_trip_status(company, trip, code):
    with tenant_context(company.id):
        status = HandbookValue.objects.get(handbook__code="trip_status", code=code)
        Trip.objects.filter(pk=trip.pk).update(status=status)


def legacy_links(company, trip_ids=None):
    """Состояние ДО 0012: у всех участков обнулены остановки, статус planned."""
    with tenant_context(company.id):
        TripConsignment.objects.update(from_stop=None, to_stop=None, status="planned", leg_seq=1)


def test_stops_backfill_sets_seq_load_first_and_is_idempotent(company):
    """Состояние «до B1»: seq у всех точек равен 1 (значение по умолчанию), id выгрузки меньше id
    погрузки; одна точка у груза без пары."""
    _, (c,) = make_cargos(company, stops_per=2)
    _, (single,) = make_cargos(company, stops_per=2)
    with tenant_context(company.id):
        with connection.cursor() as cursor:  # DDL откатывается вместе с тестовой транзакцией
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute(
                "ALTER TABLE forwarding_consignmentpoint DROP CONSTRAINT point_consignment_seq_uniq"
            )
        load = ConsignmentPoint.objects.get(consignment=c, kind="load")
        unload = ConsignmentPoint.objects.get(consignment=c, kind="unload")
        # меняем id местами через пересоздание выгрузки: выгрузка получает меньший id
        ConsignmentPoint.objects.filter(pk=unload.pk).delete()
        early = ConsignmentPoint.objects.create(
            consignment=c, kind="unload", window_from=T, city="Выгрузка", seq=1
        )
        ConsignmentPoint.objects.filter(pk=load.pk).update(seq=1)
        ConsignmentPoint.objects.filter(consignment=single, kind="unload").delete()
        ConsignmentPoint.objects.filter(consignment=single).update(seq=1)
    run("0009_stops_backfill")
    run("0009_stops_backfill")
    with tenant_context(company.id):
        got = {p.kind: p.seq for p in ConsignmentPoint.objects.filter(consignment=c)}
        assert got == {"load": 1, "unload": 2}, got
        assert early.pk != load.pk
        assert [p.seq for p in ConsignmentPoint.objects.filter(consignment=single)] == [1]


def test_legs_backfill_whole_route_status_and_no_points(company):
    # три груза: с маршрутом из трёх остановок, с двумя, и груз без остановок
    _, (c3,) = make_cargos(company, stops_per=3)
    _, (c2,) = make_cargos(company, stops_per=2)
    _, (c0,) = make_cargos(company, stops_per=2)
    with tenant_context(company.id):
        ConsignmentPoint.objects.filter(consignment=c0).delete()
    t_planned = mk_trip(company, [c3.pk, c2.pk])
    t_done = mk_trip(company, [c3.pk])  # перегруз: один груз в двух рейсах
    t_cancelled = mk_trip(company, [c2.pk])
    t_zero = mk_trip(company, [c0.pk])
    set_trip_status(company, t_done, "COMPLETED")
    set_trip_status(company, t_cancelled, "CANCELLED")
    legacy_links(company)

    run("0012_tripconsignment_legs_backfill")

    with tenant_context(company.id):
        by = {(link.trip_id, link.consignment_id): link for link in TripConsignment.objects.all()}
        first3 = ConsignmentPoint.objects.filter(consignment=c3).order_by("seq")
        load3, unload3 = first3.first(), first3.last()
        load2, unload2 = [
            ConsignmentPoint.objects.filter(consignment=c2).order_by("seq")[i] for i in (0, 1)
        ]
        link = by[(t_planned.pk, c3.pk)]
        assert (link.from_stop_id, link.to_stop_id) == (load3.pk, unload3.pk)  # последняя выгрузка
        assert link.status == "planned" and link.leg_seq == 1
        assert by[(t_planned.pk, c2.pk)].from_stop_id == load2.pk
        assert by[(t_done.pk, c3.pk)].status == "done"
        assert (
            by[(t_done.pk, c3.pk)].from_stop_id == load3.pk
        )  # перегруз: оба рейса получили участок
        assert by[(t_cancelled.pk, c2.pk)].status == "cancelled"
        assert by[(t_cancelled.pk, c2.pk)].to_stop_id == unload2.pk
        zero = by[(t_zero.pk, c0.pk)]
        assert zero.from_stop_id is None and zero.to_stop_id is None and zero.status == "planned"
        snapshot = sorted(
            (link.pk, link.from_stop_id, link.to_stop_id, link.status)
            for link in TripConsignment.objects.all()
        )
    run("0012_tripconsignment_legs_backfill")  # повтор не меняет
    with tenant_context(company.id):
        again = sorted(
            (link.pk, link.from_stop_id, link.to_stop_id, link.status)
            for link in TripConsignment.objects.all()
        )
    assert again == snapshot


def test_legs_backfill_is_company_scoped_and_status_by_code_not_name(make_company):
    (ca, _, _), (cb, _, _) = make_company("A"), make_company("B")
    _, (a,) = make_cargos(ca)
    _, (b,) = make_cargos(cb)
    ta, tb = mk_trip(ca, [a.pk]), mk_trip(cb, [b.pk])
    for company, trip in ((ca, ta), (cb, tb)):
        # у компании B «Завершён» переименован: код остаётся системным
        set_trip_status(company, trip, "COMPLETED")
        legacy_links(company)
    with tenant_context(cb.id):
        HandbookValue.objects.filter(handbook__code="trip_status", code="COMPLETED").update(
            name="Сдан клиенту"
        )
    run("0012_tripconsignment_legs_backfill")
    for company, trip in ((ca, ta), (cb, tb)):
        with tenant_context(company.id):
            (link,) = TripConsignment.objects.filter(trip=trip)
            assert link.status == "done" and link.from_stop_id and link.to_stop_id


def test_reverse_guards_refuse_data_the_old_schema_cannot_hold(company):
    _, (c,) = make_cargos(company, stops_per=3)
    # B: промежуточная остановка не помещается в прежнюю схему
    with pytest.raises(RuntimeError, match="forwarding.0008"):
        migration("0008_stops_schema").guard_reverse(global_apps, SHIM)
    # C: два участка одного груза в одном рейсе
    with tenant_context(company.id):
        pts = list(ConsignmentPoint.objects.filter(consignment=c).order_by("seq"))
    from apps.forwarding.tests.test_legs import leg

    mk_trip(company, legs=[leg(c, pts[0], pts[1]), leg(c, pts[1], pts[2])])
    with pytest.raises(RuntimeError, match="forwarding.0011"):
        migration("0011_tripconsignment_legs").guard_reverse(global_apps, SHIM)


def test_reverse_guards_pass_for_legacy_shaped_data(company):
    make_cargos(company, stops_per=2)
    migration("0008_stops_schema").guard_reverse(global_apps, SHIM)
    migration("0011_tripconsignment_legs").guard_reverse(global_apps, SHIM)
