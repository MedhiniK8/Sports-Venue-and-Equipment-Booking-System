from datetime import date, datetime
from uuid import uuid4

import pytest

from app.contracts.booking import TimeInterval
from app.e2_allocation.booking_update import apply_booking_to_cache
from app.e2_allocation.cache import AvailabilityCache
from app.e2_allocation.combined_booking import CombinedAllocationCache
from app.e2_allocation.equipment_cache import EquipmentCache
from app.e2_allocation.equipment_models import (
    EquipmentInventory,
    EquipmentRequestLine,
)
from app.e2_allocation.models import AvailabilityInterval, AvailabilityStatus


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


def make_court_cache(court_id):
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            AvailabilityInterval(
                interval=interval(6, 20),
                status=AvailabilityStatus.FREE,
            )
        ],
    )
    return cache


def make_combined(court_id):
    court_cache = make_court_cache(court_id)
    equipment_cache = EquipmentCache()
    combined = CombinedAllocationCache(court_cache, equipment_cache)
    return court_cache, equipment_cache, combined


def test_successful_combined_booking_then_cancellation():
    court_id = uuid4()
    equipment_id = uuid4()
    court_cache, equipment_cache, combined = make_combined(court_id)
    equipment_cache.set_inventory(
        EquipmentInventory(equipment_id=equipment_id, total_quantity=5)
    )
    booking_id = uuid4()
    items = (
        EquipmentRequestLine(equipment_id=equipment_id, quantity=2),
    )

    allocation = combined.allocate(
        court_id,
        BOOKING_DATE,
        interval(),
        booking_id,
        items,
        current_datetime=FIXED_NOW,
    )
    assert allocation.succeeded is True

    court_intervals = court_cache.get_intervals(court_id, BOOKING_DATE)
    assert court_intervals is not None
    assert sum(
        item.status is AvailabilityStatus.BOOKED
        and item.reference_id == booking_id
        for item in court_intervals
    ) == 1
    assert len(equipment_cache.get_reservations(
        equipment_id,
        BOOKING_DATE,
    ) or []) == 1

    cancellation = combined.cancel(
        booking_id,
        court_id,
        BOOKING_DATE,
    )
    assert cancellation.succeeded is True
    assert cancellation.court_cancelled is True
    assert cancellation.equipment_cancelled is True
    assert cancellation.cancelled_equipment_reservation_count == 1
    assert all(
        item.status is AvailabilityStatus.FREE
        for item in court_cache.get_intervals(court_id, BOOKING_DATE) or []
    )
    assert equipment_cache.get_reservations(
        equipment_id,
        BOOKING_DATE,
    ) == []


def test_combined_booking_multiple_items():
    court_id = uuid4()
    first = uuid4()
    second = uuid4()
    court_cache, equipment_cache, combined = make_combined(court_id)
    equipment_cache.set_inventory(
        EquipmentInventory(equipment_id=first, total_quantity=5)
    )
    equipment_cache.set_inventory(
        EquipmentInventory(equipment_id=second, total_quantity=3)
    )

    result = combined.allocate(
        court_id,
        BOOKING_DATE,
        interval(),
        uuid4(),
        (
            EquipmentRequestLine(equipment_id=first, quantity=2),
            EquipmentRequestLine(equipment_id=second, quantity=3),
        ),
        current_datetime=FIXED_NOW,
    )

    assert result.succeeded is True
    assert len(equipment_cache.get_reservations(first, BOOKING_DATE) or []) == 1
    assert len(equipment_cache.get_reservations(second, BOOKING_DATE) or []) == 1


def test_court_only_combined_booking_and_cancellation():
    court_id = uuid4()
    court_cache, equipment_cache, combined = make_combined(court_id)
    booking_id = uuid4()

    allocation = combined.allocate(
        court_id,
        BOOKING_DATE,
        interval(),
        booking_id,
        (),
        current_datetime=FIXED_NOW,
    )
    assert allocation.succeeded is True
    assert allocation.equipment_allocated is False

    cancellation = combined.cancel(
        booking_id,
        court_id,
        BOOKING_DATE,
    )
    assert cancellation.succeeded is True
    assert cancellation.court_cancelled is True
    assert cancellation.equipment_cancelled is False
    assert not equipment_cache.snapshot()


def test_repeated_combined_cancellation_is_safe():
    court_id = uuid4()
    court_cache, equipment_cache, combined = make_combined(court_id)
    booking_id = uuid4()
    allocation = combined.allocate(
        court_id,
        BOOKING_DATE,
        interval(),
        booking_id,
        (),
        current_datetime=FIXED_NOW,
    )
    assert allocation.succeeded is True

    first = combined.cancel(booking_id, court_id, BOOKING_DATE)
    before_court = court_cache.snapshot()
    before_equipment = equipment_cache.snapshot()
    repeated = combined.cancel(booking_id, court_id, BOOKING_DATE)

    assert first.succeeded is True
    assert repeated.succeeded is True
    assert repeated.repeated is True
    assert court_cache.snapshot() == before_court
    assert equipment_cache.snapshot() == before_equipment


def test_cancellation_restores_availability_for_subsequent_request():
    court_id = uuid4()
    equipment_id = uuid4()
    court_cache, equipment_cache, combined = make_combined(court_id)
    equipment_cache.set_inventory(
        EquipmentInventory(equipment_id=equipment_id, total_quantity=2)
    )
    first_id = uuid4()
    item = (EquipmentRequestLine(
        equipment_id=equipment_id,
        quantity=2,
    ),)
    first = combined.allocate(
        court_id,
        BOOKING_DATE,
        interval(),
        first_id,
        item,
        current_datetime=FIXED_NOW,
    )
    assert first.succeeded is True
    assert combined.cancel(
        first_id,
        court_id,
        BOOKING_DATE,
    ).succeeded is True

    second = combined.allocate(
        court_id,
        BOOKING_DATE,
        interval(),
        uuid4(),
        item,
        current_datetime=FIXED_NOW,
    )
    assert second.succeeded is True


def test_combined_cancellation_preserves_unrelated_booking():
    court_id = uuid4()
    equipment_id = uuid4()
    court_cache, equipment_cache, combined = make_combined(court_id)
    equipment_cache.set_inventory(
        EquipmentInventory(equipment_id=equipment_id, total_quantity=5)
    )
    first_id = uuid4()
    second_id = uuid4()
    item = (
        EquipmentRequestLine(equipment_id=equipment_id, quantity=1),
    )
    assert combined.allocate(
        court_id,
        BOOKING_DATE,
        interval(8, 10),
        first_id,
        item,
        current_datetime=FIXED_NOW,
    ).succeeded
    assert combined.allocate(
        court_id,
        BOOKING_DATE,
        interval(10, 12),
        second_id,
        item,
        current_datetime=FIXED_NOW,
    ).succeeded

    result = combined.cancel(first_id, court_id, BOOKING_DATE)
    assert result.succeeded is True
    reservations = equipment_cache.get_reservations(
        equipment_id,
        BOOKING_DATE,
    )
    assert reservations is not None
    assert len(reservations) == 1
    assert reservations[0].booking_id == second_id


@pytest.mark.parametrize(
    ("missing_side", "expected_error"),
    [
        ("equipment", "equipment reservations are missing"),
        ("court", "court allocation is missing"),
    ],
)
def test_missing_or_inconsistent_reservation_side_fails(
    missing_side,
    expected_error,
):
    court_id = uuid4()
    equipment_id = uuid4()
    court_cache, equipment_cache, combined = make_combined(court_id)
    equipment_cache.set_inventory(
        EquipmentInventory(equipment_id=equipment_id, total_quantity=5)
    )
    booking_id = uuid4()
    record_items = (
        EquipmentRequestLine(equipment_id=equipment_id, quantity=1),
    )

    if missing_side == "equipment":
        assert apply_booking_to_cache(
            court_id,
            BOOKING_DATE,
            interval(),
            booking_id,
            court_cache,
            current_datetime=FIXED_NOW,
        ).valid
        combined._bookings[booking_id] = __import__(
            "app.e2_allocation.combined_booking",
            fromlist=["CombinedBookingRecord"],
        ).CombinedBookingRecord(
            booking_id=booking_id,
            court_id=court_id,
            booking_date=BOOKING_DATE,
            interval=interval(),
            items=record_items,
        )
    else:
        from app.e2_allocation.equipment_allocation import allocate_equipment
        from app.e2_allocation.equipment_models import EquipmentAllocationRequest
        allocate_equipment(
            EquipmentAllocationRequest(
                booking_id=booking_id,
                court_id=court_id,
                interval=interval(),
                items=record_items,
            ),
            equipment_cache,
            current_datetime=FIXED_NOW,
        )

    result = combined.cancel(booking_id, court_id, BOOKING_DATE)

    assert result.succeeded is False
    assert expected_error in " ".join(result.errors)


def test_duplicate_court_booking_reference_is_ambiguous():
    court_id = uuid4()
    court_cache, equipment_cache, combined = make_combined(court_id)
    booking_id = uuid4()
    court_cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            AvailabilityInterval(
                interval=interval(8, 9),
                status=AvailabilityStatus.BOOKED,
                reference_id=booking_id,
            ),
            AvailabilityInterval(
                interval=interval(10, 11),
                status=AvailabilityStatus.BOOKED,
                reference_id=booking_id,
            ),
        ],
    )

    result = combined.cancel(booking_id, court_id, BOOKING_DATE)

    assert result.succeeded is False
    assert "Duplicate or ambiguous court" in result.errors[0]


def test_unknown_booking_and_invalid_request_fail_safely():
    court_id = uuid4()
    court_cache, equipment_cache, combined = make_combined(court_id)
    before_court = court_cache.snapshot()
    before_equipment = equipment_cache.snapshot()

    unknown = combined.cancel(uuid4(), court_id, BOOKING_DATE)
    invalid = combined.cancel(None, court_id, BOOKING_DATE)

    assert unknown.succeeded is False
    assert invalid.succeeded is False
    assert court_cache.snapshot() == before_court
    assert equipment_cache.snapshot() == before_equipment


def test_combined_cancellation_staging_failure_preserves_snapshots(monkeypatch):
    court_id = uuid4()
    equipment_id = uuid4()
    court_cache, equipment_cache, combined = make_combined(court_id)
    equipment_cache.set_inventory(
        EquipmentInventory(equipment_id=equipment_id, total_quantity=5)
    )
    booking_id = uuid4()
    assert combined.allocate(
        court_id,
        BOOKING_DATE,
        interval(),
        booking_id,
        (
            EquipmentRequestLine(equipment_id=equipment_id, quantity=2),
        ),
        current_datetime=FIXED_NOW,
    ).succeeded
    before_court = court_cache.snapshot()
    before_equipment = equipment_cache.snapshot()

    def fail_batch(*args, **kwargs):
        raise ValueError("injected staged cache failure")

    monkeypatch.setattr(
        equipment_cache,
        "batch_replace_reservations",
        fail_batch,
    )

    result = combined.cancel(booking_id, court_id, BOOKING_DATE)

    assert result.succeeded is False
    assert "atomically" in result.errors[0]
    assert court_cache.snapshot() == before_court
    assert equipment_cache.snapshot() == before_equipment


def test_combined_allocation_equipment_shortage_preserves_court_cache():
    court_id = uuid4()
    equipment_id = uuid4()
    court_cache, equipment_cache, combined = make_combined(court_id)
    equipment_cache.set_inventory(
        EquipmentInventory(equipment_id=equipment_id, total_quantity=1)
    )
    before_court = court_cache.snapshot()
    before_equipment = equipment_cache.snapshot()

    result = combined.allocate(
        court_id,
        BOOKING_DATE,
        interval(),
        uuid4(),
        (
            EquipmentRequestLine(equipment_id=equipment_id, quantity=2),
        ),
        current_datetime=FIXED_NOW,
    )

    assert result.succeeded is False
    assert len(result.shortages) == 1
    assert court_cache.snapshot() == before_court
    assert equipment_cache.snapshot() == before_equipment


def test_combined_allocation_court_failure_preserves_equipment_cache():
    court_id = uuid4()
    equipment_id = uuid4()
    court_cache, equipment_cache, combined = make_combined(court_id)
    equipment_cache.set_inventory(
        EquipmentInventory(equipment_id=equipment_id, total_quantity=5)
    )
    before_equipment = equipment_cache.snapshot()

    result = combined.allocate(
        court_id,
        BOOKING_DATE,
        interval(20, 21),
        uuid4(),
        (
            EquipmentRequestLine(equipment_id=equipment_id, quantity=1),
        ),
        current_datetime=FIXED_NOW,
    )

    assert result.succeeded is False
    assert "Court allocation failed" in " ".join(result.errors)
    assert equipment_cache.snapshot() == before_equipment


def test_combined_allocation_staging_failure_preserves_snapshots(monkeypatch):
    court_id = uuid4()
    equipment_id = uuid4()
    court_cache, equipment_cache, combined = make_combined(court_id)
    equipment_cache.set_inventory(
        EquipmentInventory(equipment_id=equipment_id, total_quantity=5)
    )
    before_court = court_cache.snapshot()
    before_equipment = equipment_cache.snapshot()

    def fail_batch(*args, **kwargs):
        raise ValueError("injected combined allocation failure")

    monkeypatch.setattr(
        equipment_cache,
        "batch_replace_reservations",
        fail_batch,
    )

    result = combined.allocate(
        court_id,
        BOOKING_DATE,
        interval(),
        uuid4(),
        (
            EquipmentRequestLine(equipment_id=equipment_id, quantity=1),
        ),
        current_datetime=FIXED_NOW,
    )

    assert result.succeeded is False
    assert "atomically" in result.errors[0]
    assert court_cache.snapshot() == before_court
    assert equipment_cache.snapshot() == before_equipment


def test_staged_court_copy_is_deeply_isolated():
    court_id = uuid4()
    court_cache = make_court_cache(court_id)
    staged = court_cache.copy()
    original = court_cache.get_intervals(court_id, BOOKING_DATE)
    staged_intervals = staged.get_intervals(court_id, BOOKING_DATE)
    assert original is not None
    assert staged_intervals is not None

    staged_intervals[0].status = AvailabilityStatus.BLOCKED
    staged_intervals.append(
        AvailabilityInterval(
            interval=interval(4, 5),
            status=AvailabilityStatus.BOOKED,
            reference_id=uuid4(),
        )
    )

    assert court_cache.get_intervals(court_id, BOOKING_DATE) == original


def test_staged_equipment_copy_is_deeply_isolated():
    equipment_id = uuid4()
    equipment_cache = EquipmentCache()
    equipment_cache.set_inventory(
        EquipmentInventory(equipment_id=equipment_id, total_quantity=5)
    )
    booking_id = uuid4()
    from app.e2_allocation.equipment_models import EquipmentReservation
    equipment_cache.set_reservations(
        equipment_id,
        BOOKING_DATE,
        [
            EquipmentReservation(
                equipment_id=equipment_id,
                booking_id=booking_id,
                interval=interval(),
                quantity=1,
            )
        ],
    )
    staged = equipment_cache.copy()
    staged_reservations = staged.get_reservations(equipment_id, BOOKING_DATE)
    assert staged_reservations is not None

    staged_reservations[0].quantity = 4

    original = equipment_cache.get_reservations(equipment_id, BOOKING_DATE)
    assert original is not None
    assert original[0].quantity == 1


@pytest.mark.parametrize(
    ("court_id_change", "interval_change", "equipment_change", "quantity_change"),
    [
        (True, False, False, False),
        (False, True, False, False),
        (False, False, True, False),
        (False, False, False, True),
    ],
)
def test_booking_id_reuse_with_different_data_is_rejected(
    court_id_change,
    interval_change,
    equipment_change,
    quantity_change,
):
    court_id = uuid4()
    court_cache, equipment_cache, combined = make_combined(court_id)
    equipment_id = uuid4()
    other_equipment_id = uuid4()
    equipment_cache.set_inventory(
        EquipmentInventory(equipment_id=equipment_id, total_quantity=5)
    )
    equipment_cache.set_inventory(
        EquipmentInventory(equipment_id=other_equipment_id, total_quantity=5)
    )
    booking_id = uuid4()
    original_items = (
        EquipmentRequestLine(equipment_id=equipment_id, quantity=2),
    )
    assert combined.allocate(
        court_id,
        BOOKING_DATE,
        interval(),
        booking_id,
        original_items,
        current_datetime=FIXED_NOW,
    ).succeeded

    retried_court = uuid4() if court_id_change else court_id
    retried_interval = interval(12, 14) if interval_change else interval()
    retried_equipment = (
        other_equipment_id if equipment_change else equipment_id
    )
    retried_quantity = 3 if quantity_change else 2
    if retried_court != court_id:
        court_cache.set_intervals(
            retried_court,
            BOOKING_DATE,
            [
                AvailabilityInterval(
                    interval=interval(6, 20),
                    status=AvailabilityStatus.FREE,
                )
            ],
        )

    before_court = court_cache.snapshot()
    before_equipment = equipment_cache.snapshot()
    result = combined.allocate(
        retried_court,
        BOOKING_DATE,
        retried_interval,
        booking_id,
        (
            EquipmentRequestLine(
                equipment_id=retried_equipment,
                quantity=retried_quantity,
            ),
        ),
        current_datetime=FIXED_NOW,
    )

    assert result.succeeded is False
    assert court_cache.snapshot() == before_court
    assert equipment_cache.snapshot() == before_equipment


def test_allocation_retry_after_cancellation_is_rejected():
    court_id = uuid4()
    equipment_id = uuid4()
    court_cache, equipment_cache, combined = make_combined(court_id)
    equipment_cache.set_inventory(
        EquipmentInventory(equipment_id=equipment_id, total_quantity=5)
    )
    booking_id = uuid4()
    items = (
        EquipmentRequestLine(equipment_id=equipment_id, quantity=1),
    )
    assert combined.allocate(
        court_id,
        BOOKING_DATE,
        interval(),
        booking_id,
        items,
        current_datetime=FIXED_NOW,
    ).succeeded
    assert combined.cancel(
        booking_id,
        court_id,
        BOOKING_DATE,
    ).succeeded

    before_court = court_cache.snapshot()
    before_equipment = equipment_cache.snapshot()
    result = combined.allocate(
        court_id,
        BOOKING_DATE,
        interval(),
        booking_id,
        items,
        current_datetime=FIXED_NOW,
    )

    assert result.succeeded is False
    assert "marked cancelled" in " ".join(result.errors)
    assert court_cache.snapshot() == before_court
    assert equipment_cache.snapshot() == before_equipment


def test_repeated_cancellation_rejects_reintroduced_booking_claims():
    court_id = uuid4()
    equipment_id = uuid4()
    court_cache, equipment_cache, combined = make_combined(court_id)
    equipment_cache.set_inventory(
        EquipmentInventory(equipment_id=equipment_id, total_quantity=5)
    )
    booking_id = uuid4()
    items = (
        EquipmentRequestLine(equipment_id=equipment_id, quantity=1),
    )
    assert combined.allocate(
        court_id,
        BOOKING_DATE,
        interval(),
        booking_id,
        items,
        current_datetime=FIXED_NOW,
    ).succeeded
    assert combined.cancel(
        booking_id,
        court_id,
        BOOKING_DATE,
    ).succeeded

    assert apply_booking_to_cache(
        court_id,
        BOOKING_DATE,
        interval(),
        booking_id,
        court_cache,
        current_datetime=FIXED_NOW,
    ).valid
    before_court = court_cache.snapshot()
    before_equipment = equipment_cache.snapshot()
    result = combined.cancel(booking_id, court_id, BOOKING_DATE)

    assert result.succeeded is False
    assert "reintroduced" in " ".join(result.errors)
    assert court_cache.snapshot() == before_court
    assert equipment_cache.snapshot() == before_equipment


def test_cancellation_retry_after_staging_failure_succeeds(monkeypatch):
    court_id = uuid4()
    equipment_id = uuid4()
    court_cache, equipment_cache, combined = make_combined(court_id)
    equipment_cache.set_inventory(
        EquipmentInventory(equipment_id=equipment_id, total_quantity=5)
    )
    booking_id = uuid4()
    assert combined.allocate(
        court_id,
        BOOKING_DATE,
        interval(),
        booking_id,
        (
            EquipmentRequestLine(equipment_id=equipment_id, quantity=1),
        ),
        current_datetime=FIXED_NOW,
    ).succeeded
    before_court = court_cache.snapshot()
    before_equipment = equipment_cache.snapshot()

    monkeypatch.setattr(
        equipment_cache,
        "batch_replace_reservations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("simulated cancellation failure")
        ),
    )
    failed = combined.cancel(booking_id, court_id, BOOKING_DATE)
    assert failed.succeeded is False
    assert court_cache.snapshot() == before_court
    assert equipment_cache.snapshot() == before_equipment

    monkeypatch.undo()
    retried = combined.cancel(booking_id, court_id, BOOKING_DATE)
    assert retried.succeeded is True
    reservations = equipment_cache.get_reservations(
        equipment_id,
        BOOKING_DATE,
    )
    assert reservations == []
    inventory = equipment_cache.get_inventory(equipment_id)
    assert inventory is not None
    assert inventory.total_quantity == 5


def test_court_commit_restore_failure_rolls_back_equipment(monkeypatch):
    court_id = uuid4()
    equipment_id = uuid4()
    court_cache, equipment_cache, combined = make_combined(court_id)
    equipment_cache.set_inventory(
        EquipmentInventory(equipment_id=equipment_id, total_quantity=5)
    )
    before_court = court_cache.snapshot()
    before_equipment = equipment_cache.snapshot()

    def fail_restore(snapshot):
        court_cache.set_intervals(
            court_id,
            BOOKING_DATE,
            [
                AvailabilityInterval(
                    interval=interval(8, 9),
                    status=AvailabilityStatus.BOOKED,
                    reference_id=uuid4(),
                )
            ],
        )
        raise RuntimeError("simulated court commit failure")

    monkeypatch.setattr(
        court_cache,
        "restore_snapshot",
        fail_restore,
    )

    result = combined.allocate(
        court_id,
        BOOKING_DATE,
        interval(),
        uuid4(),
        (
            EquipmentRequestLine(equipment_id=equipment_id, quantity=1),
        ),
        current_datetime=FIXED_NOW,
    )

    assert result.succeeded is False
    assert court_cache.snapshot() == before_court
    assert equipment_cache.snapshot() == before_equipment
