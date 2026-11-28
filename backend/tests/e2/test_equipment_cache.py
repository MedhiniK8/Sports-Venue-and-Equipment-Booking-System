from datetime import date, datetime
from uuid import uuid4

import pytest

from app.contracts.booking import TimeInterval
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


def reservation(
    equipment_id,
    booking_id,
    start,
    end,
    quantity,
    booking_date=BOOKING_DATE,
):
    return EquipmentReservation(
        equipment_id=equipment_id,
        booking_id=booking_id,
        interval=TimeInterval(
            start=datetime(
                booking_date.year,
                booking_date.month,
                booking_date.day,
                start,
            ),
            end=datetime(
                booking_date.year,
                booking_date.month,
                booking_date.day,
                end,
            ),
        ),
        quantity=quantity,
    )


def test_set_and_retrieve_inventory():
    cache = EquipmentCache()
    inventory = EquipmentInventory(equipment_id=uuid4(), total_quantity=5)
    cache.set_inventory(inventory)
    assert cache.get_inventory(inventory.equipment_id) == inventory
    assert cache.has_inventory(inventory.equipment_id)


def test_missing_reservations_and_inventory():
    cache = EquipmentCache()
    equipment_id = uuid4()
    assert cache.get_inventory(equipment_id) is None
    assert cache.get_reservations(equipment_id, BOOKING_DATE) is None


def test_set_get_and_sort_reservations():
    cache = EquipmentCache()
    equipment_id = uuid4()
    cache.set_inventory(EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=10,
    ))
    late = reservation(equipment_id, uuid4(), 12, 14, 1)
    early = reservation(equipment_id, uuid4(), 8, 10, 1)
    cache.set_reservations(equipment_id, BOOKING_DATE, [late, early])
    stored = cache.get_reservations(equipment_id, BOOKING_DATE)
    assert stored == [early, late]


def test_reservation_exceeding_inventory_is_rejected():
    cache = EquipmentCache()
    equipment_id = uuid4()
    cache.set_inventory(EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=2,
    ))
    with pytest.raises(ValueError, match="exceed"):
        cache.set_reservations(
            equipment_id,
            BOOKING_DATE,
            [
                reservation(equipment_id, uuid4(), 8, 12, 2),
                reservation(equipment_id, uuid4(), 9, 11, 1),
            ],
        )
    assert not cache.has_reservations(equipment_id, BOOKING_DATE)


def test_inventory_reduction_rejects_when_existing_reservation_exceeds_new_quantity():
    cache = EquipmentCache()
    equipment_id = uuid4()
    cache.set_inventory(EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=5,
    ))
    cache.set_reservations(
        equipment_id,
        BOOKING_DATE,
        [reservation(equipment_id, uuid4(), 8, 12, 4)],
    )
    before = cache.get_inventory(equipment_id)

    result = cache.replace_inventory(
        EquipmentInventory(equipment_id=equipment_id, total_quantity=3)
    )

    assert result.valid is False
    assert "existing reservations" in result.errors[0]
    assert cache.get_inventory(equipment_id) == before


def test_inventory_reduction_preserves_reservations_when_still_safe():
    cache = EquipmentCache()
    equipment_id = uuid4()
    cache.set_inventory(EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=5,
    ))
    cache.set_reservations(
        equipment_id,
        BOOKING_DATE,
        [reservation(equipment_id, uuid4(), 8, 12, 2)],
    )
    result = cache.replace_inventory(
        EquipmentInventory(equipment_id=equipment_id, total_quantity=3)
    )
    assert result.valid is True
    assert cache.get_reservations(equipment_id, BOOKING_DATE) is not None


def test_batch_replace_is_atomic_on_failure():
    cache = EquipmentCache()
    first = uuid4()
    second = uuid4()
    cache.set_inventory(EquipmentInventory(equipment_id=first, total_quantity=5))
    cache.set_inventory(EquipmentInventory(equipment_id=second, total_quantity=1))
    original = reservation(first, uuid4(), 8, 10, 1)
    cache.set_reservations(first, BOOKING_DATE, [original])
    before = cache.get_reservations(first, BOOKING_DATE)

    with pytest.raises(ValueError, match="exceed"):
        cache.batch_replace_reservations({
            (first, BOOKING_DATE): [
                original,
                reservation(first, uuid4(), 9, 11, 5),
            ],
            (second, BOOKING_DATE): [
                reservation(second, uuid4(), 8, 12, 2),
            ],
        })

    assert cache.get_reservations(first, BOOKING_DATE) == before
    assert not cache.has_reservations(second, BOOKING_DATE)


def test_remove_clear_and_separate_dates():
    cache = EquipmentCache()
    equipment_id = uuid4()
    cache.set_inventory(EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=5,
    ))
    cache.set_reservations(
        equipment_id,
        BOOKING_DATE,
        [reservation(equipment_id, uuid4(), 8, 10, 1)],
    )
    next_date = date(2026, 11, 24)
    cache.set_reservations(
        equipment_id,
        next_date,
        [reservation(equipment_id, uuid4(), 8, 10, 1, next_date)],
    )

    cache.remove_reservations(equipment_id, BOOKING_DATE)
    assert not cache.has_reservations(equipment_id, BOOKING_DATE)
    assert cache.has_reservations(equipment_id, next_date)
    cache.clear()
    assert not cache.has_inventory(equipment_id)
