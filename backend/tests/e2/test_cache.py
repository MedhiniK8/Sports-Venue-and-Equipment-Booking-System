from datetime import date, datetime
from uuid import uuid4

import pytest

from app.contracts.booking import TimeInterval
from app.e2_allocation.cache import AvailabilityCache
from app.e2_allocation.models import AvailabilityInterval, AvailabilityStatus


BOOKING_DATE = date(2026, 11, 23)


def make_interval(
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
    status: AvailabilityStatus = AvailabilityStatus.FREE,
) -> AvailabilityInterval:
    return AvailabilityInterval(
        interval=TimeInterval(
            start=datetime(2026, 11, 23, start_hour, start_minute),
            end=datetime(2026, 11, 23, end_hour, end_minute),
        ),
        status=status,
    )


def test_stores_intervals_for_court_and_date():
    cache = AvailabilityCache()
    court_id = uuid4()
    intervals = [make_interval(6, 0, 7, 0), make_interval(7, 0, 8, 0)]

    cache.set_intervals(court_id, BOOKING_DATE, intervals)

    assert cache.get_intervals(court_id, BOOKING_DATE) == intervals
    assert cache.has_intervals(court_id, BOOKING_DATE)


def test_stored_intervals_are_chronologically_sorted():
    cache = AvailabilityCache()
    court_id = uuid4()
    early = make_interval(6, 0, 7, 0)
    late = make_interval(8, 0, 9, 0)

    cache.set_intervals(court_id, BOOKING_DATE, [late, early])

    assert cache.get_intervals(court_id, BOOKING_DATE) == [early, late]


def test_storing_does_not_mutate_original_list():
    cache = AvailabilityCache()
    court_id = uuid4()
    late = make_interval(8, 0, 9, 0)
    early = make_interval(6, 0, 7, 0)
    original = [late, early]

    cache.set_intervals(court_id, BOOKING_DATE, original)

    assert original == [late, early]


def test_adjacent_intervals_are_accepted():
    cache = AvailabilityCache()
    court_id = uuid4()
    adjacent = [make_interval(6, 0, 7, 0), make_interval(7, 0, 8, 0)]

    cache.set_intervals(court_id, BOOKING_DATE, adjacent)

    assert cache.get_intervals(court_id, BOOKING_DATE) == adjacent


def test_overlapping_intervals_are_rejected_without_storing_entry():
    cache = AvailabilityCache()
    court_id = uuid4()
    overlapping = [make_interval(6, 0, 7, 0), make_interval(6, 30, 7, 30)]

    with pytest.raises(ValueError, match="availability intervals must not overlap"):
        cache.set_intervals(court_id, BOOKING_DATE, overlapping)

    assert not cache.has_intervals(court_id, BOOKING_DATE)


def test_failed_replacement_preserves_existing_entry():
    cache = AvailabilityCache()
    court_id = uuid4()
    original = [make_interval(6, 0, 7, 0)]
    cache.set_intervals(court_id, BOOKING_DATE, original)

    with pytest.raises(ValueError):
        cache.set_intervals(
            court_id,
            BOOKING_DATE,
            [make_interval(8, 0, 9, 0), make_interval(8, 30, 9, 30)],
        )

    assert cache.get_intervals(court_id, BOOKING_DATE) == original


def test_get_returns_deep_defensive_copy():
    cache = AvailabilityCache()
    court_id = uuid4()
    interval = make_interval(6, 0, 7, 0)
    cache.set_intervals(court_id, BOOKING_DATE, [interval])

    result = cache.get_intervals(court_id, BOOKING_DATE)

    assert result is not None
    assert result[0] == interval
    assert result[0] is not interval
    result[0].status = AvailabilityStatus.BLOCKED
    result[0].reference_id = uuid4()
    result[0].interval.start = datetime(2026, 11, 23, 6, 30)
    result.append(make_interval(8, 0, 9, 0))
    cached = cache.get_intervals(court_id, BOOKING_DATE)
    assert cached == [interval]
    assert cached is not None
    assert cached[0].status is AvailabilityStatus.FREE
    assert cached[0].reference_id is None


def test_missing_entry_returns_none():
    cache = AvailabilityCache()

    assert cache.get_intervals(uuid4(), BOOKING_DATE) is None


def test_existence_check_for_stored_entry():
    cache = AvailabilityCache()
    court_id = uuid4()

    assert not cache.has_intervals(court_id, BOOKING_DATE)
    cache.set_intervals(court_id, BOOKING_DATE, [make_interval(6, 0, 7, 0)])
    assert cache.has_intervals(court_id, BOOKING_DATE)


def test_empty_entry_still_exists():
    cache = AvailabilityCache()
    court_id = uuid4()

    cache.set_intervals(court_id, BOOKING_DATE, [])

    assert cache.has_intervals(court_id, BOOKING_DATE)
    assert cache.get_intervals(court_id, BOOKING_DATE) == []


def test_remove_entry():
    cache = AvailabilityCache()
    court_id = uuid4()
    cache.set_intervals(court_id, BOOKING_DATE, [make_interval(6, 0, 7, 0)])

    cache.remove_intervals(court_id, BOOKING_DATE)

    assert not cache.has_intervals(court_id, BOOKING_DATE)
    assert cache.get_intervals(court_id, BOOKING_DATE) is None


def test_remove_missing_entry_is_graceful():
    cache = AvailabilityCache()
    court_id = uuid4()

    cache.remove_intervals(court_id, BOOKING_DATE)

    assert not cache.has_intervals(court_id, BOOKING_DATE)


def test_clear_removes_all_entries():
    cache = AvailabilityCache()
    first_court = uuid4()
    second_court = uuid4()
    cache.set_intervals(first_court, BOOKING_DATE, [make_interval(6, 0, 7, 0)])
    cache.set_intervals(second_court, BOOKING_DATE, [])

    cache.clear()

    assert not cache.has_intervals(first_court, BOOKING_DATE)
    assert not cache.has_intervals(second_court, BOOKING_DATE)


def test_separate_courts_have_separate_entries():
    cache = AvailabilityCache()
    first_court = uuid4()
    second_court = uuid4()
    first_intervals = [make_interval(6, 0, 7, 0)]
    second_intervals = [make_interval(8, 0, 9, 0)]
    cache.set_intervals(first_court, BOOKING_DATE, first_intervals)
    cache.set_intervals(second_court, BOOKING_DATE, second_intervals)

    assert cache.get_intervals(first_court, BOOKING_DATE) == first_intervals
    assert cache.get_intervals(second_court, BOOKING_DATE) == second_intervals


def test_separate_dates_have_separate_entries():
    cache = AvailabilityCache()
    court_id = uuid4()
    next_date = date(2026, 11, 24)
    first_intervals = [make_interval(6, 0, 7, 0)]
    second_intervals = [make_interval(8, 0, 9, 0)]
    cache.set_intervals(court_id, BOOKING_DATE, first_intervals)
    cache.set_intervals(court_id, next_date, second_intervals)

    assert cache.get_intervals(court_id, BOOKING_DATE) == first_intervals
    assert cache.get_intervals(court_id, next_date) == second_intervals
