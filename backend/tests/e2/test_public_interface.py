from datetime import date, datetime
from uuid import uuid4

from app.e2_allocation import (
    AllocationService,
    AvailabilityCache,
    CommittedBooking,
    EquipmentAllocationRequest,
    EquipmentCache,
    EquipmentInventory,
    EquipmentRequestLine,
    EquipmentReservation,
    TimeInterval,
    AvailabilityStatus,
)


BOOKING_DATE = date(2026, 11, 23)
FIXED_NOW = datetime(2026, 11, 23, 5, 0)


def interval(start=10, end=12):
    return TimeInterval(
        start=datetime(2026, 11, 23, start),
        end=datetime(2026, 11, 23, end),
    )


def test_public_service_initializes_with_isolated_caches():
    court_cache = AvailabilityCache()
    equipment_cache = EquipmentCache()
    service = AllocationService(court_cache, equipment_cache)
    assert service.court_cache is court_cache
    assert service.equipment_cache is equipment_cache


def test_public_court_availability_and_allocation():
    service = AllocationService()
    court_id = uuid4()
    booking_id = uuid4()
    service.generate_availability(
        [court_id],
        [],
        [],
        BOOKING_DATE,
    )

    available = service.check_court_availability(
        court_id,
        BOOKING_DATE,
        interval(),
        current_datetime=FIXED_NOW,
    )
    assert available.valid is True

    allocated = service.allocate_court(
        court_id,
        BOOKING_DATE,
        interval(),
        booking_id,
        current_datetime=FIXED_NOW,
    )
    assert allocated.valid is True
    assert service.get_court_availability(court_id, BOOKING_DATE) is not None


def test_public_court_availability_return_is_mutation_isolated():
    service = AllocationService()
    court_id = uuid4()
    service.generate_availability([court_id], [], [], BOOKING_DATE)

    returned = service.get_court_availability(court_id, BOOKING_DATE)
    assert returned is not None
    returned[0].status = "BLOCKED"
    returned[0].interval.start = datetime(2026, 11, 23, 12, 0)

    cached = service.get_court_availability(court_id, BOOKING_DATE)
    assert cached is not None
    assert cached[0].status is AvailabilityStatus.FREE
    assert cached[0].interval.start == datetime(2026, 11, 23, 6, 0)


def test_public_court_cancellation():
    service = AllocationService()
    court_id = uuid4()
    booking_id = uuid4()
    service.generate_availability([court_id], [], [], BOOKING_DATE)
    assert service.allocate_court(
        court_id,
        BOOKING_DATE,
        interval(),
        booking_id,
        FIXED_NOW,
    ).valid

    result = service.cancel_court(
        court_id,
        BOOKING_DATE,
        booking_id,
    )
    assert result.valid is True


def test_public_equipment_availability_and_allocation():
    service = AllocationService()
    equipment_id = uuid4()
    inventory_result = service.set_equipment_inventory(
        EquipmentInventory(
            equipment_id=equipment_id,
            total_quantity=5,
        )
    )
    assert inventory_result.valid is True

    availability = service.get_equipment_availability(
        equipment_id,
        interval(),
        requested_quantity=3,
    )
    assert availability.valid is True

    result = service.allocate_equipment(
        EquipmentAllocationRequest(
            booking_id=uuid4(),
            court_id=uuid4(),
            interval=interval(),
            items=(
                EquipmentRequestLine(
                    equipment_id=equipment_id,
                    quantity=3,
                ),
            ),
        ),
        current_datetime=FIXED_NOW,
    )
    assert result.succeeded is True


def test_public_combined_allocation_and_cancellation():
    service = AllocationService()
    court_id = uuid4()
    equipment_id = uuid4()
    booking_id = uuid4()
    service.generate_availability([court_id], [], [], BOOKING_DATE)
    assert service.set_equipment_inventory(
        EquipmentInventory(
            equipment_id=equipment_id,
            total_quantity=5,
        )
    ).valid

    result = service.allocate_combined(
        court_id,
        BOOKING_DATE,
        interval(),
        booking_id,
        (
            EquipmentRequestLine(
                equipment_id=equipment_id,
                quantity=2,
            ),
        ),
        current_datetime=FIXED_NOW,
    )
    assert result.succeeded is True

    cancellation = service.cancel_combined(
        booking_id,
        court_id,
        BOOKING_DATE,
    )
    assert cancellation.succeeded is True


def test_public_equipment_cancellation():
    service = AllocationService()
    equipment_id = uuid4()
    booking_id = uuid4()
    assert service.set_equipment_inventory(
        EquipmentInventory(
            equipment_id=equipment_id,
            total_quantity=5,
        )
    ).valid

    allocated = service.allocate_equipment(
        EquipmentAllocationRequest(
            booking_id=booking_id,
            interval=interval(),
            items=(
                EquipmentRequestLine(
                    equipment_id=equipment_id,
                    quantity=2,
                ),
            ),
        ),
        current_datetime=FIXED_NOW,
    )
    assert allocated.succeeded is True

    cancellation = service.cancel_equipment(
        booking_id=booking_id,
    )
    assert cancellation.succeeded is True
    assert service.equipment_cache.get_reservations(
        equipment_id,
        BOOKING_DATE,
    ) == []


def test_public_failure_results_are_structured():
    service = AllocationService()
    court_id = uuid4()
    result = service.check_court_availability(
        court_id,
        BOOKING_DATE,
        interval(),
        current_datetime=FIXED_NOW,
    )
    assert result.valid is False
    assert result.errors


def test_public_court_block():
    service = AllocationService()
    court_id = uuid4()
    block_id = uuid4()
    service.generate_availability([court_id], [], [], BOOKING_DATE)
    result = service.apply_court_block(
        court_id,
        BOOKING_DATE,
        interval(),
        block_id,
        FIXED_NOW,
    )
    assert result.valid is True


def test_public_generation_accepts_committed_booking_records():
    service = AllocationService()
    court_id = uuid4()
    booking = CommittedBooking(
        booking_id=uuid4(),
        court_id=court_id,
        interval=interval(),
    )
    service.generate_availability([court_id], [booking], [], BOOKING_DATE)
    court_availability = service.get_court_availability(
        court_id,
        BOOKING_DATE,
    )
    assert court_availability is not None


def test_public_equipment_reservation_refresh_replaces_snapshot():
    service = AllocationService()
    equipment_id = uuid4()
    assert service.set_equipment_inventory(
        EquipmentInventory(
            equipment_id=equipment_id,
            total_quantity=5,
        )
    ).valid
    stale_booking_id = uuid4()
    stale_result = service.refresh_equipment_reservations(
        [
            EquipmentReservation(
                equipment_id=equipment_id,
                booking_id=stale_booking_id,
                interval=interval(8, 9),
                quantity=2,
            )
        ]
    )
    assert stale_result.valid is True

    booking_id = uuid4()
    refreshed = service.refresh_equipment_reservations(
        [
            EquipmentReservation(
                equipment_id=equipment_id,
                booking_id=booking_id,
                interval=interval(10, 12),
                quantity=3,
            )
        ]
    )
    assert refreshed.valid is True
    reservations = service.equipment_cache.get_reservations(
        equipment_id,
        BOOKING_DATE,
    )
    assert reservations is not None
    assert len(reservations) == 1
    assert reservations[0].booking_id == booking_id
    assert reservations[0].quantity == 3


def test_public_equipment_reservation_refresh_failure_is_atomic():
    service = AllocationService()
    equipment_id = uuid4()
    assert service.set_equipment_inventory(
        EquipmentInventory(
            equipment_id=equipment_id,
            total_quantity=3,
        )
    ).valid
    booking_id = uuid4()
    assert service.refresh_equipment_reservations(
        [
            EquipmentReservation(
                equipment_id=equipment_id,
                booking_id=booking_id,
                interval=interval(8, 10),
                quantity=2,
            )
        ]
    ).valid
    before = service.equipment_cache.snapshot()

    failed = service.refresh_equipment_reservations(
        [
            EquipmentReservation(
                equipment_id=equipment_id,
                booking_id=uuid4(),
                interval=interval(10, 12),
                quantity=4,
            )
        ]
    )

    assert failed.valid is False
    assert service.equipment_cache.snapshot() == before
