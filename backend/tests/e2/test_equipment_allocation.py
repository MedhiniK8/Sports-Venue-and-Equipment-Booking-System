from datetime import date, datetime
from uuid import uuid4

import pytest

from app.contracts.booking import TimeInterval
from app.e2_allocation.equipment_allocation import allocate_equipment
from app.e2_allocation.equipment_cache import EquipmentCache
from app.e2_allocation.equipment_models import (
    EquipmentAllocationRequest,
    EquipmentInventory,
    EquipmentRequestLine,
    EquipmentReservation,
)


BOOKING_DATE = date(2026, 11, 23)
FIXED_NOW = datetime(2026, 11, 23, 5, 0)


def interval(start=10, end=12):
    return TimeInterval(
        start=datetime(2026, 11, 23, start),
        end=datetime(2026, 11, 23, end),
    )


def make_request(items, start=10, end=12, booking_id=None):
    return EquipmentAllocationRequest(
        booking_id=booking_id or uuid4(),
        interval=interval(start, end),
        items=tuple(items),
    )


def test_allocate_one_item_and_multiple_quantity():
    cache = EquipmentCache()
    equipment_id = uuid4()
    cache.set_inventory(EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=5,
    ))
    request = make_request([
        EquipmentRequestLine(equipment_id=equipment_id, quantity=3),
    ])

    result = allocate_equipment(
        request,
        cache,
        current_datetime=FIXED_NOW,
    )

    assert result.succeeded is True
    assert len(result.reservations) == 1
    reservations = cache.get_reservations(equipment_id, BOOKING_DATE)
    assert reservations is not None
    assert reservations[0].quantity == 3
    assert reservations[0].booking_id == request.booking_id


def test_allocate_multiple_items_atomically():
    cache = EquipmentCache()
    first = uuid4()
    second = uuid4()
    cache.set_inventory(EquipmentInventory(equipment_id=first, total_quantity=5))
    cache.set_inventory(EquipmentInventory(equipment_id=second, total_quantity=3))
    request = make_request([
        EquipmentRequestLine(equipment_id=first, quantity=2),
        EquipmentRequestLine(equipment_id=second, quantity=1),
    ])

    result = allocate_equipment(
        request,
        cache,
        current_datetime=FIXED_NOW,
    )

    assert result.succeeded is True
    assert cache.get_reservations(first, BOOKING_DATE) is not None
    assert cache.get_reservations(second, BOOKING_DATE) is not None


def test_multi_item_shortage_leaves_no_partial_allocations():
    cache = EquipmentCache()
    first = uuid4()
    second = uuid4()
    cache.set_inventory(EquipmentInventory(equipment_id=first, total_quantity=5))
    cache.set_inventory(EquipmentInventory(equipment_id=second, total_quantity=1))
    first_before = cache.get_reservations(first, BOOKING_DATE)
    second_before = cache.get_reservations(second, BOOKING_DATE)
    request = make_request([
        EquipmentRequestLine(equipment_id=first, quantity=2),
        EquipmentRequestLine(equipment_id=second, quantity=2),
    ])

    result = allocate_equipment(
        request,
        cache,
        current_datetime=FIXED_NOW,
    )

    assert result.succeeded is False
    assert len(result.shortages) == 1
    assert cache.get_reservations(first, BOOKING_DATE) == first_before
    assert cache.get_reservations(second, BOOKING_DATE) == second_before


def test_missing_inventory_leaves_cache_unchanged():
    cache = EquipmentCache()
    equipment_id = uuid4()
    request = make_request([
        EquipmentRequestLine(equipment_id=equipment_id, quantity=1),
    ])
    result = allocate_equipment(
        request,
        cache,
        current_datetime=FIXED_NOW,
    )
    assert result.succeeded is False
    assert len(result.shortages) == 1
    assert not cache.has_reservations(equipment_id, BOOKING_DATE)


def test_exact_inventory_can_be_allocated():
    cache = EquipmentCache()
    equipment_id = uuid4()
    cache.set_inventory(EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=2,
    ))
    request = make_request([
        EquipmentRequestLine(equipment_id=equipment_id, quantity=2),
    ])
    result = allocate_equipment(
        request,
        cache,
        current_datetime=FIXED_NOW,
    )
    assert result.succeeded is True


def test_overlapping_reservation_uses_concurrent_quantity():
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
                interval=interval(9, 11),
                quantity=4,
            )
        ],
    )
    request = make_request([
        EquipmentRequestLine(equipment_id=equipment_id, quantity=2),
    ])
    result = allocate_equipment(
        request,
        cache,
        current_datetime=FIXED_NOW,
    )
    assert result.succeeded is False
    assert len(cache.get_reservations(equipment_id, BOOKING_DATE) or []) == 1


def test_duplicate_booking_retry_is_deterministic():
    cache = EquipmentCache()
    equipment_id = uuid4()
    cache.set_inventory(EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=5,
    ))
    booking_id = uuid4()
    request = make_request([
        EquipmentRequestLine(equipment_id=equipment_id, quantity=2),
    ], booking_id=booking_id)

    first = allocate_equipment(request, cache, current_datetime=FIXED_NOW)
    before = cache.get_reservations(equipment_id, BOOKING_DATE)
    second = allocate_equipment(request, cache, current_datetime=FIXED_NOW)

    assert first.succeeded is True
    assert second.succeeded is True
    assert cache.get_reservations(equipment_id, BOOKING_DATE) == before
    assert len(before or []) == 1


def test_duplicate_booking_with_different_request_is_rejected():
    cache = EquipmentCache()
    equipment_id = uuid4()
    cache.set_inventory(EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=5,
    ))
    booking_id = uuid4()
    first_request = make_request([
        EquipmentRequestLine(equipment_id=equipment_id, quantity=2),
    ], booking_id=booking_id)
    allocate_equipment(first_request, cache, current_datetime=FIXED_NOW)

    second_request = make_request([
        EquipmentRequestLine(equipment_id=equipment_id, quantity=3),
    ], booking_id=booking_id)
    result = allocate_equipment(
        second_request,
        cache,
        current_datetime=FIXED_NOW,
    )

    assert result.succeeded is False
    assert "inconsistent" in result.errors[0]


def test_court_only_empty_request_succeeds():
    cache = EquipmentCache()
    request = make_request([])
    result = allocate_equipment(
        request,
        cache,
        current_datetime=FIXED_NOW,
    )
    assert result.succeeded is True
    assert result.reservations == ()
