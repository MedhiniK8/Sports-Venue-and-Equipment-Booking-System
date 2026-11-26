from datetime import date, datetime
from uuid import uuid4

from app.contracts.booking import TimeInterval
from app.e2_allocation.equipment_allocation import allocate_equipment
from app.e2_allocation.equipment_cache import EquipmentCache
from app.e2_allocation.equipment_cancellation import cancel_equipment_booking
from app.e2_allocation.equipment_models import (
    EquipmentAllocationRequest,
    EquipmentInventory,
    EquipmentRequestLine,
)


BOOKING_DATE = date(2026, 11, 23)
FIXED_NOW = datetime(2026, 11, 23, 5, 0)


def interval(start=10, end=12):
    return TimeInterval(
        start=datetime(2026, 11, 23, start),
        end=datetime(2026, 11, 23, end),
    )


def make_request(booking_id, items):
    return EquipmentAllocationRequest(
        booking_id=booking_id,
        interval=interval(),
        items=tuple(items),
    )


def test_cancel_all_equipment_for_booking():
    cache = EquipmentCache()
    first = uuid4()
    second = uuid4()
    cache.set_inventory(EquipmentInventory(equipment_id=first, total_quantity=5))
    cache.set_inventory(EquipmentInventory(equipment_id=second, total_quantity=5))
    booking_id = uuid4()
    request = make_request(booking_id, [
        EquipmentRequestLine(equipment_id=first, quantity=2),
        EquipmentRequestLine(equipment_id=second, quantity=1),
    ])
    allocate_equipment(request, cache, current_datetime=FIXED_NOW)

    result = cancel_equipment_booking(booking_id, cache)

    assert result.succeeded is True
    assert result.cancelled_reservation_count == 2
    assert cache.get_reservations(first, BOOKING_DATE) == []
    assert cache.get_reservations(second, BOOKING_DATE) == []


def test_item_specific_cancellation_preserves_other_items():
    cache = EquipmentCache()
    first = uuid4()
    second = uuid4()
    cache.set_inventory(EquipmentInventory(equipment_id=first, total_quantity=5))
    cache.set_inventory(EquipmentInventory(equipment_id=second, total_quantity=5))
    booking_id = uuid4()
    request = make_request(booking_id, [
        EquipmentRequestLine(equipment_id=first, quantity=2),
        EquipmentRequestLine(equipment_id=second, quantity=1),
    ])
    allocate_equipment(request, cache, current_datetime=FIXED_NOW)

    result = cancel_equipment_booking(booking_id, cache, first)

    assert result.succeeded is True
    assert result.cancelled_reservation_count == 1
    assert cache.get_reservations(first, BOOKING_DATE) == []
    assert len(cache.get_reservations(second, BOOKING_DATE) or []) == 1


def test_cancellation_preserves_other_booking_reservations():
    cache = EquipmentCache()
    equipment_id = uuid4()
    cache.set_inventory(EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=5,
    ))
    first_id = uuid4()
    second_id = uuid4()
    first_request = make_request(first_id, [
        EquipmentRequestLine(equipment_id=equipment_id, quantity=2),
    ])
    second_request = make_request(second_id, [
        EquipmentRequestLine(equipment_id=equipment_id, quantity=1),
    ])
    allocate_equipment(first_request, cache, current_datetime=FIXED_NOW)
    allocate_equipment(second_request, cache, current_datetime=FIXED_NOW)

    result = cancel_equipment_booking(first_id, cache)

    assert result.succeeded is True
    reservations = cache.get_reservations(equipment_id, BOOKING_DATE)
    assert reservations is not None
    assert len(reservations) == 1
    assert reservations[0].booking_id == second_id


def test_missing_and_repeated_cancellation_fail():
    cache = EquipmentCache()
    equipment_id = uuid4()
    cache.set_inventory(EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=5,
    ))
    booking_id = uuid4()
    request = make_request(booking_id, [
        EquipmentRequestLine(equipment_id=equipment_id, quantity=2),
    ])
    allocate_equipment(request, cache, current_datetime=FIXED_NOW)

    first = cancel_equipment_booking(booking_id, cache)
    repeated = cancel_equipment_booking(booking_id, cache)
    missing = cancel_equipment_booking(uuid4(), cache)

    assert first.succeeded is True
    assert repeated.succeeded is False
    assert missing.succeeded is False


def test_cancel_then_allocate_again_restores_availability():
    cache = EquipmentCache()
    equipment_id = uuid4()
    cache.set_inventory(EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=2,
    ))
    first_id = uuid4()
    first_request = make_request(first_id, [
        EquipmentRequestLine(equipment_id=equipment_id, quantity=2),
    ])
    allocate_equipment(first_request, cache, current_datetime=FIXED_NOW)

    cancel_equipment_booking(first_id, cache)

    second_request = make_request(uuid4(), [
        EquipmentRequestLine(equipment_id=equipment_id, quantity=2),
    ])
    result = allocate_equipment(
        second_request,
        cache,
        current_datetime=FIXED_NOW,
    )
    assert result.succeeded is True
