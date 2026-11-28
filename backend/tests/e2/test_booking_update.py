from datetime import date, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.contracts.booking import TimeInterval, ValidationResult
from app.e2_allocation.booking_update import apply_booking_to_cache
from app.e2_allocation.cache import AvailabilityCache
from app.e2_allocation.models import AvailabilityInterval, AvailabilityStatus


BOOKING_DATE = date(2026, 11, 23)
FIXED_NOW = datetime(2026, 11, 23, 5, 0)


def make_time_interval(
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
) -> TimeInterval:
    return TimeInterval(
        start=datetime(2026, 11, 23, start_hour, start_minute),
        end=datetime(2026, 11, 23, end_hour, end_minute),
    )


def make_availability_interval(
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
    status: AvailabilityStatus,
    reference_id: UUID | None = None,
) -> AvailabilityInterval:
    return AvailabilityInterval(
        interval=make_time_interval(
            start_hour, start_minute, end_hour, end_minute
        ),
        status=status,
        reference_id=reference_id,
    )


def apply_booking(
    court_id: UUID,
    cache: AvailabilityCache,
    requested_interval: TimeInterval,
    booking_id: UUID | None = None,
    current_datetime: datetime = FIXED_NOW,
) -> ValidationResult:
    return apply_booking_to_cache(
        court_id,
        BOOKING_DATE,
        requested_interval,
        booking_id or uuid4(),
        cache,
        current_datetime=current_datetime,
    )


def spans(cache: AvailabilityCache, court_id: UUID) -> list[AvailabilityInterval]:
    intervals = cache.get_intervals(court_id, BOOKING_DATE)
    assert intervals is not None
    return intervals


def test_booking_splits_free_interval_into_before_booked_and_after():
    court_id = uuid4()
    booking_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(8, 0, 12, 0, AvailabilityStatus.FREE)],
    )

    result = apply_booking(
        court_id, cache, make_time_interval(10, 0, 11, 0), booking_id
    )

    assert result.valid is True
    assert [
        (item.interval.start, item.interval.end, item.status, item.reference_id)
        for item in spans(cache, court_id)
    ] == [
        (
            datetime(2026, 11, 23, 8, 0),
            datetime(2026, 11, 23, 10, 0),
            AvailabilityStatus.FREE,
            None,
        ),
        (
            datetime(2026, 11, 23, 10, 0),
            datetime(2026, 11, 23, 11, 0),
            AvailabilityStatus.BOOKED,
            booking_id,
        ),
        (
            datetime(2026, 11, 23, 11, 0),
            datetime(2026, 11, 23, 12, 0),
            AvailabilityStatus.FREE,
            None,
        ),
    ]


def test_booking_at_free_interval_start_keeps_only_after_remainder():
    court_id = uuid4()
    booking_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(8, 0, 10, 0, AvailabilityStatus.FREE)],
    )

    result = apply_booking(
        court_id, cache, make_time_interval(8, 0, 9, 0), booking_id
    )

    assert result.valid is True
    assert [(item.interval.start.hour, item.interval.end.hour, item.status) for item in spans(cache, court_id)] == [
        (8, 9, AvailabilityStatus.BOOKED),
        (9, 10, AvailabilityStatus.FREE),
    ]
    assert spans(cache, court_id)[0].reference_id == booking_id


def test_booking_at_free_interval_end_keeps_only_before_remainder():
    court_id = uuid4()
    booking_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(8, 0, 10, 0, AvailabilityStatus.FREE)],
    )

    result = apply_booking(
        court_id, cache, make_time_interval(9, 0, 10, 0), booking_id
    )

    assert result.valid is True
    assert [(item.interval.start.hour, item.interval.end.hour, item.status) for item in spans(cache, court_id)] == [
        (8, 9, AvailabilityStatus.FREE),
        (9, 10, AvailabilityStatus.BOOKED),
    ]
    assert spans(cache, court_id)[1].reference_id == booking_id


def test_booking_occupying_entire_free_interval_replaces_it():
    court_id = uuid4()
    booking_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(8, 0, 10, 0, AvailabilityStatus.FREE)],
    )

    result = apply_booking(
        court_id, cache, make_time_interval(8, 0, 10, 0), booking_id
    )

    assert result.valid is True
    intervals = spans(cache, court_id)
    assert len(intervals) == 1
    assert intervals[0].status is AvailabilityStatus.BOOKED
    assert intervals[0].reference_id == booking_id
    assert intervals[0].interval == make_time_interval(8, 0, 10, 0)


def test_booking_spanning_adjacent_free_intervals_creates_one_booked_interval():
    court_id = uuid4()
    booking_id = uuid4()
    cache = AvailabilityCache()
    existing_booked = make_availability_interval(
        12, 0, 14, 0, AvailabilityStatus.BOOKED, uuid4()
    )
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_availability_interval(6, 0, 10, 0, AvailabilityStatus.FREE),
            make_availability_interval(10, 0, 12, 0, AvailabilityStatus.FREE),
            existing_booked,
        ],
    )

    result = apply_booking(
        court_id, cache, make_time_interval(9, 0, 11, 0), booking_id
    )

    assert result.valid is True
    intervals = spans(cache, court_id)
    assert [
        (item.interval.start.hour, item.interval.end.hour, item.status)
        for item in intervals
    ] == [
        (6, 9, AvailabilityStatus.FREE),
        (9, 11, AvailabilityStatus.BOOKED),
        (11, 12, AvailabilityStatus.FREE),
        (12, 14, AvailabilityStatus.BOOKED),
    ]
    assert intervals[1].reference_id == booking_id
    assert intervals[3] == existing_booked


@pytest.mark.parametrize(
    ("boundary_status", "boundary_hour"),
    [
        (AvailabilityStatus.BOOKED, 10),
        (AvailabilityStatus.BLOCKED, 10),
    ],
)
def test_booking_touching_existing_unavailable_boundary_preserves_it(
    boundary_status, boundary_hour
):
    court_id = uuid4()
    booking_id = uuid4()
    boundary_id = uuid4()
    cache = AvailabilityCache()
    boundary = make_availability_interval(
        boundary_hour,
        0,
        12,
        0,
        boundary_status,
        boundary_id,
    )
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_availability_interval(
                8, 0, boundary_hour, 0, AvailabilityStatus.FREE
            ),
            boundary,
        ],
    )

    result = apply_booking(
        court_id,
        cache,
        make_time_interval(9, 0, boundary_hour, 0),
        booking_id,
    )

    assert result.valid is True
    intervals = spans(cache, court_id)
    assert intervals[-1] == boundary
    assert intervals[-2].status is AvailabilityStatus.BOOKED
    assert intervals[-2].reference_id == booking_id


def test_preserves_unaffected_booked_and_blocked_intervals():
    court_id = uuid4()
    booking_id = uuid4()
    existing_booked = make_availability_interval(
        6, 0, 8, 0, AvailabilityStatus.BOOKED, uuid4()
    )
    blocked = make_availability_interval(
        12, 0, 14, 0, AvailabilityStatus.BLOCKED, uuid4()
    )
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            existing_booked,
            make_availability_interval(8, 0, 12, 0, AvailabilityStatus.FREE),
            blocked,
        ],
    )

    result = apply_booking(
        court_id, cache, make_time_interval(9, 0, 10, 0), booking_id
    )

    assert result.valid is True
    intervals = spans(cache, court_id)
    assert intervals[0] == existing_booked
    assert intervals[-1] == blocked


def test_validation_failure_leaves_cache_unchanged():
    court_id = uuid4()
    existing = make_availability_interval(
        8, 0, 10, 0, AvailabilityStatus.BOOKED, uuid4()
    )
    cache = AvailabilityCache()
    cache.set_intervals(court_id, BOOKING_DATE, [existing])
    before = spans(cache, court_id)

    result = apply_booking(
        court_id, cache, make_time_interval(8, 30, 9, 0)
    )

    assert result.valid is False
    assert spans(cache, court_id) == before


def test_missing_cache_entry_returns_failure_without_creating_entry():
    court_id = uuid4()
    cache = AvailabilityCache()

    result = apply_booking(
        court_id, cache, make_time_interval(8, 0, 9, 0)
    )

    assert result.valid is False
    assert cache.has_intervals(court_id, BOOKING_DATE) is False


def test_invalid_booking_interval_returns_failure_without_modifying_cache():
    court_id = uuid4()
    existing = make_availability_interval(
        8, 0, 10, 0, AvailabilityStatus.FREE
    )
    cache = AvailabilityCache()
    cache.set_intervals(court_id, BOOKING_DATE, [existing])
    before = spans(cache, court_id)
    invalid_interval = TimeInterval.model_construct(
        start=datetime(2026, 11, 23, 9, 0),
        end=datetime(2026, 11, 23, 8, 0),
    )

    result = apply_booking(court_id, cache, invalid_interval)

    assert result.valid is False
    assert spans(cache, court_id) == before


def test_result_intervals_remain_sorted_and_non_overlapping():
    court_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(6, 0, 12, 0, AvailabilityStatus.FREE)],
    )

    result = apply_booking(
        court_id, cache, make_time_interval(8, 0, 10, 0)
    )

    assert result.valid is True
    intervals = spans(cache, court_id)
    assert intervals == sorted(
        intervals, key=lambda item: item.interval.start
    )
    assert all(
        left.interval.end <= right.interval.start
        for left, right in zip(intervals, intervals[1:])
    )


def test_booking_id_is_assigned_once_and_repeated_request_is_rejected():
    court_id = uuid4()
    booking_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(6, 0, 12, 0, AvailabilityStatus.FREE)],
    )
    requested_interval = make_time_interval(8, 0, 9, 0)

    first_result = apply_booking(court_id, cache, requested_interval, booking_id)
    second_result = apply_booking(court_id, cache, requested_interval, booking_id)

    assert first_result.valid is True
    assert second_result.valid is False
    intervals = spans(cache, court_id)
    assert sum(
        item.status is AvailabilityStatus.BOOKED
        and item.reference_id == booking_id
        for item in intervals
    ) == 1


def test_booking_update_rejects_elapsed_slot_without_changing_cache():
    court_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(6, 0, 20, 0, AvailabilityStatus.FREE)],
    )
    before = spans(cache, court_id)

    result = apply_booking(
        court_id,
        cache,
        make_time_interval(10, 0, 11, 0),
        current_datetime=datetime(2026, 11, 23, 10, 0),
    )

    assert result.valid is False
    assert "already started or passed" in result.errors[0]
    assert spans(cache, court_id) == before
