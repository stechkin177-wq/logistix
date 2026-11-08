"""Расчёт расхода топлива между полными заправками: сценарии и пограничные случаи."""

from datetime import datetime, timedelta
from datetime import timezone as tz
from decimal import Decimal

import pytest

from apps.core.tenancy import tenant_context
from apps.fleet import services
from apps.fleet.models import FuelFill, Vehicle

pytestmark = pytest.mark.django_db

T0 = datetime(2026, 6, 1, 8, 0, tzinfo=tz.utc)


@pytest.fixture
def ctx(company):
    with tenant_context(company.id):
        yield Vehicle.objects.create(plate="T1")


def fills(vehicle, *rows):
    """rows: (литры, пробег|None, полный) в хронологическом порядке."""
    for i, (liters, km, full) in enumerate(rows):
        FuelFill.objects.create(
            vehicle=vehicle,
            filled_at=T0 + timedelta(days=i),
            liters=Decimal(liters),
            odometer_km=km,
            full_tank=full,
        )
    return services.fuel_stats(vehicle)


def test_partial_fill_without_odometer_counts_liters(ctx):
    # полный (якорь) -> частичная БЕЗ пробега -> полный с пробегом
    stats = fills(ctx, ("300", 10000, True), ("100", None, False), ("130", 10800, True))
    assert stats["average_l_per_100km"] == Decimal("28.75")  # (100 + 130) / 800 * 100
    assert stats["distance_km"] == 800 and stats["liters"] == Decimal("230")
    assert len(stats["segments"]) == 1 and len(stats["no_odometer"]) == 1


def test_partial_with_odometer_gives_same_result_but_is_not_an_anchor(ctx):
    stats = fills(ctx, ("300", 10000, True), ("100", 10400, False), ("130", 10800, True))
    assert stats["average_l_per_100km"] == Decimal("28.75")
    assert stats["segments"][0]["from_km"] == 10000  # расстояние - от якоря, не от частичной


def test_full_fill_without_odometer_is_not_an_anchor_but_counts_liters(ctx):
    stats = fills(ctx, ("300", 10000, True), ("50", None, True), ("100", 10500, True))
    assert stats["segments"][0]["distance_km"] == 500
    assert stats["average_l_per_100km"] == Decimal("30.00")  # (50 + 100) / 500


def test_fills_before_first_anchor_and_after_last_are_ignored(ctx):
    stats = fills(
        ctx,
        ("40", 9000, False),  # до первого якоря: начальный уровень неизвестен
        ("300", 10000, True),
        ("100", 10500, True),
        ("20", None, False),  # после последнего якоря: сегмент не закрыт
    )
    assert stats["liters"] == Decimal("100") and stats["distance_km"] == 500


def test_multiple_segments_average_is_weighted_by_distance(ctx):
    stats = fills(
        ctx,
        ("300", 10000, True),
        ("100", 10400, True),  # 25.00
        ("300", 11000, True),  # 300/600 -> 50.00? нет: 300 л на 600 км
    )
    assert [s["l_per_100km"] for s in stats["segments"]] == [Decimal("25.00"), Decimal("50.00")]
    assert stats["average_l_per_100km"] == Decimal("40.00")  # 400 л / 1000 км


def test_zero_distance_segment_is_dropped_without_error(ctx):
    stats = fills(ctx, ("300", 10000, True), ("100", 10000, True), ("100", 10500, True))
    assert [s["distance_km"] for s in stats["segments"]] == [500]


def test_not_enough_data(ctx):
    assert fills(ctx)["average_l_per_100km"] is None
    assert fills(ctx, ("300", 10000, True))["segments"] == []
    only_partial = fills(ctx, ("50", 10100, False))
    assert only_partial["average_l_per_100km"] is None


def test_order_is_by_time_not_by_insertion(ctx):
    FuelFill.objects.create(
        vehicle=ctx, filled_at=T0 + timedelta(days=2), liters=Decimal("130"), odometer_km=10800
    )
    FuelFill.objects.create(
        vehicle=ctx, filled_at=T0, liters=Decimal("300"), odometer_km=10000, full_tank=True
    )
    FuelFill.objects.create(
        vehicle=ctx,
        filled_at=T0 + timedelta(days=1),
        liters=Decimal("100"),
        full_tank=False,
    )
    assert services.fuel_stats(ctx)["average_l_per_100km"] == Decimal("28.75")
