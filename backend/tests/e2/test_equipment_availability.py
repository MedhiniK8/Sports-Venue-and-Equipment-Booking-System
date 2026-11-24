from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from app.contracts.booking import TimeInterval
from app.e2_allocation.equipment_availability import get_equipment_availability
from app.e2_allocation.equipment_cache import EquipmentCache
from app.e2_allocation.equipment_models import (
    EquipmentInventory,
    EquipmentReservation,
)


BOOKING_DATE = date(2026, 11, 23)


def interval(start=10, end=12):
    return TimeInterval(
        start=datetime(2026, 11, 23, start),
        end=datetime(2026, 11, 23, end),
    )


def test_full_inventory_is_available_without_reservations():
    cache = EquipmentCache()
    equipment_id = uuid4()
    cache.set_inventory(EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=5,
    ))
    result = get_equipment_availability(
        equipment_id,
        interval(),
        cache,
        requested_quantity=3,
    )
    assert result.valid is True
    assert result.available_quantity == 5
    assert len(result.segments) == 1


def test_availability_reports_shortage_in_multiple_segments():
    cache = EquipmentCache()
    equipment_id = uuid4()
    cache.set_inventory(EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=5,
    ))
    cache.set_reservations(
        equipment_id,
        BOOKING_DATE,
        [
            EquipmentReservation(
                equipment_id=equipment_id,
                booking_id=uuid4(),
                interval=interval(11, 13),
                quantity=4,
            )
        ],
    )
    result = get_equipment_availability(
        equipment_id,
        interval(10, 12),
        cache,
        requested_quantity=2,
    )
    assert result.valid is False
    assert result.available_quantity == 1
    assert result.shortages[0].available_quantity == 1
    assert [
        segment.reserved_quantity
        for segment in result.segments
    ] == [0, 4]


def test_zero_inventory_and_missing_inventory_are_reported():
    cache = EquipmentCache()
    zero_id = uuid4()
    missing_id = uuid4()
    cache.set_inventory(EquipmentInventory(
        equipment_id=zero_id,
        total_quantity=0,
    ))
    zero = get_equipment_availability(
        zero_id,
        interval(),
        cache,
        requested_quantity=1,
    )
    missing = get_equipment_availability(
        missing_id,
        interval(),
        cache,
        requested_quantity=1,
    )
    assert zero.valid is False
    assert zero.available_quantity == 0
    assert missing.valid is False
    assert missing.available_quantity == 0


def test_equipment_availability_rejects_timezone_aware_interval():
    cache = EquipmentCache()
    equipment_id = uuid4()
    cache.set_inventory(EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=5,
    ))
    aware = TimeInterval(
        start=datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc),
        end=datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc),
    )

    result = get_equipment_availability(
        equipment_id,
        aware,
        cache,
        requested_quantity=1,
    )

    assert result.valid is False
    assert "naive venue-local" in result.errors[0]


def test_equipment_availability_rejects_cross_date_interval():
    cache = EquipmentCache()
    equipment_id = uuid4()
    cache.set_inventory(EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=5,
    ))
    cross_date = TimeInterval(
        start=datetime(2026, 11, 23, 19, 0),
        end=datetime(2026, 11, 24, 7, 0),
    )

    result = get_equipment_availability(
        equipment_id,
        cross_date,
        cache,
        requested_quantity=1,
    )

    assert result.valid is False
    assert "one date" in result.errors[0]


@pytest.mark.parametrize(
    ("start_hour", "end_hour"),
    [(5, 6), (19, 21)],
)
def test_equipment_availability_rejects_outside_operating_hours(
    start_hour,
    end_hour,
):
    cache = EquipmentCache()
    equipment_id = uuid4()
    cache.set_inventory(EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=5,
    ))
    outside = TimeInterval(
        start=datetime(2026, 11, 23, start_hour),
        end=datetime(2026, 11, 23, end_hour),
    )

    result = get_equipment_availability(
        equipment_id,
        outside,
        cache,
        requested_quantity=1,
    )

    assert result.valid is False
    assert "06:00-20:00" in result.errors[0]


def test_equipment_availability_allows_past_datetime_for_query_only():
    cache = EquipmentCache()
    equipment_id = uuid4()
    cache.set_inventory(EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=5,
    ))
    past = TimeInterval(
        start=datetime(2026, 11, 22, 10, 0),
        end=datetime(2026, 11, 22, 12, 0),
    )

    result = get_equipment_availability(
        equipment_id,
        past,
        cache,
        requested_quantity=1,
    )

    assert result.valid is True
