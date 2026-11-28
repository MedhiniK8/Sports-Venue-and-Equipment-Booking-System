from datetime import date, datetime
from uuid import uuid4

from app.contracts.booking import TimeInterval
from app.e2_allocation import (
    EquipmentAllocationRequest,
    EquipmentCache,
    EquipmentInventory,
    EquipmentRequestLine,
    allocate_equipment,
)
from app.e2_allocation.cache import AvailabilityCache
from app.e2_allocation.models import AvailabilityInterval, AvailabilityStatus


BOOKING_DATE = date(2026, 11, 23)
FIXED_NOW = datetime(2026, 11, 23, 5, 0)


def interval(start=10, end=12):
    return TimeInterval(
        start=datetime(2026, 11, 23, start),
        end=datetime(2026, 11, 23, end),
    )


def test_public_equipment_imports_are_available():
    assert EquipmentCache is not None
    assert EquipmentAllocationRequest is not None
    assert allocate_equipment is not None


def test_equipment_only_allocation_does_not_mutate_court_cache():
    court_cache = AvailabilityCache()
    court_id = uuid4()
    court_cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            AvailabilityInterval(
                interval=interval(6, 20),
                status=AvailabilityStatus.FREE,
            )
        ],
    )
    before = court_cache.get_intervals(court_id, BOOKING_DATE)

    equipment_cache = EquipmentCache()
    equipment_id = uuid4()
    equipment_cache.set_inventory(
        EquipmentInventory(equipment_id=equipment_id, total_quantity=2)
    )
    request = EquipmentAllocationRequest(
        booking_id=uuid4(),
        court_id=court_id,
        interval=interval(),
        items=(
            EquipmentRequestLine(equipment_id=equipment_id, quantity=1),
        ),
    )
    result = allocate_equipment(
        request,
        equipment_cache,
        current_datetime=FIXED_NOW,
    )

    assert result.succeeded is True
    assert court_cache.get_intervals(court_id, BOOKING_DATE) == before
