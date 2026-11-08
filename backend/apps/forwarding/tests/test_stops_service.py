"""Этап 1.5-B1: остановки маршрута груза (сервис, ограничения БД)."""

from datetime import datetime
from datetime import timezone as dt_tz

import pytest
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError

from apps.core.models import Membership
from apps.core.tenancy import tenant_context
from apps.forwarding.consignments import services as stops
from apps.forwarding.models import Consignment, ConsignmentPoint, ConsignmentStop
from apps.forwarding.orders.services import create_order
from apps.forwarding.tests.test_orders import make_client

pytestmark = pytest.mark.django_db

T = datetime(2026, 6, 2, 9, 0, tzinfo=dt_tz.utc)


def stop(kind, city, **extra):
    return {"kind": kind, "window_from": T, "city": city, **extra}


def route(*cities_kinds):
    return [stop(kind, city) for kind, city in cities_kinds]


THREE = [("load", "Астана"), ("transit", "Караганда"), ("unload", "Алматы")]


def make_cargo(company, items=None, **extra):
    """Груз заказа с маршрутом из stops (по умолчанию - три остановки)."""
    client = make_client(company)
    with tenant_context(company.id):
        user = Membership.objects.filter(company=company).first().user
        order = create_order(
            {
                "client": client,
                "consignments": [
                    {
                        "name": "Груз",
                        "weight_kg": 1000,
                        "volume_m3": 10,
                        "pallets": 4,
                        "stops": items if items is not None else route(*THREE),
                        **extra,
                    }
                ],
            },
            user,
        )
        return Consignment.objects.get(order=order)


def cities(consignment):
    return [(p.seq, p.kind, p.city) for p in stops.stops_of(consignment)]


def test_alias_is_the_same_model():
    assert ConsignmentStop is ConsignmentPoint
    assert ConsignmentPoint._meta.db_table == "forwarding_consignmentpoint"


def test_create_with_three_stops_sets_sequence(company):
    cons = make_cargo(company)
    with tenant_context(company.id):
        assert cities(cons) == [
            (1, "load", "Астана"),
            (2, "transit", "Караганда"),
            (3, "unload", "Алматы"),
        ]
        assert {p.status for p in cons.points.all()} == {"planned"}


def test_legacy_points_create_load_first_even_if_order_reversed(company):
    client = make_client(company)
    with tenant_context(company.id):
        user = Membership.objects.filter(company=company).first().user
        order = create_order(
            {
                "client": client,
                "consignments": [
                    {
                        "name": "Старый",
                        "weight_kg": 1,
                        "volume_m3": 1,
                        "points": [stop("unload", "Б"), stop("load", "А")],
                    }
                ],
            },
            user,
        )
        cons = Consignment.objects.get(order=order)
        assert cities(cons) == [(1, "load", "А"), (2, "unload", "Б")]


@pytest.mark.parametrize(
    "items",
    [
        [],
        [("load", "A")],
        [("unload", "A"), ("load", "B")],  # начинается не с погрузки
        [("load", "A"), ("transit", "B")],  # заканчивается не выгрузкой
        [("transit", "A"), ("unload", "B")],
    ],
)
def test_route_must_start_with_load_and_end_with_unload(company, items):
    with pytest.raises(ValidationError):
        make_cargo(company, route(*items))


def test_multiple_loads_and_unloads_are_allowed(company):
    cons = make_cargo(
        company,
        route(
            ("load", "A"), ("load", "B"), ("customs", "Граница"), ("unload", "C"), ("unload", "D")
        ),
    )
    with tenant_context(company.id):
        assert [p.seq for p in stops.stops_of(cons)] == [1, 2, 3, 4, 5]
        edges = stops.stops_of(cons)
        assert stops.first_load(edges).city == "A" and stops.last_unload(edges).city == "D"


def test_window_order_is_checked(company):
    bad = route(*THREE)
    bad[1]["window_to"] = datetime(2026, 6, 1, tzinfo=dt_tz.utc)
    with pytest.raises(ValidationError):
        make_cargo(company, bad)


def test_shares_cannot_exceed_consignment(company):
    bad = route(*THREE)
    bad[1]["weight_kg"] = 1001
    with pytest.raises(ValidationError):
        make_cargo(company, bad)
    ok = route(*THREE)
    ok[1].update(weight_kg=400, volume_m3=3, pallets=2)
    cons = make_cargo(company, ok)
    with tenant_context(company.id):
        mid = stops.stops_of(cons)[1]
        assert (mid.weight_kg, mid.pallets) == (400, 2)
        assert stops.stops_of(cons)[0].weight_kg is None  # null = весь груз


def test_db_constraints(company):
    cons = make_cargo(company)
    with tenant_context(company.id):
        first = stops.stops_of(cons)[0]
        with pytest.raises(IntegrityError), transaction.atomic():
            ConsignmentPoint.objects.filter(pk=first.pk).update(seq=2)  # (груз, seq) уникален
        with pytest.raises(IntegrityError), transaction.atomic():
            ConsignmentPoint.objects.filter(pk=first.pk).update(seq=0)
        with pytest.raises(IntegrityError), transaction.atomic():
            ConsignmentPoint.objects.filter(pk=first.pk).update(status="lost")
        with pytest.raises(IntegrityError), transaction.atomic():
            ConsignmentPoint.objects.filter(pk=first.pk).update(weight_kg=-1)
        # вид не уникален: вторая погрузка допустима
        ConsignmentPoint.objects.create(consignment=cons, kind="load", window_from=T, city="X")


def test_replace_keeps_ids_and_renumbers_on_insert(company):
    cons = make_cargo(company)
    with tenant_context(company.id):
        a, b, c = stops.stops_of(cons)
        changed = stops.replace_stops(
            cons,
            [
                {"id": a.pk},
                stop("transfer", "Склад"),
                {"id": b.pk, "city": "Караганда-2"},
                {"id": c.pk},
            ],
        )
        assert changed
        got = stops.stops_of(cons)
        assert [(p.seq, p.kind, p.city) for p in got] == [
            (1, "load", "Астана"),
            (2, "transfer", "Склад"),
            (3, "transit", "Караганда-2"),
            (4, "unload", "Алматы"),
        ]
        assert [p.pk for p in got if p.pk in (a.pk, b.pk, c.pk)] == [a.pk, b.pk, c.pk]


def test_replace_reorders_and_deletes(company):
    cons = make_cargo(
        company, route(("load", "A"), ("transit", "B"), ("transit", "C"), ("unload", "D"))
    )
    with tenant_context(company.id):
        a, b, c, d = stops.stops_of(cons)
        stops.replace_stops(cons, [{"id": a.pk}, {"id": c.pk}, {"id": b.pk}, {"id": d.pk}])
        assert [p.city for p in stops.stops_of(cons)] == ["A", "C", "B", "D"]
        stops.replace_stops(cons, [{"id": a.pk}, {"id": d.pk}])  # B и C удалены
        assert [(p.seq, p.city) for p in stops.stops_of(cons)] == [(1, "A"), (2, "D")]
        assert not stops.replace_stops(cons, [{"id": a.pk}, {"id": d.pk}])  # без изменений


def test_replace_validates_route_and_foreign_ids(company):
    cons = make_cargo(company)
    other = make_cargo(company)
    with tenant_context(company.id):
        a, b, c = stops.stops_of(cons)
        foreign = stops.stops_of(other)[0]
        with pytest.raises(ValidationError):
            stops.replace_stops(cons, [{"id": b.pk}, {"id": a.pk}, {"id": c.pk}])  # не с погрузки
        with pytest.raises(ValidationError):
            stops.replace_stops(cons, [{"id": a.pk}, {"id": foreign.pk}, {"id": c.pk}])
        with pytest.raises(ValidationError):
            stops.replace_stops(cons, [{"id": a.pk}, {"id": a.pk}, {"id": c.pk}])
        with pytest.raises(ValidationError):
            stops.replace_stops(cons, [{"id": a.pk}, {"kind": "transit"}, {"id": c.pk}])
        assert [p.pk for p in stops.stops_of(cons)] == [a.pk, b.pk, c.pk]  # ничего не изменилось


def test_add_remove_move_keep_sequence_dense(company):
    cons = make_cargo(company)
    with tenant_context(company.id):
        new = stops.add_stop(cons, stop("customs", "Граница"), position=2)
        assert [(p.seq, p.city) for p in stops.stops_of(cons)] == [
            (1, "Астана"),
            (2, "Граница"),
            (3, "Караганда"),
            (4, "Алматы"),
        ]
        stops.move_stop(new, 3)
        assert [p.city for p in stops.stops_of(cons)] == [
            "Астана",
            "Караганда",
            "Граница",
            "Алматы",
        ]
        with pytest.raises(ValidationError):
            stops.move_stop(new, 4)  # маршрут не может заканчиваться таможней
        stops.remove_stop(new)
        assert [(p.seq, p.city) for p in stops.stops_of(cons)] == [
            (1, "Астана"),
            (2, "Караганда"),
            (3, "Алматы"),
        ]
        last = stops.stops_of(cons)[-1]
        with pytest.raises(ValidationError):
            stops.remove_stop(last)  # маршрут остался бы без выгрузки в конце
        assert len(stops.stops_of(cons)) == 3


def test_protected_stop_cannot_be_deleted(company, monkeypatch):
    """Остановка, на которую что-то ссылается (PROTECT), не удаляется: понятная ошибка."""
    cons = make_cargo(company)
    with tenant_context(company.id):
        mid = stops.stops_of(cons)[1]
        from django.db.models import ProtectedError

        def boom(self, *a, **k):
            raise ProtectedError("защищено", {self})

        monkeypatch.setattr(ConsignmentPoint, "delete", boom)
        with pytest.raises(ValidationError) as err:
            stops.remove_stop(mid)
        assert "участки" in str(err.value.detail)
        with pytest.raises(ValidationError):
            stops.replace_stops(
                cons, [{"id": s.pk} for s in stops.stops_of(cons) if s.pk != mid.pk]
            )


def test_legacy_update_points_changes_edge_stops_of_multistop_route(company):
    cons = make_cargo(company)
    with tenant_context(company.id):
        assert stops.update_points(
            cons, [{"kind": "load", "city": "Новая погрузка"}, {"kind": "unload"}]
        )
        got = stops.stops_of(cons)
        assert [p.city for p in got] == ["Новая погрузка", "Караганда", "Алматы"]
        assert not stops.update_points(cons, [{"kind": "load"}, {"kind": "unload"}])


def test_legacy_update_points_creates_missing_edges(company):
    cons = make_cargo(company, route(("load", "A"), ("transit", "B"), ("unload", "C")))
    with tenant_context(company.id):
        ConsignmentPoint.objects.filter(consignment=cons, kind="unload").delete()
        stops.update_points(
            cons,
            [
                {"kind": "load"},
                {"kind": "unload", "window_from": T, "city": "Z"},
            ],
        )
        assert cities(cons) == [(1, "load", "A"), (2, "transit", "B"), (3, "unload", "Z")]
        ConsignmentPoint.objects.filter(consignment=cons, kind="load").delete()
        ConsignmentPoint.objects.filter(consignment=cons).update(seq=models_f_plus(10))
        stops._renumber(stops.stops_of(cons))
        stops.update_points(
            cons,
            [{"kind": "load", "window_from": T, "city": "Y"}, {"kind": "unload"}],
        )
        assert [(p.seq, p.kind) for p in stops.stops_of(cons)] == [
            (1, "load"),
            (2, "transit"),
            (3, "unload"),
        ]


def models_f_plus(n):
    from django.db.models import F

    return F("seq") + n


def test_both_points_and_stops_rejected_by_service(company):
    client = make_client(company)
    with tenant_context(company.id):
        user = Membership.objects.filter(company=company).first().user
        with pytest.raises(ValidationError):
            create_order(
                {
                    "client": client,
                    "consignments": [
                        {
                            "name": "X",
                            "weight_kg": 1,
                            "volume_m3": 1,
                            "points": route(("load", "A"), ("unload", "B")),
                            "stops": route(("load", "A"), ("unload", "B")),
                        }
                    ],
                },
                user,
            )
