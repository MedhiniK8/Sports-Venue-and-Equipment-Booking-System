from datetime import datetime
from uuid import uuid4

import pytest

from app.contracts.booking import TimeInterval
from app.e2_allocation.equipment_interval_utils import (
    calculate_equipment_availability_segments,
    get_max_concurrent_quantity,
)
from app.e2_allocation.equipment_models import EquipmentReservation


def interval(start, end, end_minute=0):
    return TimeInterval(
        start=datetime(2026, 11, 23, start, 0),
        end=datetime(2026, 11, 23, end, end_minute),
    )


def reservation(start, end, quantity):
    return EquipmentReservation(
        equipment_id=uuid4(),
        booking_id=uuid4(),
        interval=interval(start, end),
        quantity=quantity,
    )


@pytest.mark.parametrize(
    ("reservation_interval", "requested_interval", "overlap"),
    [
        ((8, 9), (9, 10), False),
        ((9, 10), (9, 10), True),
        ((8, 11), (9, 10), True),
        ((9, 9), None, None),
    ],
)
def test_half_open_overlap_cases(
    reservation_interval,
    requested_interval,
    overlap,
):
    if overlap is None:
        return
    existing = reservation(*reservation_interval, 1)
    existing_interval = existing.interval
    requested = interval(*requested_interval)
    assert (
        existing_interval.start < requested.end
        and requested.start < existing_interval.end
    ) is overlap


def test_multiple_reservations_create_multiple_segments():
    equipment_id = uuid4()
    first = EquipmentReservation(
        equipment_id=equipment_id,
        booking_id=uuid4(),
        interval=interval(8, 11),
        quantity=2,
    )
    second = EquipmentReservation(
        equipment_id=equipment_id,
        booking_id=uuid4(),
        interval=interval(10, 12),
        quantity=1,
    )
    segments = calculate_equipment_availability_segments(
        5,
        [first, second],
        interval(9, 11, 30),
    )
    assert [
        (
            segment.interval.start.hour,
            segment.interval.end.hour,
            segment.reserved_quantity,
            segment.available_quantity,
        )
        for segment in segments
    ] == [
        (9, 10, 2, 3),
        (10, 11, 3, 2),
        (11, 11, 1, 4),
    ]


def test_empty_reservation_list_reports_full_inventory():
    segments = calculate_equipment_availability_segments(
        4,
        [],
        interval(9, 12),
    )
    assert len(segments) == 1
    assert segments[0].reserved_quantity == 0
    assert segments[0].available_quantity == 4


def test_max_concurrent_quantity_sums_different_reservations():
    reservations = [
        reservation(8, 12, 2),
        reservation(9, 11, 3),
        reservation(10, 13, 1),
    ]
    assert get_max_concurrent_quantity(reservations) == 6


def test_adjacent_reservations_do_not_overlap_at_boundary():
    reservations = [
        reservation(8, 10, 2),
        reservation(10, 12, 3),
    ]
    segments = calculate_equipment_availability_segments(
        5,
        reservations,
        interval(8, 12),
    )
    assert [
        (segment.reserved_quantity, segment.available_quantity)
        for segment in segments
    ] == [(2, 3), (3, 2)]
