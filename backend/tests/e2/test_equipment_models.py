from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts.booking import TimeInterval
from app.e2_allocation.equipment_models import (
    EquipmentAllocationRequest,
    EquipmentInventory,
    EquipmentRequestLine,
    EquipmentReservation,
    EquipmentShortage,
)


def interval(start=10, end=12):
    return TimeInterval(
        start=datetime(2026, 11, 23, start),
        end=datetime(2026, 11, 23, end),
    )


def test_valid_equipment_inventory():
    equipment_id = uuid4()
    inventory = EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=5,
    )
    assert inventory.equipment_id == equipment_id
    assert inventory.total_quantity == 5


@pytest.mark.parametrize("quantity", [-1, True, 1.5, "2"])
def test_invalid_inventory_quantity(quantity):
    with pytest.raises(ValidationError):
        EquipmentInventory(equipment_id=uuid4(), total_quantity=quantity)


def test_zero_inventory_is_valid():
    inventory = EquipmentInventory(equipment_id=uuid4(), total_quantity=0)
    assert inventory.total_quantity == 0


@pytest.mark.parametrize("quantity", [0, -1, True, 1.5, "2"])
def test_invalid_request_quantity(quantity):
    with pytest.raises(ValidationError):
        EquipmentRequestLine(equipment_id=uuid4(), quantity=quantity)


def test_valid_request_and_reservation_models():
    equipment_id = uuid4()
    booking_id = uuid4()
    request = EquipmentRequestLine(equipment_id=equipment_id, quantity=2)
    reservation = EquipmentReservation(
        equipment_id=equipment_id,
        booking_id=booking_id,
        interval=interval(),
        quantity=2,
    )
    assert request.quantity == 2
    assert reservation.booking_id == booking_id


def test_duplicate_equipment_request_items_are_rejected():
    equipment_id = uuid4()
    with pytest.raises(ValidationError, match="duplicate equipment"):
        EquipmentAllocationRequest(
            booking_id=uuid4(),
            interval=interval(),
            items=(
                EquipmentRequestLine(equipment_id=equipment_id, quantity=1),
                EquipmentRequestLine(equipment_id=equipment_id, quantity=2),
            ),
        )


def test_empty_equipment_request_is_valid_for_court_only():
    request = EquipmentAllocationRequest(
        booking_id=uuid4(),
        interval=interval(),
        items=(),
    )
    assert request.items == ()


def test_multi_item_request_is_preserved():
    request = EquipmentAllocationRequest(
        booking_id=uuid4(),
        interval=interval(),
        items=(
            EquipmentRequestLine(equipment_id=uuid4(), quantity=2),
            EquipmentRequestLine(equipment_id=uuid4(), quantity=1),
        ),
    )
    assert len(request.items) == 2


def test_reservation_rejects_cross_date_and_timezone():
    equipment_id = uuid4()
    booking_id = uuid4()
    cross_date = TimeInterval(
        start=datetime(2026, 11, 23, 23),
        end=datetime(2026, 11, 24, 1),
    )
    with pytest.raises(ValidationError, match="one date"):
        EquipmentReservation(
            equipment_id=equipment_id,
            booking_id=booking_id,
            interval=cross_date,
            quantity=1,
        )


def test_valid_shortage_model():
    shortage = EquipmentShortage(
        equipment_id=uuid4(),
        requested_quantity=3,
        available_quantity=1,
    )
    assert shortage.requested_quantity == 3
    assert shortage.available_quantity == 1
