"""Этап 1.5-C: участки перевозки (TripConsignment): правила, покрытие, сервисы рейса."""

from datetime import datetime
from datetime import timezone as dt_tz
from decimal import Decimal as D

import pytest
from rest_framework.exceptions import ValidationError

from apps.core.audit.models import AuditLog
from apps.core.models import Membership
from apps.core.tenancy import tenant_context
from apps.forwarding.consignments import services as stop_services
from apps.forwarding.models import Consignment, Trip, TripConsignment
from apps.forwarding.orders.services import create_order
from apps.forwarding.tests.test_orders import make_client
from apps.forwarding.tests.test_trips import make_carrier
from apps.forwarding.trips import legs as leg_rules
from apps.forwarding.trips.services import change_trip_status, create_trip, reassign

pytestmark = pytest.mark.django_db

T = datetime(2026, 6, 2, 9, 0, tzinfo=dt_tz.utc)


def stop(kind, city):
    return {"kind": kind, "window_from": T, "city": city}


def route(n):
    """load, transit..., unload: n остановок."""
    kinds = ["load"] + ["transit"] * (n - 2) + ["unload"]
    return [stop(k, f"Город {i}") for i, k in enumerate(kinds, start=1)]


def make_cargos(company, stops_per=3, count=1, client=None, weight=1000, **order_extra):
    """Заказ с `count` грузами, у каждого маршрут из `stops_per` остановок."""
    client = client or make_client(company)
    with tenant_context(company.id):
        user = Membership.objects.filter(company=company).first().user
        order = create_order(
            {
                "client": client,
                "consignments": [
                    {
                        "name": f"Груз {i}",
                        "weight_kg": weight,
                        "volume_m3": 10,
                        "pallets": 10,
                        "stops": route(stops_per),
                    }
                    for i in range(count)
                ],
                **order_extra,
            },
            user,
        )
        return order, list(Consignment.objects.filter(order=order).order_by("id"))


def stops_of(company, consignment):
    with tenant_context(company.id):
        return stop_services.stops_of(consignment)


def mk_trip(company, ids=None, legs=None, carrier=True):
    with tenant_context(company.id):
        user = Membership.objects.filter(company=company).first().user
        cr = make_carrier(company, "Перевозчик") if carrier else None
        return create_trip(ids or [], cr.pk if cr else None, {}, user, legs=legs)


def leg(consignment, from_stop, to_stop, **shares):
    return {
        "consignment": consignment.pk,
        "from_stop": from_stop.pk,
        "to_stop": to_stop.pk,
        "shares": shares,
    }


def links(company, trip):
    with tenant_context(company.id):
        return list(
            TripConsignment.objects.filter(trip=trip).order_by("consignment_id", "leg_seq", "id")
        )


def coverage(company, consignment):
    with tenant_context(company.id):
        c = Consignment.objects.get(pk=consignment.pk)
        return leg_rules.route_coverage(c)


def reassign_svc(company, trip, ids=None, legs=None):
    with tenant_context(company.id):
        user = Membership.objects.filter(company=company).first().user
        return reassign(Trip.objects.get(pk=trip.pk), ids or [], user, legs=legs)


def status_svc(company, trip, code):
    with tenant_context(company.id):
        user = Membership.objects.filter(company=company).first().user
        from apps.core.handbooks.models import HandbookValue

        status = HandbookValue.objects.get(handbook__code="trip_status", code=code)
        return change_trip_status(
            Trip.objects.get(pk=trip.pk), status, user, can_revert=True, reason="тест"
        )


def bad(fn, *args, **kwargs):
    with pytest.raises(ValidationError) as err:
        fn(*args, **kwargs)
    return str(err.value.detail)


# --- C1/C3: участок на весь маршрут при создании рейса по consignment_ids ---


def test_consignment_ids_create_whole_route_leg(company):
    _, (c,) = make_cargos(company)
    first, mid, last = stops_of(company, c)
    trip = mk_trip(company, [c.pk])
    (link,) = links(company, trip)
    assert (link.from_stop_id, link.to_stop_id) == (first.pk, last.pk)
    assert (link.leg_seq, link.status) == (1, "planned")
    assert link.weight_kg is None and link.volume_m3 is None and link.pallets is None
    cov = coverage(company, c)
    assert cov["fully_assigned"] and cov["uncovered"] == []
    assert [s["covered"] for s in cov["segments"]] == [True, True]
    # каждый отрезок знает, какой рейс его покрывает
    assert [[t["number"] for t in s["trips"]] for s in cov["segments"]] == [[trip.number]] * 2
    assert cov["segments"][0]["trips"][0]["status"] == "planned"


def test_segment_lists_a_trip_once_even_with_two_legs_in_it(company):
    """Два участка одного рейса с долями перекрываются на отрезке 2-3: рейс в отрезке один раз."""
    _, (c,) = make_cargos(company, stops_per=4)
    s1, s2, s3, s4 = stops_of(company, c)
    trip = mk_trip(
        company, legs=[leg(c, s1, s3, weight_kg=D("300")), leg(c, s2, s4, weight_kg=D("300"))]
    )
    segment = coverage(company, c)["segments"][1]  # отрезок 2-3 покрыт обоими участками
    assert len(segment["legs"]) == 2
    assert [t["id"] for t in segment["trips"]] == [trip.pk]


def test_two_trips_on_different_legs_is_a_transfer(company):
    """Основной сценарий: один груз на двух рейсах на разных участках."""
    _, (c,) = make_cargos(company)
    first, mid, last = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, first, mid)])
    t2 = mk_trip(company, legs=[leg(c, mid, last)])
    assert coverage(company, c)["fully_assigned"]
    # отмена второго рейса снимает покрытие второго отрезка
    status_svc(company, t2, "CANCELLED")
    cov = coverage(company, c)
    assert not cov["fully_assigned"]
    assert [(s["from_stop"], s["to_stop"]) for s in cov["uncovered"]] == [(mid.pk, last.pk)]
    assert [link.status for link in links(company, t2)] == ["cancelled"]
    assert [link.status for link in links(company, t1)] == ["planned"]


def test_uncovered_segment_when_only_first_leg_assigned(company):
    _, (c,) = make_cargos(company, stops_per=4)
    s1, s2, s3, s4 = stops_of(company, c)
    mk_trip(company, legs=[leg(c, s1, s2)])
    cov = coverage(company, c)
    assert not cov["fully_assigned"]
    assert [(s["from_seq"], s["to_seq"], s["covered"]) for s in cov["segments"]] == [
        (1, 2, True),
        (2, 3, False),
        (3, 4, False),
    ]
    assert len(cov["uncovered"]) == 2
    mk_trip(company, legs=[leg(c, s2, s4)])  # leg 2→4 покрывает два отрезка
    assert coverage(company, c)["fully_assigned"]


def test_cargo_without_trips_is_not_assigned(company):
    _, (c,) = make_cargos(company)
    cov = coverage(company, c)
    assert not cov["fully_assigned"] and len(cov["uncovered"]) == 2


# --- C2: правила участков ---


def test_leg_must_go_forward_and_use_stops_of_this_cargo(company):
    _, (c, other) = make_cargos(company, count=2)
    s1, s2, s3 = stops_of(company, c)
    o1, _o2, _o3 = stops_of(company, other)
    assert "вперёд" in bad(mk_trip, company, legs=[leg(c, s2, s1)])
    assert "вперёд" in bad(mk_trip, company, legs=[leg(c, s2, s2)])
    assert "не принадлежит" in bad(mk_trip, company, legs=[leg(c, o1, s3)])
    assert "не найдена" in bad(
        mk_trip, company, legs=[{"consignment": c.pk, "from_stop": 99999999, "to_stop": s3.pk}]
    )
    with tenant_context(company.id):
        assert not TripConsignment.objects.exists()  # ничего не создано


def test_shares_validated_and_summed_per_segment(company):
    _, (c,) = make_cargos(company, weight=1000)
    s1, s2, s3 = stops_of(company, c)
    assert "больше" in bad(mk_trip, company, legs=[leg(c, s1, s3, weight_kg=D("1001"))])
    assert "отрицательной" in bad(mk_trip, company, legs=[leg(c, s1, s3, weight_kg=D("-1"))])
    mk_trip(company, legs=[leg(c, s1, s3, weight_kg=D("400"))])
    mk_trip(company, legs=[leg(c, s1, s3, weight_kg=D("600"))])  # параллельные доли: 400 + 600
    assert "превышает" in bad(mk_trip, company, legs=[leg(c, s2, s3, weight_kg=D("1"))])
    # на отрезке 1→2 тоже занято полностью, а вот доли по другому измерению независимы
    mk_trip(company, legs=[leg(c, s1, s3, pallets=3)])


def test_parallel_shares_by_volume_and_pallets_are_independent_of_weight(company):
    _, (c,) = make_cargos(company)
    s1, s2, s3 = stops_of(company, c)
    mk_trip(company, legs=[leg(c, s1, s3, volume_m3=D("6"), pallets=6)])
    mk_trip(company, legs=[leg(c, s1, s3, volume_m3=D("4"), pallets=4)])
    assert "превышает" in bad(mk_trip, company, legs=[leg(c, s1, s2, pallets=1)])


def test_whole_cargo_leg_excludes_other_trips_on_the_segment(company):
    _, (c,) = make_cargos(company, stops_per=4)
    s1, s2, s3, s4 = stops_of(company, c)
    mk_trip(company, legs=[leg(c, s2, s3)])  # пустая доля = весь груз на отрезке 2→3
    assert "исключает" in bad(mk_trip, company, legs=[leg(c, s1, s4, weight_kg=D("1"))])
    assert "исключает" in bad(mk_trip, company, legs=[leg(c, s2, s3)])
    mk_trip(company, legs=[leg(c, s1, s2), leg(c, s3, s4)])  # соседние отрезки свободны
    assert coverage(company, c)["fully_assigned"]


def test_whole_cargo_leg_excludes_partial_new_leg_and_vice_versa(company):
    _, (c,) = make_cargos(company)
    s1, s2, s3 = stops_of(company, c)
    mk_trip(company, legs=[leg(c, s1, s3, weight_kg=D("100"))])
    assert "исключает" in bad(mk_trip, company, legs=[leg(c, s1, s3)])  # весь груз поверх доли


def test_legacy_whole_route_in_several_trips_still_allowed(company):
    """Старый способ (consignment_ids): перегруз без остановок - один груз в нескольких рейсах."""
    _, (c,) = make_cargos(company)
    mk_trip(company, [c.pk])
    mk_trip(company, [c.pk])
    assert len(coverage(company, c)["segments"][0]["legs"]) == 2


def test_legacy_ids_cannot_overlap_an_explicit_partial_leg(company):
    _, (c,) = make_cargos(company)
    s1, s2, s3 = stops_of(company, c)
    mk_trip(company, legs=[leg(c, s1, s2, weight_kg=D("100"))])
    assert "исключает" in bad(mk_trip, company, [c.pk])


def test_cancelled_legs_do_not_block(company):
    _, (c,) = make_cargos(company)
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s3)])
    assert "исключает" in bad(mk_trip, company, legs=[leg(c, s1, s2)])
    status_svc(company, t1, "CANCELLED")
    t2 = mk_trip(company, legs=[leg(c, s1, s2)])  # освободилось
    assert [link.status for link in links(company, t2)] == ["planned"]
    # вернуть отменённый рейс нельзя: участок пересекается с новым
    assert "пересекаются" in bad(status_svc, company, t1, "PLANNED")
    status_svc(company, t2, "CANCELLED")
    status_svc(company, t1, "PLANNED")  # теперь можно
    assert [link.status for link in links(company, t1)] == ["planned"]


def test_deleted_trip_legs_do_not_count(company):
    _, (c,) = make_cargos(company)
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s3)])
    with tenant_context(company.id):
        Trip.objects.get(pk=t1.pk).delete()  # в корзину
    assert coverage(company, c)["uncovered"]  # рейс в корзине не покрывает маршрут
    mk_trip(company, legs=[leg(c, s1, s3)])


# --- C3: рейс: create / reassign / статусы / сборные ---


def test_two_legs_of_same_cargo_in_one_trip(company):
    _, (c,) = make_cargos(company, stops_per=4)
    s1, s2, s3, s4 = stops_of(company, c)
    trip = mk_trip(company, legs=[leg(c, s3, s4), leg(c, s1, s2)])
    got = links(company, trip)
    assert [(link.from_stop_id, link.leg_seq) for link in got] == [(s1.pk, 1), (s3.pk, 2)]
    assert not trip.is_consolidated
    assert "дважды" in bad(mk_trip, company, legs=[leg(c, s1, s2), leg(c, s1, s2)])


def test_ids_and_legs_combine(company):
    _, (a, b) = make_cargos(company, count=2)
    a1, a2, a3 = stops_of(company, a)
    trip = mk_trip(company, [b.pk], legs=[leg(a, a1, a2)])
    got = {link.consignment_id: link for link in links(company, trip)}
    assert set(got) == {a.pk, b.pk}
    assert got[a.pk].to_stop_id == a2.pk  # явный участок
    assert got[b.pk].to_stop_id == stops_of(company, b)[-1].pk  # весь маршрут


def test_consolidated_follows_orders_of_legs(company):
    o1, (c1,) = make_cargos(company)
    o2, (c2,) = make_cargos(company)
    trip = mk_trip(
        company, legs=[leg(c1, *stops_of(company, c1)[:2]), leg(c2, *stops_of(company, c2)[:2])]
    )
    assert trip.is_consolidated and trip.number.startswith("C")
    number = trip.number
    after = reassign_svc(company, trip, [c1.pk])
    assert not after.is_consolidated and after.number == number  # номер не меняется
    after = reassign_svc(company, trip, [c1.pk, c2.pk])
    assert after.is_consolidated and after.number == number


def test_reassign_with_legs_narrows_and_expands(company):
    _, (c,) = make_cargos(company)
    s1, s2, s3 = stops_of(company, c)
    trip = mk_trip(company, [c.pk])
    assert coverage(company, c)["fully_assigned"]
    reassign_svc(company, trip, [c.pk], legs=[leg(c, s1, s2)])  # сузили
    (link,) = links(company, trip)
    assert (link.from_stop_id, link.to_stop_id) == (s1.pk, s2.pk)
    cov = coverage(company, c)
    assert [s["covered"] for s in cov["segments"]] == [True, False]
    reassign_svc(company, trip, [c.pk], legs=[leg(c, s1, s3, weight_kg=D("500"))])  # расширили
    (link,) = links(company, trip)
    assert (link.to_stop_id, link.weight_kg) == (s3.pk, D("500"))
    assert coverage(company, c)["fully_assigned"]
    with tenant_context(company.id):
        changes = [
            a.changes for a in AuditLog.objects.filter(object_type="forwarding.trip").order_by("id")
        ]
    assert "legs" in changes[-1] and "consignments" not in changes[-1]


def test_reassign_without_legs_keeps_existing_legs(company):
    _, (c,) = make_cargos(company)
    s1, s2, s3 = stops_of(company, c)
    trip = mk_trip(company, legs=[leg(c, s1, s2)])
    reassign_svc(company, trip, [c.pk])  # старый клиент: набор не менялся
    (link,) = links(company, trip)
    assert link.to_stop_id == s2.pk
    with tenant_context(company.id):
        assert AuditLog.objects.filter(object_type="forwarding.trip", action="update").count() == 0


def test_reassign_moves_leg_between_trips_transfer(company):
    """Груз ехал целиком в рейсе 1; делим: рейс 1 - до промежуточной, рейс 2 - дальше."""
    _, (c,) = make_cargos(company)
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, [c.pk])
    assert "исключает" in bad(mk_trip, company, legs=[leg(c, s2, s3)])  # пока рейс 1 держит всё
    reassign_svc(company, t1, [c.pk], legs=[leg(c, s1, s2)])
    t2 = mk_trip(company, legs=[leg(c, s2, s3)])
    assert coverage(company, c)["fully_assigned"]
    assert len({link.trip_id for link in links(company, t1) + links(company, t2)}) == 2


def test_reassign_conflict_rolls_back(company):
    _, (c,) = make_cargos(company)
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    t2 = mk_trip(company, legs=[leg(c, s2, s3)])
    assert "исключает" in bad(reassign_svc, company, t2, [c.pk], legs=[leg(c, s1, s3)])
    (link,) = links(company, t2)
    assert link.from_stop_id == s2.pk  # прежний участок на месте
    assert links(company, t1)


def test_trip_status_drives_leg_status(company):
    _, (c,) = make_cargos(company)
    s1, s2, s3 = stops_of(company, c)
    trip = mk_trip(company, legs=[leg(c, s1, s2), leg(c, s2, s3)])
    assert {link.status for link in links(company, trip)} == {"planned"}
    status_svc(company, trip, "IN_PROGRESS")
    assert {link.status for link in links(company, trip)} == {"in_progress"}
    status_svc(company, trip, "COMPLETED")
    assert {link.status for link in links(company, trip)} == {"done"}
    assert coverage(company, c)["fully_assigned"]  # выполненные участки покрывают маршрут
    status_svc(company, trip, "PLANNED")
    assert {link.status for link in links(company, trip)} == {"planned"}


def test_cancelling_trip_cancels_only_its_own_legs(company):
    _, (c,) = make_cargos(company)
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    t2 = mk_trip(company, legs=[leg(c, s2, s3)])
    status_svc(company, t1, "CANCELLED")
    assert [link.status for link in links(company, t1)] == ["cancelled"]
    assert [link.status for link in links(company, t2)] == ["planned"]
    cov = coverage(company, c)
    assert [s["covered"] for s in cov["segments"]] == [False, True]


def test_new_leg_on_cancelled_trip_is_cancelled_and_not_validated(company):
    _, (c,) = make_cargos(company)
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s3)])
    status_svc(company, t1, "CANCELLED")
    t2 = mk_trip(company, legs=[leg(c, s1, s3)])
    status_svc(company, t2, "CANCELLED")
    reassign_svc(company, t2, [c.pk], legs=[leg(c, s1, s2)])  # на отменённом рейсе - без проверок
    assert [link.status for link in links(company, t2)] == ["cancelled"]


# --- защита остановок ---


def test_stop_with_leg_cannot_be_deleted(company):
    _, (c,) = make_cargos(company)
    s1, s2, s3 = stops_of(company, c)
    trip = mk_trip(company, legs=[leg(c, s1, s2), leg(c, s2, s3)])
    with tenant_context(company.id):
        cons = Consignment.objects.get(pk=c.pk)
        message = bad(stop_services.remove_stop, stop_services.stops_of(cons)[1])
        assert "участки" in message
        message = bad(
            stop_services.replace_stops,
            cons,
            [{"id": s1.pk}, {"id": s3.pk}],
        )
        assert "участки" in message
        assert len(stop_services.stops_of(cons)) == 3
    # защита действует и для участков отменённых рейсов (запись участка остаётся в истории)
    status_svc(company, trip, "CANCELLED")
    with tenant_context(company.id):
        cons = Consignment.objects.get(pk=c.pk)
        assert "участки" in bad(stop_services.remove_stop, stop_services.stops_of(cons)[1])
