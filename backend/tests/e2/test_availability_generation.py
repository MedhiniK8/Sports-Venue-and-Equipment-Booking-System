from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from app.contracts.booking import TimeInterval
from app.e2_allocation.availability_generation import (
    CommittedBooking,
    EffectiveCourtBlock,
    populate_seven_day_availability,
)
from app.e2_allocation.cache import AvailabilityCache
from app.e2_allocation.models import AvailabilityInterval, AvailabilityStatus


REFERENCE_DATE = date(2026, 11, 23)


def make_time_interval(
    booking_date: date,
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
) -> TimeInterval:
    return TimeInterval(
        start=datetime.combine(booking_date, time(start_hour, start_minute)),
        end=datetime.combine(booking_date, time(end_hour, end_minute)),
    )


def make_booking(
    court_id: UUID,
    booking_date: date,
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
    owner_id: UUID | None = None,
) -> CommittedBooking:
    return CommittedBooking(
        booking_id=uuid4(),
        court_id=court_id,
        owner_id=owner_id,
        interval=make_time_interval(
            booking_date, start_hour, start_minute, end_hour, end_minute
        ),
    )


def make_block(
    court_id: UUID,
    start: datetime,
    end: datetime,
) -> EffectiveCourtBlock:
    return EffectiveCourtBlock(
        block_id=uuid4(),
        court_id=court_id,
        interval=TimeInterval(start=start, end=end),
    )


def get_spans(
    cache: AvailabilityCache, court_id: UUID, booking_date: date
) -> list[tuple[datetime, datetime, AvailabilityStatus, UUID | None]]:
    intervals = cache.get_intervals(court_id, booking_date)
    assert intervals is not None
    return [
        (
            item.interval.start,
            item.interval.end,
            item.status,
            item.reference_id,
        )
        for item in intervals
    ]


def day_time(booking_date: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(booking_date, time(hour, minute))


def test_populates_all_seven_dates_for_multiple_active_courts():
    cache = AvailabilityCache()
    courts = [uuid4(), uuid4()]

    populate_seven_day_availability(cache, courts, [], [], REFERENCE_DATE)

    for court_id in courts:
        for offset in range(7):
            booking_date = REFERENCE_DATE + timedelta(days=offset)
            assert get_spans(cache, court_id, booking_date) == [
                (
                    day_time(booking_date, 6),
                    day_time(booking_date, 20),
                    AvailabilityStatus.FREE,
                    None,
                )
            ]
        assert not cache.has_intervals(court_id, REFERENCE_DATE + timedelta(days=7))


def test_court_without_bookings_or_blocks_has_full_free_day():
    cache = AvailabilityCache()
    court_id = uuid4()

    populate_seven_day_availability(cache, [court_id], [], [], REFERENCE_DATE)

    assert get_spans(cache, court_id, REFERENCE_DATE) == [
        (
            day_time(REFERENCE_DATE, 6),
            day_time(REFERENCE_DATE, 20),
            AvailabilityStatus.FREE,
            None,
        )
    ]


def test_booking_splits_free_availability():
    cache = AvailabilityCache()
    court_id = uuid4()
    booking = make_booking(court_id, REFERENCE_DATE, 10, 0, 11, 0)

    populate_seven_day_availability(
        cache, [court_id], [booking], [], REFERENCE_DATE
    )

    assert get_spans(cache, court_id, REFERENCE_DATE) == [
        (
            day_time(REFERENCE_DATE, 6),
            day_time(REFERENCE_DATE, 10),
            AvailabilityStatus.FREE,
            None,
        ),
        (
            day_time(REFERENCE_DATE, 10),
            day_time(REFERENCE_DATE, 11),
            AvailabilityStatus.BOOKED,
            booking.booking_id,
        ),
        (
            day_time(REFERENCE_DATE, 11),
            day_time(REFERENCE_DATE, 20),
            AvailabilityStatus.FREE,
            None,
        ),
    ]


def test_multiple_bookings_on_one_date_are_sorted_and_split_free_time():
    cache = AvailabilityCache()
    court_id = uuid4()
    later = make_booking(court_id, REFERENCE_DATE, 12, 0, 13, 0)
    earlier = make_booking(court_id, REFERENCE_DATE, 8, 0, 9, 0)

    populate_seven_day_availability(
        cache, [court_id], [later, earlier], [], REFERENCE_DATE
    )

    spans = get_spans(cache, court_id, REFERENCE_DATE)
    assert [span[2] for span in spans] == [
        AvailabilityStatus.FREE,
        AvailabilityStatus.BOOKED,
        AvailabilityStatus.FREE,
        AvailabilityStatus.BOOKED,
        AvailabilityStatus.FREE,
    ]
    assert spans[1][3] == earlier.booking_id
    assert spans[3][3] == later.booking_id


def test_adjacent_bookings_preserve_each_owners_identity():
    cache = AvailabilityCache()
    court_id = uuid4()
    first_owner, second_owner = uuid4(), uuid4()
    first = make_booking(
        court_id, REFERENCE_DATE, 9, 0, 10, 0, owner_id=first_owner
    )
    second = make_booking(
        court_id, REFERENCE_DATE, 10, 0, 11, 0, owner_id=second_owner
    )

    populate_seven_day_availability(
        cache, [court_id], [first, second], [], REFERENCE_DATE
    )

    intervals = cache.get_intervals(court_id, REFERENCE_DATE)
    assert intervals is not None
    booked = [item for item in intervals if item.status == AvailabilityStatus.BOOKED]
    assert [(item.interval.start.time(), item.interval.end.time(), item.owner_id) for item in booked] == [
        (time(9, 0), time(10, 0), first_owner),
        (time(10, 0), time(11, 0), second_owner),
    ]
    assert all(
        item.owner_id is None
        for item in intervals
        if item.status != AvailabilityStatus.BOOKED
    )


def test_block_splits_free_availability():
    cache = AvailabilityCache()
    court_id = uuid4()
    block = make_block(
        court_id,
        day_time(REFERENCE_DATE, 10),
        day_time(REFERENCE_DATE, 12),
    )

    populate_seven_day_availability(cache, [court_id], [], [block], REFERENCE_DATE)

    assert get_spans(cache, court_id, REFERENCE_DATE) == [
        (
            day_time(REFERENCE_DATE, 6),
            day_time(REFERENCE_DATE, 10),
            AvailabilityStatus.FREE,
            None,
        ),
        (
            day_time(REFERENCE_DATE, 10),
            day_time(REFERENCE_DATE, 12),
            AvailabilityStatus.BLOCKED,
            block.block_id,
        ),
        (
            day_time(REFERENCE_DATE, 12),
            day_time(REFERENCE_DATE, 20),
            AvailabilityStatus.FREE,
            None,
        ),
    ]


def test_booking_and_non_overlapping_block_both_affect_same_date():
    cache = AvailabilityCache()
    court_id = uuid4()
    booking = make_booking(court_id, REFERENCE_DATE, 8, 0, 9, 0)
    block = make_block(
        court_id,
        day_time(REFERENCE_DATE, 10),
        day_time(REFERENCE_DATE, 11),
    )

    populate_seven_day_availability(
        cache, [court_id], [booking], [block], REFERENCE_DATE
    )

    spans = get_spans(cache, court_id, REFERENCE_DATE)
    assert [span[2] for span in spans] == [
        AvailabilityStatus.FREE,
        AvailabilityStatus.BOOKED,
        AvailabilityStatus.FREE,
        AvailabilityStatus.BLOCKED,
        AvailabilityStatus.FREE,
    ]


def test_multi_day_block_is_split_and_clipped_to_each_operating_day():
    cache = AvailabilityCache()
    court_id = uuid4()
    next_date = REFERENCE_DATE + timedelta(days=1)
    block = make_block(
        court_id,
        day_time(REFERENCE_DATE, 19),
        day_time(next_date, 8),
    )

    populate_seven_day_availability(cache, [court_id], [], [block], REFERENCE_DATE)

    assert get_spans(cache, court_id, REFERENCE_DATE) == [
        (
            day_time(REFERENCE_DATE, 6),
            day_time(REFERENCE_DATE, 19),
            AvailabilityStatus.FREE,
            None,
        ),
        (
            day_time(REFERENCE_DATE, 19),
            day_time(REFERENCE_DATE, 20),
            AvailabilityStatus.BLOCKED,
            block.block_id,
        ),
    ]
    assert get_spans(cache, court_id, next_date) == [
        (
            day_time(next_date, 6),
            day_time(next_date, 8),
            AvailabilityStatus.BLOCKED,
            block.block_id,
        ),
        (
            day_time(next_date, 8),
            day_time(next_date, 20),
            AvailabilityStatus.FREE,
            None,
        ),
    ]


def test_operating_hour_boundaries_are_half_open():
    cache = AvailabilityCache()
    court_id = uuid4()
    booking = make_booking(court_id, REFERENCE_DATE, 6, 0, 20, 0)

    populate_seven_day_availability(
        cache, [court_id], [booking], [], REFERENCE_DATE
    )

    assert get_spans(cache, court_id, REFERENCE_DATE) == [
        (
            day_time(REFERENCE_DATE, 6),
            day_time(REFERENCE_DATE, 20),
            AvailabilityStatus.BOOKED,
            booking.booking_id,
        )
    ]


def test_touching_bookings_are_adjacent_not_conflicting():
    cache = AvailabilityCache()
    court_id = uuid4()
    first = make_booking(court_id, REFERENCE_DATE, 6, 0, 7, 0)
    second = make_booking(court_id, REFERENCE_DATE, 7, 0, 8, 0)

    populate_seven_day_availability(
        cache, [court_id], [first, second], [], REFERENCE_DATE
    )

    spans = get_spans(cache, court_id, REFERENCE_DATE)
    assert spans[0][0:3] == (
        day_time(REFERENCE_DATE, 6),
        day_time(REFERENCE_DATE, 7),
        AvailabilityStatus.BOOKED,
    )
    assert spans[1][0:3] == (
        day_time(REFERENCE_DATE, 7),
        day_time(REFERENCE_DATE, 8),
        AvailabilityStatus.BOOKED,
    )


def test_out_of_window_bookings_and_blocks_are_ignored():
    cache = AvailabilityCache()
    court_id = uuid4()
    before_window = REFERENCE_DATE - timedelta(days=1)
    after_window = REFERENCE_DATE + timedelta(days=7)
    bookings = [
        make_booking(court_id, before_window, 10, 0, 11, 0),
        make_booking(court_id, after_window, 10, 0, 11, 0),
    ]
    blocks = [
        make_block(
            court_id,
            day_time(before_window, 10),
            day_time(before_window, 11),
        ),
        make_block(
            court_id,
            day_time(after_window, 10),
            day_time(after_window, 11),
        ),
    ]

    populate_seven_day_availability(
        cache, [court_id], bookings, blocks, REFERENCE_DATE
    )

    assert get_spans(cache, court_id, REFERENCE_DATE) == [
        (
            day_time(REFERENCE_DATE, 6),
            day_time(REFERENCE_DATE, 20),
            AvailabilityStatus.FREE,
            None,
        )
    ]


def test_block_intersecting_window_is_clipped_to_window_and_operating_hours():
    cache = AvailabilityCache()
    court_id = uuid4()
    previous_date = REFERENCE_DATE - timedelta(days=1)
    block = make_block(
        court_id,
        day_time(previous_date, 19),
        day_time(REFERENCE_DATE, 7),
    )

    populate_seven_day_availability(cache, [court_id], [], [block], REFERENCE_DATE)

    assert get_spans(cache, court_id, REFERENCE_DATE)[:2] == [
        (
            day_time(REFERENCE_DATE, 6),
            day_time(REFERENCE_DATE, 7),
            AvailabilityStatus.BLOCKED,
            block.block_id,
        ),
        (
            day_time(REFERENCE_DATE, 7),
            day_time(REFERENCE_DATE, 20),
            AvailabilityStatus.FREE,
            None,
        ),
    ]


def test_block_outside_operating_hours_does_not_change_availability():
    cache = AvailabilityCache()
    court_id = uuid4()
    block = make_block(
        court_id,
        day_time(REFERENCE_DATE, 20),
        day_time(REFERENCE_DATE, 22),
    )

    populate_seven_day_availability(cache, [court_id], [], [block], REFERENCE_DATE)

    assert get_spans(cache, court_id, REFERENCE_DATE) == [
        (
            day_time(REFERENCE_DATE, 6),
            day_time(REFERENCE_DATE, 20),
            AvailabilityStatus.FREE,
            None,
        )
    ]


def test_booking_outside_operating_hours_is_rejected():
    cache = AvailabilityCache()
    court_id = uuid4()
    booking = make_booking(court_id, REFERENCE_DATE, 5, 0, 6, 0)

    with pytest.raises(ValueError, match="within court hours"):
        populate_seven_day_availability(
            cache, [court_id], [booking], [], REFERENCE_DATE
        )

    assert not cache.has_intervals(court_id, REFERENCE_DATE)


def test_booking_crossing_calendar_date_is_rejected():
    cache = AvailabilityCache()
    court_id = uuid4()
    booking = CommittedBooking(
        booking_id=uuid4(),
        court_id=court_id,
        interval=TimeInterval(
            start=day_time(REFERENCE_DATE, 19),
            end=day_time(REFERENCE_DATE + timedelta(days=1), 7),
        ),
    )

    with pytest.raises(ValueError, match="contained within one date"):
        populate_seven_day_availability(
            cache, [court_id], [booking], [], REFERENCE_DATE
        )


def test_unknown_or_inactive_court_record_is_rejected():
    cache = AvailabilityCache()
    active_court = uuid4()
    inactive_court = uuid4()
    booking = make_booking(inactive_court, REFERENCE_DATE, 10, 0, 11, 0)

    with pytest.raises(ValueError, match="unknown or inactive"):
        populate_seven_day_availability(
            cache, [active_court], [booking], [], REFERENCE_DATE
        )


def test_invalid_booking_interval_is_rejected():
    cache = AvailabilityCache()
    court_id = uuid4()
    invalid_interval = TimeInterval.model_construct(
        start=day_time(REFERENCE_DATE, 11),
        end=day_time(REFERENCE_DATE, 10),
    )
    booking = CommittedBooking.model_construct(
        booking_id=uuid4(),
        court_id=court_id,
        interval=invalid_interval,
    )

    with pytest.raises(ValueError, match="invalid interval"):
        populate_seven_day_availability(
            cache, [court_id], [booking], [], REFERENCE_DATE
        )


def test_timezone_aware_records_are_rejected():
    cache = AvailabilityCache()
    court_id = uuid4()
    booking = CommittedBooking(
        booking_id=uuid4(),
        court_id=court_id,
        interval=TimeInterval(
            start=datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc),
            end=datetime(2026, 11, 23, 11, 0, tzinfo=timezone.utc),
        ),
    )

    with pytest.raises(ValueError, match="must be naive venue-local values"):
        populate_seven_day_availability(
            cache, [court_id], [booking], [], REFERENCE_DATE
        )


@pytest.mark.parametrize(
    "conflict_type",
    ["booking-booking", "block-block", "booking-block"],
)
def test_conflicting_overlaps_are_rejected_without_partial_cache_population(
    conflict_type,
):
    cache = AvailabilityCache()
    court_id = uuid4()
    existing = make_time_interval(REFERENCE_DATE, 6, 0, 20, 0)
    cache.set_intervals(
        court_id,
        REFERENCE_DATE,
        [AvailabilityInterval(interval=existing, status=AvailabilityStatus.FREE)],
    )

    first_booking = make_booking(court_id, REFERENCE_DATE, 10, 0, 11, 0)
    second_booking = make_booking(court_id, REFERENCE_DATE, 10, 30, 11, 30)
    first_block = make_block(
        court_id, day_time(REFERENCE_DATE, 10), day_time(REFERENCE_DATE, 11)
    )
    second_block = make_block(
        court_id, day_time(REFERENCE_DATE, 10, 30), day_time(REFERENCE_DATE, 11, 30)
    )

    if conflict_type == "booking-booking":
        bookings, blocks = [first_booking, second_booking], []
    elif conflict_type == "block-block":
        bookings, blocks = [], [first_block, second_block]
    else:
        bookings, blocks = [first_booking], [first_block]

    with pytest.raises(ValueError, match="conflicting availability records overlap"):
        populate_seven_day_availability(
            cache, [court_id], bookings, blocks, REFERENCE_DATE
        )

    intervals = cache.get_intervals(court_id, REFERENCE_DATE)
    assert intervals is not None
    assert len(intervals) == 1
    assert intervals[0].status is AvailabilityStatus.FREE


def test_repeated_generation_replaces_the_same_window_entries():
    cache = AvailabilityCache()
    court_id = uuid4()
    booking = make_booking(court_id, REFERENCE_DATE, 10, 0, 11, 0)

    populate_seven_day_availability(
        cache, [court_id], [booking], [], REFERENCE_DATE
    )
    first_generation = get_spans(cache, court_id, REFERENCE_DATE)
    populate_seven_day_availability(
        cache, [court_id], [booking], [], REFERENCE_DATE
    )

    assert get_spans(cache, court_id, REFERENCE_DATE) == first_generation


def test_generation_is_deterministic_for_record_order():
    court_id = uuid4()
    booking_early = make_booking(court_id, REFERENCE_DATE, 8, 0, 9, 0)
    booking_late = make_booking(court_id, REFERENCE_DATE, 12, 0, 13, 0)
    block = make_block(
        court_id,
        day_time(REFERENCE_DATE, 10),
        day_time(REFERENCE_DATE, 11),
    )
    first_cache = AvailabilityCache()
    second_cache = AvailabilityCache()

    populate_seven_day_availability(
        first_cache,
        [court_id],
        [booking_late, booking_early],
        [block],
        REFERENCE_DATE,
    )
    populate_seven_day_availability(
        second_cache,
        [court_id],
        [booking_early, booking_late],
        [block],
        REFERENCE_DATE,
    )

    for offset in range(7):
        booking_date = REFERENCE_DATE + timedelta(days=offset)
        assert get_spans(first_cache, court_id, booking_date) == get_spans(
            second_cache, court_id, booking_date
        )
