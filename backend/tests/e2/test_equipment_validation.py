from datetime import date, datetime
from uuid import uuid4

import pytest

from app.contracts.booking import TimeInterval
from app.e2_allocation import equipment_validation as equipment_validation_module
from app.e2_allocation.equipment_cache import EquipmentCache
from app.e2_allocation.equipment_models import (
    EquipmentAllocationRequest,
    EquipmentInventory,
    EquipmentRequestLine,
    EquipmentReservation,
)
from app.e2_allocation.equipment_validation import (
    validate_equipment_request,
)


BOOKING_DATE = date(2026, 11, 23)
FIXED_NOW = datetime(2026, 11, 23, 5, 0)


def interval(start=10, end=12, booking_date=BOOKING_DATE):
    return TimeInterval(
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
    )


def request_for(items, start=10, end=12, booking_date=BOOKING_DATE):
    return EquipmentAllocationRequest(
        booking_id=uuid4(),
        interval=interval(start, end, booking_date),
        items=tuple(items),
    )


def test_entire_interval_available():
    cache = EquipmentCache()
    equipment_id = uuid4()
    cache.set_inventory(EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=5,
    ))
    request = request_for([
        EquipmentRequestLine(equipment_id=equipment_id, quantity=3),
    ])
    result = validate_equipment_request(
        request,
        cache,
        current_datetime=FIXED_NOW,
    )
    assert result.valid is True
    assert result.shortages == []


def test_insufficient_quantity_reports_shortage():
    cache = EquipmentCache()
    equipment_id = uuid4()
    cache.set_inventory(EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=2,
    ))
    cache.set_reservations(
        equipment_id,
        BOOKING_DATE,
        [
            EquipmentReservation(
                equipment_id=equipment_id,
                booking_id=uuid4(),
                interval=interval(10, 11),
                quantity=2,
            )
        ],
    )
    request = request_for([
        EquipmentRequestLine(equipment_id=equipment_id, quantity=1),
    ])
    result = validate_equipment_request(
        request,
        cache,
        current_datetime=FIXED_NOW,
    )
    assert result.valid is False
    assert result.shortages[0].available_quantity == 0
    assert "Insufficient equipment" in result.errors[0]


def test_multiple_shortages_are_reported():
    cache = EquipmentCache()
    first = uuid4()
    second = uuid4()
    cache.set_inventory(EquipmentInventory(
        equipment_id=first,
        total_quantity=1,
    ))
    cache.set_inventory(EquipmentInventory(
        equipment_id=second,
        total_quantity=0,
    ))
    request = request_for([
        EquipmentRequestLine(equipment_id=first, quantity=2),
        EquipmentRequestLine(equipment_id=second, quantity=1),
    ])
    result = validate_equipment_request(
        request,
        cache,
        current_datetime=FIXED_NOW,
    )
    assert result.valid is False
    assert len(result.shortages) == 2
    assert {item.equipment_id for item in result.shortages} == {first, second}


def test_missing_inventory_is_reported():
    cache = EquipmentCache()
    equipment_id = uuid4()
    request = request_for([
        EquipmentRequestLine(equipment_id=equipment_id, quantity=1),
    ])
    result = validate_equipment_request(
        request,
        cache,
        current_datetime=FIXED_NOW,
    )
    assert result.valid is False
    assert "Inventory is missing" in result.errors[0]


def test_court_only_empty_request_is_valid():
    cache = EquipmentCache()
    request = request_for([])
    result = validate_equipment_request(
        request,
        cache,
        current_datetime=FIXED_NOW,
    )
    assert result.valid is True


@pytest.mark.parametrize(
    ("start", "end"),
    [(5, 6), (19, 21)],
)
def test_equipment_interval_must_be_within_operating_hours(start, end):
    cache = EquipmentCache()
    request = request_for([], start=start, end=end)
    result = validate_equipment_request(
        request,
        cache,
        current_datetime=FIXED_NOW,
    )
    assert result.valid is False
    assert "06:00-20:00" in result.errors[0]


def test_past_date_and_started_interval_are_rejected():
    cache = EquipmentCache()
    past_request = request_for(
        [],
        booking_date=BOOKING_DATE - __import__("datetime").timedelta(days=1),
    )
    past_result = validate_equipment_request(
        past_request,
        cache,
        current_datetime=datetime(2026, 11, 23, 10),
    )
    assert past_result.valid is False

    started_request = request_for([], start=10, end=12)
    started_result = validate_equipment_request(
        started_request,
        cache,
        current_datetime=datetime(2026, 11, 23, 10),
    )
    assert started_result.valid is False


def test_default_equipment_clock_uses_venue_local_time(monkeypatch):
    cache = EquipmentCache()
    monkeypatch.setattr(
        equipment_validation_module,
        "current_venue_local_naive",
        lambda: datetime(2026, 11, 23, 19, 20),
    )

    result = validate_equipment_request(
        request_for([], start=19, end=20),
        cache,
    )

    assert result.valid is False
    assert "already started or passed" in result.errors[0]


def test_timezone_aware_current_datetime_is_rejected():
    cache = EquipmentCache()
    request = request_for([])
    result = validate_equipment_request(
        request,
        cache,
        current_datetime=datetime(
            2026, 11, 23, 5, tzinfo=__import__("datetime").timezone.utc
        ),
    )
    assert result.valid is False
    assert "naive venue-local" in result.errors[0]
