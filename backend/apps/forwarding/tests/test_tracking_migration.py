"""Этап 1.5-D1: заполнение location_status у существующих грузов (миграция 0014)."""

import importlib

import pytest
from django.apps import apps as django_apps
from django.db import connection

from apps.core.tenancy import tenant_context
from apps.forwarding.models import Consignment, TripConsignment
from apps.forwarding.tests.test_legs import leg, mk_trip, stops_of
from apps.forwarding.tests.test_legs import status_svc as set_trip_status
from apps.forwarding.tests.test_tracking import location, make_route_cargo
from apps.forwarding.tracking import services as tr

pytestmark = pytest.mark.django_db
migration = importlib.import_module("apps.forwarding.migrations.0014_location_status_backfill")


def reset(company, c):
    with tenant_context(company.id):
        Consignment.objects.filter(pk=c.pk).update(location_status="planned", current_stop=None)


def test_backfill_matches_service_and_is_idempotent(company, make_company):
    other = make_company("Другая")[0]
    _, c = make_route_cargo(company)
    _, d = make_route_cargo(company, kinds=("load", "unload"))
    _, o = make_route_cargo(other, kinds=("load", "unload"))
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    td = mk_trip(company, [d.pk])
    set_trip_status(company, td, "COMPLETED")
    set_trip_status(company, t1, "IN_PROGRESS")
    with tenant_context(company.id):
        for x in (c, d):
            tr.recompute_location(Consignment.objects.get(pk=x.pk))
    expected = {x.pk: location(company, x) for x in (c, d)}
    assert expected[c.pk][0] == "in_transit" and expected[d.pk][0] == "delivered"
    reset(company, c)
    reset(company, d)
    changed = migration.run_backfill(django_apps, connection)
    assert changed == 2
    assert {x.pk: location(company, x) for x in (c, d)} == expected
    assert location(other, o)[0] == "planned"  # данные другой компании не смешиваются
    assert migration.run_backfill(django_apps, connection) == 0  # повтор ничего не меняет
    with tenant_context(company.id):
        assert TripConsignment.objects.count() == 2  # связи не тронуты
