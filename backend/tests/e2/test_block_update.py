from datetime import date, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.contracts.booking import TimeInterval, ValidationResult
from app.e2_allocation.block_update import apply_block_to_cache
from app.e2_allocation.cache import AvailabilityCache
from app.e2_allocation.models import AvailabilityInterval, AvailabilityStatus


BOOKING_DATE = date(2026, 11, 23)
FIXED_NOW = datetime(2026, 11, 23, 5, 0)


def make_time_interval(
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
    booking_date: date = BOOKING_DATE,
) -> TimeInterval:
    return TimeInterval(
        start=datetime(
            booking_date.year,
            booking_date.month,
            booking_date.day,
            start_hour,
            start_minute,
        ),
        end=datetime(
            booking_date.year,
            booking_date.month,
            booking_date.day,
            end_hour,
            end_minute,
        ),
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


def apply_block(
    court_id: UUID,
    cache: AvailabilityCache,
    requested_interval: TimeInterval,
    block_id: UUID | None = None,
    booking_date: date = BOOKING_DATE,
    current_datetime: datetime = FIXED_NOW,
) -> ValidationResult:
    return apply_block_to_cache(
        court_id,
        booking_date,
        requested_interval,
        block_id or uuid4(),
        cache,
        current_datetime=current_datetime,
    )


def intervals_for(
    cache: AvailabilityCache, court_id: UUID, booking_date: date = BOOKING_DATE
) -> list[AvailabilityInterval]:
    intervals = cache.get_intervals(court_id, booking_date)
    assert intervals is not None
    return intervals


def test_block_in_middle_splits_free_interval_and_sets_reference():
    court_id = uuid4()
    block_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(6, 0, 12, 0, AvailabilityStatus.FREE)],
    )

    result = apply_block(
        court_id, cache, make_time_interval(9, 0, 11, 0), block_id
    )

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert [
        (item.interval.start.hour, item.interval.end.hour, item.status)
        for item in intervals
    ] == [
        (6, 9, AvailabilityStatus.FREE),
        (9, 11, AvailabilityStatus.BLOCKED),
        (11, 12, AvailabilityStatus.FREE),
    ]
    assert intervals[1].reference_id == block_id


def test_block_at_free_interval_beginning_keeps_after_remainder():
    court_id = uuid4()
    block_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(8, 0, 10, 0, AvailabilityStatus.FREE)],
    )

    result = apply_block(
        court_id, cache, make_time_interval(8, 0, 9, 0), block_id
    )

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert [
        (item.interval.start.hour, item.interval.end.hour, item.status)
        for item in intervals
    ] == [
        (8, 9, AvailabilityStatus.BLOCKED),
        (9, 10, AvailabilityStatus.FREE),
    ]
    assert intervals[0].reference_id == block_id


def test_block_at_free_interval_end_keeps_before_remainder():
    court_id = uuid4()
    block_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(8, 0, 10, 0, AvailabilityStatus.FREE)],
    )

    result = apply_block(
        court_id, cache, make_time_interval(9, 0, 10, 0), block_id
    )

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert [
        (item.interval.start.hour, item.interval.end.hour, item.status)
        for item in intervals
    ] == [
        (8, 9, AvailabilityStatus.FREE),
        (9, 10, AvailabilityStatus.BLOCKED),
    ]
    assert intervals[1].reference_id == block_id


def test_block_occupying_entire_free_interval_replaces_it():
    court_id = uuid4()
    block_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(8, 0, 10, 0, AvailabilityStatus.FREE)],
    )

    result = apply_block(
        court_id, cache, make_time_interval(8, 0, 10, 0), block_id
    )

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert len(intervals) == 1
    assert intervals[0].status is AvailabilityStatus.BLOCKED
    assert intervals[0].reference_id == block_id
    assert intervals[0].interval == make_time_interval(8, 0, 10, 0)


def test_block_spanning_adjacent_free_intervals_creates_one_blocked_interval():
    court_id = uuid4()
    block_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_availability_interval(6, 0, 10, 0, AvailabilityStatus.FREE),
            make_availability_interval(10, 0, 12, 0, AvailabilityStatus.FREE),
        ],
    )

    result = apply_block(
        court_id, cache, make_time_interval(9, 0, 11, 0), block_id
    )

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert [
        (item.interval.start.hour, item.interval.end.hour, item.status)
        for item in intervals
    ] == [
        (6, 9, AvailabilityStatus.FREE),
        (9, 11, AvailabilityStatus.BLOCKED),
        (11, 12, AvailabilityStatus.FREE),
    ]
    assert intervals[1].reference_id == block_id


def test_block_spanning_multiple_free_intervals_preserves_partial_edges():
    court_id = uuid4()
    block_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_availability_interval(6, 0, 9, 0, AvailabilityStatus.FREE),
            make_availability_interval(9, 0, 10, 0, AvailabilityStatus.FREE),
            make_availability_interval(10, 0, 12, 0, AvailabilityStatus.FREE),
        ],
    )

    result = apply_block(
        court_id, cache, make_time_interval(8, 0, 11, 0), block_id
    )

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert [
        (item.interval.start.hour, item.interval.end.hour, item.status)
        for item in intervals
    ] == [
        (6, 8, AvailabilityStatus.FREE),
        (8, 11, AvailabilityStatus.BLOCKED),
        (11, 12, AvailabilityStatus.FREE),
    ]
    assert intervals[1].reference_id == block_id


def test_block_replaces_an_entire_booked_interval():
    court_id = uuid4()
    booking_id = uuid4()
    block_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_availability_interval(
                8, 0, 10, 0, AvailabilityStatus.BOOKED, booking_id
            )
        ],
    )

    result = apply_block(
        court_id, cache, make_time_interval(8, 0, 10, 0), block_id
    )

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert len(intervals) == 1
    assert intervals[0].status is AvailabilityStatus.BLOCKED
    assert intervals[0].reference_id == block_id
    assert intervals[0].interval == make_time_interval(8, 0, 10, 0)


def test_block_spanning_free_and_booked_intervals_creates_one_block():
    court_id = uuid4()
    booking_id = uuid4()
    block_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_availability_interval(8, 0, 9, 0, AvailabilityStatus.FREE),
            make_availability_interval(
                9, 0, 11, 0, AvailabilityStatus.BOOKED, booking_id
            ),
            make_availability_interval(11, 0, 12, 0, AvailabilityStatus.FREE),
        ],
    )

    result = apply_block(
        court_id, cache, make_time_interval(8, 30, 11, 30), block_id
    )

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert [
        (
            item.interval.start.hour,
            item.interval.start.minute,
            item.interval.end.hour,
            item.interval.end.minute,
            item.status,
        )
        for item in intervals
    ] == [
        (8, 0, 8, 30, AvailabilityStatus.FREE),
        (8, 30, 11, 30, AvailabilityStatus.BLOCKED),
        (11, 30, 12, 0, AvailabilityStatus.FREE),
    ]
    assert intervals[1].reference_id == block_id


def test_partial_booked_override_preserves_outside_booking_portions():
    court_id = uuid4()
    booking_id = uuid4()
    block_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_availability_interval(
                8, 0, 12, 0, AvailabilityStatus.BOOKED, booking_id
            )
        ],
    )

    result = apply_block(
        court_id, cache, make_time_interval(9, 0, 11, 0), block_id
    )

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert [
        (item.interval.start.hour, item.interval.end.hour, item.status)
        for item in intervals
    ] == [
        (8, 9, AvailabilityStatus.BOOKED),
        (9, 11, AvailabilityStatus.BLOCKED),
        (11, 12, AvailabilityStatus.BOOKED),
    ]
    assert intervals[0].reference_id == booking_id
    assert intervals[2].reference_id == booking_id
    assert intervals[1].reference_id == block_id


def test_block_spanning_multiple_free_and_booked_intervals_preserves_edges():
    court_id = uuid4()
    first_booking_id = uuid4()
    second_booking_id = uuid4()
    block_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_availability_interval(6, 0, 8, 0, AvailabilityStatus.FREE),
            make_availability_interval(
                8, 0, 9, 0, AvailabilityStatus.BOOKED, first_booking_id
            ),
            make_availability_interval(9, 0, 10, 0, AvailabilityStatus.FREE),
            make_availability_interval(
                10, 0, 12, 0, AvailabilityStatus.BOOKED, second_booking_id
            ),
            make_availability_interval(12, 0, 14, 0, AvailabilityStatus.FREE),
        ],
    )

    result = apply_block(
        court_id, cache, make_time_interval(7, 0, 13, 0), block_id
    )

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert [
        (item.interval.start.hour, item.interval.end.hour, item.status)
        for item in intervals
    ] == [
        (6, 7, AvailabilityStatus.FREE),
        (7, 13, AvailabilityStatus.BLOCKED),
        (13, 14, AvailabilityStatus.FREE),
    ]
    assert intervals[1].reference_id == block_id


def test_block_adjacent_to_existing_blocked_interval_does_not_merge_blocks():
    court_id = uuid4()
    block_id = uuid4()
    existing_block_id = uuid4()
    existing_block = make_availability_interval(
        10, 0, 12, 0, AvailabilityStatus.BLOCKED, existing_block_id
    )
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_availability_interval(6, 0, 10, 0, AvailabilityStatus.FREE),
            existing_block,
        ],
    )

    result = apply_block(
        court_id, cache, make_time_interval(8, 0, 10, 0), block_id
    )

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert intervals[1].status is AvailabilityStatus.BLOCKED
    assert intervals[1].reference_id == block_id
    assert intervals[2] == existing_block


def test_block_adjacent_to_existing_booking_preserves_booking():
    court_id = uuid4()
    block_id = uuid4()
    booking_id = uuid4()
    booking = make_availability_interval(
        10, 0, 12, 0, AvailabilityStatus.BOOKED, booking_id
    )
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_availability_interval(6, 0, 10, 0, AvailabilityStatus.FREE),
            booking,
        ],
    )

    result = apply_block(
        court_id, cache, make_time_interval(8, 0, 10, 0), block_id
    )

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert intervals[1].status is AvailabilityStatus.BLOCKED
    assert intervals[1].reference_id == block_id
    assert intervals[2] == booking


def test_overlap_with_existing_block_is_rejected_without_changes():
    court_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_availability_interval(6, 0, 8, 0, AvailabilityStatus.FREE),
            make_availability_interval(
                8,
                0,
                10,
                0,
                AvailabilityStatus.BLOCKED,
                uuid4(),
            ),
        ],
    )
    before = intervals_for(cache, court_id)

    result = apply_block(
        court_id, cache, make_time_interval(7, 0, 9, 0)
    )

    assert result.valid is False
    assert "BLOCKED" in result.errors[0]
    assert intervals_for(cache, court_id) == before


def test_block_over_a_gap_is_rejected_without_changes():
    court_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_availability_interval(6, 0, 8, 0, AvailabilityStatus.FREE),
            make_availability_interval(9, 0, 11, 0, AvailabilityStatus.FREE),
        ],
    )
    before = intervals_for(cache, court_id)

    result = apply_block(
        court_id, cache, make_time_interval(7, 0, 10, 0)
    )

    assert result.valid is False
    assert "covered" in result.errors[0]
    assert intervals_for(cache, court_id) == before


def test_missing_cache_entry_returns_failure_without_creating_entry():
    court_id = uuid4()
    cache = AvailabilityCache()

    result = apply_block(
        court_id, cache, make_time_interval(8, 0, 9, 0)
    )

    assert result.valid is False
    assert "No availability data" in result.errors[0]
    assert cache.has_intervals(court_id, BOOKING_DATE) is False


def test_invalid_reversed_interval_returns_failure_without_changes():
    court_id = uuid4()
    cache = AvailabilityCache()
    existing = make_availability_interval(
        6, 0, 12, 0, AvailabilityStatus.FREE
    )
    cache.set_intervals(court_id, BOOKING_DATE, [existing])
    before = intervals_for(cache, court_id)
    invalid_interval = TimeInterval.model_construct(
        start=datetime(2026, 11, 23, 10, 0),
        end=datetime(2026, 11, 23, 9, 0),
    )

    result = apply_block(court_id, cache, invalid_interval)

    assert result.valid is False
    assert "end must be after start" in result.errors[0]
    assert intervals_for(cache, court_id) == before


def test_zero_duration_interval_returns_failure_without_changes():
    court_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(6, 0, 12, 0, AvailabilityStatus.FREE)],
    )
    before = intervals_for(cache, court_id)
    invalid_interval = TimeInterval.model_construct(
        start=datetime(2026, 11, 23, 9, 0),
        end=datetime(2026, 11, 23, 9, 0),
    )

    result = apply_block(court_id, cache, invalid_interval)

    assert result.valid is False
    assert "end must be after start" in result.errors[0]
    assert intervals_for(cache, court_id) == before


@pytest.mark.parametrize(
    ("start_hour", "start_minute", "end_hour", "end_minute"),
    [(5, 0, 6, 0), (19, 0, 20, 1)],
)
def test_interval_outside_operating_hours_returns_failure_without_changes(
    start_hour, start_minute, end_hour, end_minute
):
    court_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(6, 0, 20, 0, AvailabilityStatus.FREE)],
    )
    before = intervals_for(cache, court_id)

    result = apply_block(
        court_id,
        cache,
        make_time_interval(start_hour, start_minute, end_hour, end_minute),
    )

    assert result.valid is False
    assert "06:00-20:00" in result.errors[0]
    assert intervals_for(cache, court_id) == before


def test_interval_on_different_date_returns_failure_without_changes():
    court_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(6, 0, 20, 0, AvailabilityStatus.FREE)],
    )
    before = intervals_for(cache, court_id)
    other_date_interval = make_time_interval(
        8,
        0,
        9,
        0,
        date(2026, 11, 24),
    )

    result = apply_block(court_id, cache, other_date_interval)

    assert result.valid is False
    assert "selected booking date" in result.errors[0]
    assert intervals_for(cache, court_id) == before


def test_block_on_past_date_is_rejected_without_changes():
    court_id = uuid4()
    past_date = BOOKING_DATE - timedelta(days=1)
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        past_date,
        [
            AvailabilityInterval(
                interval=make_time_interval(6, 0, 20, 0, past_date),
                status=AvailabilityStatus.FREE,
            )
        ],
    )
    before = intervals_for(cache, court_id, past_date)

    result = apply_block(
        court_id,
        cache,
        make_time_interval(8, 0, 9, 0, past_date),
        booking_date=past_date,
    )

    assert result.valid is False
    assert "date is in the past" in result.errors[0]
    assert intervals_for(cache, court_id, past_date) == before


@pytest.mark.parametrize(
    ("start_hour", "start_minute", "end_hour", "end_minute"),
    [(10, 0, 12, 0), (10, 30, 12, 0), (10, 0, 10, 45)],
)
def test_block_starting_in_the_past_or_already_started_is_rejected(
    start_hour, start_minute, end_hour, end_minute
):
    court_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_availability_interval(6, 0, 20, 0, AvailabilityStatus.FREE)
        ],
    )
    before = intervals_for(cache, court_id)

    result = apply_block(
        court_id,
        cache,
        make_time_interval(start_hour, start_minute, end_hour, end_minute),
        current_datetime=datetime(2026, 11, 23, 10, 30),
    )

    assert result.valid is False
    assert "already started or passed" in result.errors[0]
    assert intervals_for(cache, court_id) == before


def test_future_block_on_current_date_succeeds():
    court_id = uuid4()
    block_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_availability_interval(6, 0, 20, 0, AvailabilityStatus.FREE)
        ],
    )

    result = apply_block(
        court_id,
        cache,
        make_time_interval(11, 0, 12, 0),
        block_id,
        current_datetime=datetime(2026, 11, 23, 10, 30),
    )

    assert result.valid is True
    assert any(
        item.status is AvailabilityStatus.BLOCKED
        and item.reference_id == block_id
        for item in intervals_for(cache, court_id)
    )


def test_block_on_future_date_succeeds():
    court_id = uuid4()
    future_date = BOOKING_DATE + timedelta(days=1)
    block_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        future_date,
        [
            AvailabilityInterval(
                interval=make_time_interval(6, 0, 20, 0, future_date),
                status=AvailabilityStatus.FREE,
            )
        ],
    )

    result = apply_block(
        court_id,
        cache,
        make_time_interval(11, 0, 12, 0, future_date),
        block_id,
        booking_date=future_date,
        current_datetime=datetime(2026, 11, 23, 23, 0),
    )

    assert result.valid is True


def test_duplicate_block_id_is_rejected_without_changes():
    court_id = uuid4()
    block_id = uuid4()
    cache = AvailabilityCache()
    existing_block = make_availability_interval(
        6, 0, 7, 0, AvailabilityStatus.BLOCKED, block_id
    )
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            existing_block,
            make_availability_interval(7, 0, 12, 0, AvailabilityStatus.FREE),
        ],
    )
    before = intervals_for(cache, court_id)

    result = apply_block(
        court_id,
        cache,
        make_time_interval(8, 0, 9, 0),
        block_id,
    )

    assert result.valid is False
    assert "Block ID already exists" in result.errors[0]
    assert intervals_for(cache, court_id) == before


def test_unaffected_bookings_and_blocks_keep_their_references():
    court_id = uuid4()
    booking_id = uuid4()
    block_id = uuid4()
    new_block_id = uuid4()
    booking = make_availability_interval(
        6, 0, 8, 0, AvailabilityStatus.BOOKED, booking_id
    )
    existing_block = make_availability_interval(
        12, 0, 14, 0, AvailabilityStatus.BLOCKED, block_id
    )
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            booking,
            make_availability_interval(8, 0, 12, 0, AvailabilityStatus.FREE),
            existing_block,
        ],
    )

    result = apply_block(
        court_id, cache, make_time_interval(9, 0, 10, 0), new_block_id
    )

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert intervals[0] == booking
    assert intervals[-1] == existing_block
    assert intervals[2].status is AvailabilityStatus.BLOCKED
    assert intervals[2].reference_id == new_block_id


def test_unaffected_adjacent_free_intervals_are_not_merged():
    court_id = uuid4()
    block_id = uuid4()
    first_free = make_availability_interval(
        6, 0, 7, 0, AvailabilityStatus.FREE
    )
    second_free = make_availability_interval(
        7, 0, 8, 0, AvailabilityStatus.FREE
    )
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            first_free,
            second_free,
            make_availability_interval(8, 0, 10, 0, AvailabilityStatus.FREE),
        ],
    )

    result = apply_block(
        court_id, cache, make_time_interval(9, 0, 10, 0), block_id
    )

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert intervals[0] == first_free
    assert intervals[1] == second_free


def test_final_intervals_are_sorted_and_non_overlapping():
    court_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_availability_interval(6, 0, 12, 0, AvailabilityStatus.FREE),
            make_availability_interval(12, 0, 14, 0, AvailabilityStatus.BOOKED, uuid4()),
        ],
    )

    result = apply_block(
        court_id, cache, make_time_interval(8, 0, 10, 0)
    )

    assert result.valid is True
    intervals = intervals_for(cache, court_id)
    assert intervals == sorted(
        intervals, key=lambda item: item.interval.start
    )
    assert all(
        left.interval.end <= right.interval.start
        for left, right in zip(intervals, intervals[1:])
    )


def test_cache_is_unchanged_on_validation_failure():
    court_id = uuid4()
    existing = make_availability_interval(
        8, 0, 10, 0, AvailabilityStatus.BLOCKED, uuid4()
    )
    cache = AvailabilityCache()
    cache.set_intervals(court_id, BOOKING_DATE, [existing])
    before = intervals_for(cache, court_id)

    result = apply_block(
        court_id, cache, make_time_interval(8, 30, 9, 0)
    )

    assert result.valid is False
    assert intervals_for(cache, court_id) == before
