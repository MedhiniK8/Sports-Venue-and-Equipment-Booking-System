from datetime import date, datetime
from uuid import UUID, uuid4

import pytest

from app.contracts.booking import TimeInterval, ValidationResult
from app.e2_allocation.cache import AvailabilityCache
from app.e2_allocation.cancellation import cancel_booking_from_cache
from app.e2_allocation.models import AvailabilityInterval, AvailabilityStatus


BOOKING_DATE = date(2026, 11, 23)


def make_interval(
    start_hour: int,
    end_hour: int,
    status: AvailabilityStatus,
    reference_id: UUID | None = None,
) -> AvailabilityInterval:
    return AvailabilityInterval(
        interval=TimeInterval(
            start=datetime(2026, 11, 23, start_hour, 0),
            end=datetime(2026, 11, 23, end_hour, 0),
        ),
        status=status,
        reference_id=reference_id,
    )


def cancel(
    court_id: UUID,
    cache: AvailabilityCache,
    booking_id: UUID,
) -> ValidationResult:
    return cancel_booking_from_cache(
        court_id,
        BOOKING_DATE,
        booking_id,
        cache,
    )


def intervals_for(
    cache: AvailabilityCache, court_id: UUID
) -> list[AvailabilityInterval]:
    intervals = cache.get_intervals(court_id, BOOKING_DATE)
    assert intervals is not None
    return intervals


def test_cancellation_merges_free_intervals_on_both_sides():
    court_id = uuid4()
    booking_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_interval(6, 8, AvailabilityStatus.FREE),
            make_interval(8, 10, AvailabilityStatus.BOOKED, booking_id),
            make_interval(10, 12, AvailabilityStatus.FREE),
        ],
    )

    result = cancel(court_id, cache, booking_id)

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert len(intervals) == 1
    assert intervals[0].interval == TimeInterval(
        start=datetime(2026, 11, 23, 6, 0),
        end=datetime(2026, 11, 23, 12, 0),
    )
    assert intervals[0].status is AvailabilityStatus.FREE
    assert intervals[0].reference_id is None


def test_cancellation_merges_with_free_interval_on_left_only():
    court_id = uuid4()
    booking_id = uuid4()
    next_booking_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_interval(6, 8, AvailabilityStatus.FREE),
            make_interval(8, 10, AvailabilityStatus.BOOKED, booking_id),
            make_interval(10, 12, AvailabilityStatus.BOOKED, next_booking_id),
        ],
    )

    result = cancel(court_id, cache, booking_id)

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert [(item.interval.start.hour, item.interval.end.hour, item.status) for item in intervals] == [
        (6, 10, AvailabilityStatus.FREE),
        (10, 12, AvailabilityStatus.BOOKED),
    ]
    assert intervals[1].reference_id == next_booking_id


def test_cancellation_merges_with_free_interval_on_right_only():
    court_id = uuid4()
    previous_booking_id = uuid4()
    booking_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_interval(6, 8, AvailabilityStatus.BOOKED, previous_booking_id),
            make_interval(8, 10, AvailabilityStatus.BOOKED, booking_id),
            make_interval(10, 12, AvailabilityStatus.FREE),
        ],
    )

    result = cancel(court_id, cache, booking_id)

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert [(item.interval.start.hour, item.interval.end.hour, item.status) for item in intervals] == [
        (6, 8, AvailabilityStatus.BOOKED),
        (8, 12, AvailabilityStatus.FREE),
    ]
    assert intervals[0].reference_id == previous_booking_id
    assert intervals[1].reference_id is None


def test_cancellation_without_adjacent_free_intervals_keeps_only_cancelled_span_free():
    court_id = uuid4()
    booking_id = uuid4()
    blocked_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_interval(6, 8, AvailabilityStatus.BOOKED, uuid4()),
            make_interval(8, 10, AvailabilityStatus.BOOKED, booking_id),
            make_interval(10, 12, AvailabilityStatus.BLOCKED, blocked_id),
        ],
    )

    result = cancel(court_id, cache, booking_id)

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert [item.status for item in intervals] == [
        AvailabilityStatus.BOOKED,
        AvailabilityStatus.FREE,
        AvailabilityStatus.BLOCKED,
    ]
    assert intervals[1].interval == make_interval(
        8, 10, AvailabilityStatus.FREE
    ).interval
    assert intervals[2].reference_id == blocked_id


def test_cancellation_of_entire_cached_interval_makes_it_free():
    court_id = uuid4()
    booking_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_interval(6, 20, AvailabilityStatus.BOOKED, booking_id)],
    )

    result = cancel(court_id, cache, booking_id)

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert len(intervals) == 1
    assert intervals[0].status is AvailabilityStatus.FREE
    assert intervals[0].reference_id is None
    assert intervals[0].interval.start == datetime(2026, 11, 23, 6, 0)
    assert intervals[0].interval.end == datetime(2026, 11, 23, 20, 0)


def test_cancellation_next_to_blocked_interval_does_not_merge_across_it():
    court_id = uuid4()
    block_id = uuid4()
    booking_id = uuid4()
    cache = AvailabilityCache()
    blocked = make_interval(8, 9, AvailabilityStatus.BLOCKED, block_id)
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            blocked,
            make_interval(9, 10, AvailabilityStatus.BOOKED, booking_id),
            make_interval(10, 11, AvailabilityStatus.FREE),
        ],
    )

    result = cancel(court_id, cache, booking_id)

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert intervals[0] == blocked
    assert intervals[1].interval.start == datetime(2026, 11, 23, 9, 0)
    assert intervals[1].interval.end == datetime(2026, 11, 23, 11, 0)
    assert intervals[1].status is AvailabilityStatus.FREE


def test_cancellation_next_to_another_booking_does_not_merge_across_it():
    court_id = uuid4()
    booking_id = uuid4()
    other_booking_id = uuid4()
    cache = AvailabilityCache()
    other_booking = make_interval(
        10, 12, AvailabilityStatus.BOOKED, other_booking_id
    )
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_interval(8, 10, AvailabilityStatus.BOOKED, booking_id),
            other_booking,
        ],
    )

    result = cancel(court_id, cache, booking_id)

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert intervals[0].status is AvailabilityStatus.FREE
    assert intervals[0].interval.start == datetime(2026, 11, 23, 8, 0)
    assert intervals[0].interval.end == datetime(2026, 11, 23, 10, 0)
    assert intervals[1] == other_booking


def test_missing_cache_entry_returns_failure():
    court_id = uuid4()
    cache = AvailabilityCache()

    result = cancel(court_id, cache, uuid4())

    assert result.valid is False
    assert "No availability data" in result.errors[0]
    assert cache.has_intervals(court_id, BOOKING_DATE) is False


def test_booking_id_not_found_returns_failure_without_changing_cache():
    court_id = uuid4()
    cache = AvailabilityCache()
    existing = make_interval(8, 10, AvailabilityStatus.BOOKED, uuid4())
    cache.set_intervals(court_id, BOOKING_DATE, [existing])
    before = intervals_for(cache, court_id)

    result = cancel(court_id, cache, uuid4())

    assert result.valid is False
    assert "not found" in result.errors[0]
    assert intervals_for(cache, court_id) == before


def test_matching_booking_id_on_non_booked_interval_is_not_cancelled():
    court_id = uuid4()
    block_id = uuid4()
    cache = AvailabilityCache()
    blocked = make_interval(8, 10, AvailabilityStatus.BLOCKED, block_id)
    cache.set_intervals(court_id, BOOKING_DATE, [blocked])

    result = cancel(court_id, cache, block_id)

    assert result.valid is False
    assert "does not belong to a BOOKED interval" in result.errors[0]
    assert intervals_for(cache, court_id) == [blocked]


def test_duplicate_matching_booking_references_are_ambiguous():
    court_id = uuid4()
    booking_id = uuid4()
    cache = AvailabilityCache()
    original = [
        make_interval(8, 9, AvailabilityStatus.BOOKED, booking_id),
        make_interval(10, 11, AvailabilityStatus.BOOKED, booking_id),
    ]
    cache.set_intervals(court_id, BOOKING_DATE, original)
    before = intervals_for(cache, court_id)

    result = cancel(court_id, cache, booking_id)

    assert result.valid is False
    assert "ambiguous" in result.errors[0]
    assert intervals_for(cache, court_id) == before


def test_unrelated_bookings_and_blocks_are_preserved():
    court_id = uuid4()
    booking_id = uuid4()
    other_booking = make_interval(
        6, 8, AvailabilityStatus.BOOKED, uuid4()
    )
    block = make_interval(12, 14, AvailabilityStatus.BLOCKED, uuid4())
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            other_booking,
            make_interval(8, 10, AvailabilityStatus.BOOKED, booking_id),
            block,
        ],
    )

    result = cancel(court_id, cache, booking_id)

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert intervals[0] == other_booking
    assert intervals[-1] == block


def test_only_exact_matching_booking_is_cancelled():
    court_id = uuid4()
    booking_id = uuid4()
    other_booking_id = uuid4()
    cache = AvailabilityCache()
    other_booking = make_interval(
        10, 12, AvailabilityStatus.BOOKED, other_booking_id
    )
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_interval(8, 10, AvailabilityStatus.BOOKED, booking_id),
            other_booking,
        ],
    )

    result = cancel(court_id, cache, booking_id)

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert intervals[0].status is AvailabilityStatus.FREE
    assert intervals[1] == other_booking
    assert intervals[1].reference_id == other_booking_id


def test_adjacent_free_intervals_created_by_cancellation_are_merged():
    court_id = uuid4()
    booking_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_interval(6, 7, AvailabilityStatus.FREE),
            make_interval(7, 8, AvailabilityStatus.FREE),
            make_interval(8, 9, AvailabilityStatus.BOOKED, booking_id),
            make_interval(9, 10, AvailabilityStatus.FREE),
            make_interval(10, 11, AvailabilityStatus.FREE),
        ],
    )

    result = cancel(court_id, cache, booking_id)

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert len(intervals) == 1
    assert intervals[0].status is AvailabilityStatus.FREE
    assert intervals[0].interval.start == datetime(2026, 11, 23, 6, 0)
    assert intervals[0].interval.end == datetime(2026, 11, 23, 11, 0)


def test_final_intervals_are_sorted_and_non_overlapping():
    court_id = uuid4()
    booking_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_interval(6, 8, AvailabilityStatus.FREE),
            make_interval(8, 10, AvailabilityStatus.BOOKED, booking_id),
            make_interval(10, 12, AvailabilityStatus.FREE),
            make_interval(13, 14, AvailabilityStatus.BLOCKED, uuid4()),
        ],
    )

    result = cancel(court_id, cache, booking_id)

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert intervals == sorted(
        intervals, key=lambda item: item.interval.start
    )
    assert all(
        left.interval.end <= right.interval.start
        for left, right in zip(intervals, intervals[1:])
    )


def test_cache_is_unchanged_on_duplicate_reference_failure():
    court_id = uuid4()
    booking_id = uuid4()
    cache = AvailabilityCache()
    original = [
        make_interval(8, 9, AvailabilityStatus.BOOKED, booking_id),
        make_interval(10, 11, AvailabilityStatus.BOOKED, booking_id),
    ]
    cache.set_intervals(court_id, BOOKING_DATE, original)
    before = intervals_for(cache, court_id)

    result = cancel(court_id, cache, booking_id)

    assert result.valid is False
    assert intervals_for(cache, court_id) == before
