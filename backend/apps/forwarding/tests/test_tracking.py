"""Этап 1.5-D1/D2: передачи груза (CargoTransfer) и события (ConsignmentEvent), местонахождение."""

from datetime import datetime
from datetime import timezone as dt_tz

import pytest
from rest_framework.exceptions import ValidationError

from apps.core.models import Membership
from apps.core.tenancy import tenant_context
from apps.forwarding.models import CargoTransfer, Consignment, ConsignmentEvent, Trip
from apps.forwarding.orders.services import create_order
from apps.forwarding.tests.test_legs import leg, mk_trip, stops_of
from apps.forwarding.tests.test_legs import status_svc as set_trip_status
from apps.forwarding.tests.test_orders import make_client
from apps.forwarding.tests.test_trips import make_carrier
from apps.forwarding.tracking import services as tr
from apps.forwarding.tracking.models import ImmutableRecordError
from apps.forwarding.trips.services import create_trip

pytestmark = pytest.mark.django_db

T = datetime(2026, 6, 2, 9, 0, tzinfo=dt_tz.utc)


def at(hour, day=3):
    return datetime(2026, 6, day, hour, 0, tzinfo=dt_tz.utc)


def make_route_cargo(company, kinds=("load", "transfer", "unload"), weight=1000, **order_extra):
    client = make_client(company)
    stops = [{"kind": k, "window_from": T, "city": f"Город {i}"} for i, k in enumerate(kinds, 1)]
    with tenant_context(company.id):
        user = Membership.objects.filter(company=company).first().user
        order = create_order(
            {
                "client": client,
                "consignments": [
                    {
                        "name": "Груз",
                        "weight_kg": weight,
                        "volume_m3": 10,
                        "pallets": 10,
                        "stops": stops,
                    }
                ],
                **order_extra,
            },
            user,
        )
        return order, Consignment.objects.get(order=order)


def user_of(company):
    return Membership.objects.filter(company=company).first().user


def getc(company, c):
    with tenant_context(company.id):
        return Consignment.objects.get(pk=c.pk)


def gett(company, t):
    with tenant_context(company.id):
        return CargoTransfer.objects.get(pk=t.pk)


def fresh(company, obj):
    with tenant_context(company.id):
        return type(obj).objects.get(pk=obj.pk)


def run(company, fn, *args, **kwargs):
    with tenant_context(company.id):
        return fn(*args, **kwargs)


def bad(company, fn, *args, **kwargs):
    with tenant_context(company.id), pytest.raises(ValidationError) as err:
        fn(*args, **kwargs)
    return str(err.value.detail)


def transfer_data(kind, to_stop, **extra):
    return {"transfer_kind": kind, "to_stop": to_stop, "transferred_at": at(12), **extra}


def initiate(company, c, data, **kw):
    return run(
        company,
        tr.initiate_transfer,
        getc(company, c),
        data,
        user_of(company),
        **kw,
    )


def confirm(company, t):
    return run(company, tr.confirm_transfer, gett(company, t), user_of(company))


def event(company, c, kind, stop, when, **kw):
    return run(
        company,
        tr.record_event,
        getc(company, c),
        kind,
        stop=stop,
        occurred_at=when,
        user=user_of(company),
        **kw,
    )


def location(company, c):
    c = fresh(company, c)
    return c.location_status, c.current_stop_id


# --- передачи ---


def test_transfer_to_storage_without_to_trip_creates_no_fake_trip(company):
    _, c = make_route_cargo(company)
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    t = initiate(company, c, transfer_data("to_storage", s2, from_trip=t1))
    assert t.status == "initiated" and t.to_trip_id is None and t.from_carrier_id == t1.carrier_id
    assert t.carrier_changed is False
    confirm(company, t)
    with tenant_context(company.id):
        assert Trip.objects.count() == 1  # фиктивный рейс не создан
    assert location(company, c) == ("in_storage", s2.pk)


def test_from_storage_with_to_trip_leaves_storage_and_second_leg_assigned(company):
    _, c = make_route_cargo(company)
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    confirm(company, initiate(company, c, transfer_data("to_storage", s2, from_trip=t1)))
    assert location(company, c)[0] == "in_storage"
    t2 = mk_trip(company, legs=[leg(c, s2, s3)])
    run(company, tr.recompute_location, getc(company, c))
    assert location(company, c)[0] != "in_storage"  # исходящий участок назначен
    t = initiate(company, c, transfer_data("from_storage", s2, to_trip=t2))
    assert t.from_trip_id is None and t.to_carrier_id == t2.carrier_id
    confirm(company, t)
    assert [
        x.transfer_kind for x in CargoTransfer.all_objects.filter(consignment=c).order_by("id")
    ] == [
        "to_storage",
        "from_storage",
    ]


def test_to_carrier_changes_carrier_and_between_vehicles_same_carrier(company):
    _, c = make_route_cargo(company)
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    t2 = mk_trip(company, legs=[leg(c, s2, s3)])  # другой перевозчик (mk_trip создаёт нового)
    t = initiate(company, c, transfer_data("to_carrier", s2, from_trip=t1, to_trip=t2))
    assert t.carrier_changed is True and t.to_carrier_id == t2.carrier_id
    assert t.transfer_kind == "to_carrier"


def test_between_vehicles_of_same_carrier_keeps_carrier(company):
    _, c = make_route_cargo(company)
    s1, s2, s3 = stops_of(company, c)
    carrier = make_carrier(company, "Свой")
    with tenant_context(company.id):
        a = create_trip([], carrier.pk, {}, user_of(company), legs=[leg(c, s1, s2)])
        b = create_trip([], carrier.pk, {}, user_of(company), legs=[leg(c, s2, s3)])
    t = initiate(company, c, transfer_data("between_vehicles", s2, from_trip=a, to_trip=b))
    assert t.carrier_changed is False and t.from_carrier_id == t.to_carrier_id == carrier.pk


def test_to_carrier_without_trip_needs_explicit_carrier(company):
    _, c = make_route_cargo(company)
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    assert "to_carrier" in bad(
        company,
        tr.initiate_transfer,
        c,
        transfer_data("to_carrier", s2, from_trip=t1),
        user_of(company),
    )
    other = make_carrier(company, "Принимающий")
    t = initiate(company, c, transfer_data("to_carrier", s2, from_trip=t1, to_carrier=other))
    assert t.to_trip_id is None and t.to_carrier_id == other.pk and t.carrier_changed is True


def test_validation_rules(company, make_company):
    _, c = make_route_cargo(company, kinds=("load", "transfer", "transit", "unload"))
    s1, s2, s3, s4 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    t2 = mk_trip(company, legs=[leg(c, s2, s4)])
    user = user_of(company)

    def err(data):
        return bad(company, tr.initiate_transfer, getc(company, c), data, user)

    assert "to_stop" in err(transfer_data("to_storage", s3, from_trip=t1))  # не transfer
    assert "to_stop" in err({"transfer_kind": "to_storage", "transferred_at": at(1)})
    assert "to_trip" in err(transfer_data("to_storage", s2, from_trip=t1, to_trip=t2))
    assert "from_trip" in err(transfer_data("from_storage", s2, from_trip=t1, to_trip=t2))
    assert "to_trip" in err(transfer_data("from_storage", s2))
    assert "to_trip" in err(transfer_data("between_vehicles", s2, from_trip=t1))
    assert "from_trip" in err(
        transfer_data("to_storage", s2, from_trip=t2)
    )  # t2 не заканчивается на s2
    assert "to_trip" in err(transfer_data("from_storage", s2, to_trip=t1))  # t1 не начинается на s2
    assert "weight_kg" in err(transfer_data("to_storage", s2, from_trip=t1, weight_kg=5000))
    assert "transferred_at" in err({"transfer_kind": "to_storage", "to_stop": s2})
    assert "transfer_kind" in err({"transfer_kind": "x", "to_stop": s2, "transferred_at": at(1)})
    _, other = make_route_cargo(company)
    o1, o2, o3 = stops_of(company, other)
    assert "to_stop" in err(transfer_data("to_storage", o2, from_trip=t1))  # чужая остановка


def test_cancelled_leg_does_not_satisfy_transfer(company):
    _, c = make_route_cargo(company)
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    set_trip_status(company, t1, "CANCELLED")
    assert "from_trip" in bad(
        company,
        tr.initiate_transfer,
        getc(company, c),
        transfer_data("to_storage", s2, from_trip=t1),
        user_of(company),
    )


def test_immutable_after_confirmation_no_delete_and_reversal(company):
    _, c = make_route_cargo(company)
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    t = confirm(company, initiate(company, c, transfer_data("to_storage", s2, from_trip=t1)))
    assert t.confirmed_by_id and t.confirmed_at
    with tenant_context(company.id):
        row = CargoTransfer.objects.get(pk=t.pk)
        row.note = "правка"
        with pytest.raises(ImmutableRecordError):
            row.save()
        with pytest.raises(ImmutableRecordError):
            row.delete()
        with pytest.raises(ImmutableRecordError):
            CargoTransfer.objects.filter(pk=t.pk).first().delete()
    storno = run(
        company,
        tr.reverse_transfer,
        gett(company, t),
        user_of(company),
        note="ошибка",
    )
    assert storno.status == "reversed" and storno.reverses_id == t.pk
    assert fresh(company, t).status == "confirmed"  # исходная не изменилась
    assert location(company, c)[0] != "in_storage"  # эффект снят
    assert "status" in bad(company, tr.reverse_transfer, gett(company, t), user_of(company))
    assert "status" in bad(company, tr.reverse_transfer, gett(company, storno), user_of(company))


def test_confirm_is_idempotent_and_requires_initiated(company):
    _, c = make_route_cargo(company)
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    t = initiate(company, c, transfer_data("to_storage", s2, from_trip=t1))
    confirm(company, t)
    again = confirm(company, t)
    assert again.status == "confirmed"
    with tenant_context(company.id):
        assert ConsignmentEvent.objects.filter(consignment=c, event_type="stored").count() == 1


def test_driver_app_source_initiates_and_is_recorded(company):
    _, c = make_route_cargo(company)
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    t = initiate(company, c, transfer_data("to_storage", s2, from_trip=t1), source="driver_app")
    assert t.source == "driver_app" and t.status == "initiated"
    assert location(company, c)[0] != "in_storage"  # без подтверждения эффекта нет


def test_reverse_initiated_transfer_is_rejection(company):
    _, c = make_route_cargo(company)
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    t = initiate(company, c, transfer_data("to_storage", s2, from_trip=t1))
    run(company, tr.reverse_transfer, gett(company, t), user_of(company))
    assert "status" in bad(company, tr.confirm_transfer, gett(company, t), user_of(company))


# --- события и местонахождение ---


def test_location_status_transitions_through_all_states(company):
    _, c = make_route_cargo(company)
    s1, s2, s3 = stops_of(company, c)
    assert location(company, c) == ("planned", None)
    event(company, c, "arrived", s1, at(8))
    assert location(company, c) == ("at_stop", s1.pk)
    event(company, c, "loaded", s1, at(9))
    event(company, c, "departed", s1, at(10))
    assert location(company, c) == ("in_transit", None)
    event(company, c, "arrived", s2, at(14))
    assert location(company, c) == ("at_stop", s2.pk)
    event(company, c, "stored", s2, at(15))  # событие само по себе хранение не задаёт
    assert location(company, c)[0] == "at_stop"
    event(company, c, "departed", s2, at(16))
    assert location(company, c)[0] == "in_transit"
    event(company, c, "arrived", s3, at(20))
    assert location(company, c) == ("at_stop", s3.pk)
    event(company, c, "delivered", s3, at(21))
    assert location(company, c) == ("delivered", None)
    with tenant_context(company.id):
        last = type(s3).objects.get(pk=s3.pk)
        assert last.status == "done" and last.arrived_at == at(20) and last.done_at == at(21)


def test_event_idempotent_and_validations(company):
    _, c = make_route_cargo(company)
    s1, s2, s3 = stops_of(company, c)
    e1, created = event(company, c, "arrived", s1, at(8))
    e2, again = event(company, c, "arrived", s1, at(8))
    assert created and not again and e1.pk == e2.pk
    with tenant_context(company.id):
        assert ConsignmentEvent.objects.filter(consignment=c).count() == 1
    user = user_of(company)

    def cons():
        return getc(company, c)

    assert "event_type" in bad(company, tr.record_event, cons(), "boom", stop=s1, user=user)
    assert "stop" in bad(company, tr.record_event, cons(), "arrived", user=user)
    assert "stop" in bad(company, tr.record_event, cons(), "delivered", stop=s1, user=user)
    _, other = make_route_cargo(company)
    assert "stop" in bad(
        company, tr.record_event, cons(), "arrived", stop=stops_of(company, other)[0], user=user
    )
    event(company, c, "departed", s1, at(9))
    assert "event_type" in bad(company, tr.record_event, cons(), "skipped", stop=s1, user=user)
    with tenant_context(company.id):
        ev = ConsignmentEvent.objects.first()
        ev.note = "x"
        with pytest.raises(ImmutableRecordError):
            ev.save()
        with pytest.raises(ImmutableRecordError):
            ev.delete()


def test_event_with_leg_derives_stop_and_trip(company):
    _, c = make_route_cargo(company)
    s1, s2, s3 = stops_of(company, c)
    t1 = mk_trip(company, legs=[leg(c, s1, s2)])
    with tenant_context(company.id):
        link = t1.links.get()
    ev, _ = run(
        company, tr.record_event, getc(company, c), "arrived",
        leg=link, occurred_at=at(11), user=user_of(company),
    )  # fmt: skip
    assert ev.stop_id == s2.pk and ev.trip_id == t1.pk and ev.leg_id == link.pk


def test_trip_completion_marks_delivered_for_simple_route(company):
    _, c = make_route_cargo(company, kinds=("load", "unload"))
    t = mk_trip(company, [c.pk])
    assert location(company, c)[0] == "planned"
    set_trip_status(company, t, "COMPLETED")
    run(company, tr.recompute_location, getc(company, c))
    assert location(company, c)[0] == "delivered"


def test_company_isolation(company, make_company):
    other_company = make_company("Другая")[0]
    _, c = make_route_cargo(company)
    s1, s2, s3 = stops_of(company, c)
    event(company, c, "arrived", s1, at(8))
    with tenant_context(other_company.id):
        assert ConsignmentEvent.objects.count() == 0 and CargoTransfer.objects.count() == 0
