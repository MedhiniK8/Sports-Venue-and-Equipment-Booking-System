from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.contracts.booking import TimeInterval, ValidationResult
from app.e2_allocation.cache import AvailabilityCache
from app.e2_allocation.models import AvailabilityInterval, AvailabilityStatus
from app.e2_allocation.validation import validate_booking_availability


BOOKING_DATE = date(2026, 11, 23)
FIXED_NOW = datetime(2026, 11, 23, 5, 0)


@pytest.fixture
def court_id():
    return uuid4()

@pytest.fixture
def availability_cache():
    return AvailabilityCache()


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
) -> AvailabilityInterval:
    return AvailabilityInterval(
        interval=make_time_interval(
            start_hour, start_minute, end_hour, end_minute
        ),
        status=status,
    )


def validate(
    court_id: UUID,
    availability_cache: AvailabilityCache,
    requested_interval: TimeInterval,
    booking_date: date = BOOKING_DATE,
    current_datetime: datetime = FIXED_NOW,
) -> ValidationResult:
    return validate_booking_availability(
        court_id,
        booking_date,
        requested_interval,
        availability_cache,
        current_datetime=current_datetime,
    )


def test_accepts_booking_entirely_inside_free_interval(
    court_id, availability_cache
):
    availability_cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(10, 0, 12, 0, AvailabilityStatus.FREE)],
    )

    result = validate(
        court_id, availability_cache, make_time_interval(10, 30, 11, 30)
    )

    assert result.valid is True
    assert result.errors == []


@pytest.mark.parametrize(
    "status",
    [AvailabilityStatus.BOOKED, AvailabilityStatus.BLOCKED],
)
def test_rejects_booking_inside_unavailable_interval(
    court_id, availability_cache, status
):
    availability_cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(10, 0, 12, 0, status)],
    )

    result = validate(
        court_id, availability_cache, make_time_interval(10, 30, 11, 30)
    )

    assert result.valid is False
    assert status.value in result.errors[0]


@pytest.mark.parametrize(
    "status",
    [AvailabilityStatus.BOOKED, AvailabilityStatus.BLOCKED],
)
def test_rejects_booking_overlapping_unavailable_interval(
    court_id, availability_cache, status
):
    availability_cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_availability_interval(10, 0, 11, 0, AvailabilityStatus.FREE),
            make_availability_interval(11, 0, 12, 0, status),
        ],
    )

    result = validate(
        court_id, availability_cache, make_time_interval(10, 30, 11, 30)
    )

    assert result.valid is False
    assert status.value in result.errors[0]


def test_rejects_booking_partially_outside_available_intervals(
    court_id, availability_cache
):
    availability_cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(10, 0, 11, 0, AvailabilityStatus.FREE)],
    )

    result = validate(
        court_id, availability_cache, make_time_interval(9, 30, 10, 30)
    )

    assert result.valid is False
    assert "covered" in result.errors[0]


@pytest.mark.parametrize(
    ("start_hour", "start_minute", "end_hour", "end_minute"),
    [(5, 30, 6, 30), (19, 30, 20, 30)],
)
def test_rejects_booking_outside_operating_hours(
    court_id,
    availability_cache,
    start_hour,
    start_minute,
    end_hour,
    end_minute,
):
    availability_cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(6, 0, 20, 0, AvailabilityStatus.FREE)],
    )

    result = validate(
        court_id,
        availability_cache,
        make_time_interval(start_hour, start_minute, end_hour, end_minute),
    )

    assert result.valid is False
    assert "06:00-20:00" in result.errors[0]


def test_time_interval_contract_rejects_invalid_start_end_ordering():
    with pytest.raises(ValidationError, match="end must be after start"):
        make_time_interval(11, 0, 10, 0)


def test_validation_returns_failure_for_invalid_time_interval(
    court_id, availability_cache
):
    invalid_interval = TimeInterval.model_construct(
        start=datetime(2026, 11, 23, 11, 0),
        end=datetime(2026, 11, 23, 10, 0),
    )

    result = validate(court_id, availability_cache, invalid_interval)

    assert result.valid is False
    assert "end must be after start" in result.errors[0]


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (
            datetime(2026, 11, 23, 10, 0, 1),
            datetime(2026, 11, 23, 10, 30),
        ),
        (
            datetime(2026, 11, 23, 10, 0, 0, 1),
            datetime(2026, 11, 23, 10, 30),
        ),
    ],
)
def test_time_interval_contract_rejects_invalid_minute_precision(start, end):
    with pytest.raises(ValidationError):
        TimeInterval(start=start, end=end)


def test_validation_returns_failure_for_invalid_minute_precision(
    court_id, availability_cache
):
    invalid_interval = TimeInterval.model_construct(
        start=datetime(2026, 11, 23, 10, 0, 1),
        end=datetime(2026, 11, 23, 10, 30),
    )

    result = validate(court_id, availability_cache, invalid_interval)

    assert result.valid is False
    assert "one-minute precision" in result.errors[0]


def test_rejects_missing_court_date_cache_entry(
    court_id, availability_cache
):
    result = validate(
        court_id, availability_cache, make_time_interval(10, 0, 11, 0)
    )

    assert result.valid is False
    assert "No availability data" in result.errors[0]


def test_accepts_request_at_exact_free_interval_start(
    court_id, availability_cache
):
    availability_cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(10, 0, 11, 0, AvailabilityStatus.FREE)],
    )

    result = validate(
        court_id, availability_cache, make_time_interval(10, 0, 10, 30)
    )

    assert result.valid is True


def test_accepts_request_ending_at_exact_free_interval_end(
    court_id, availability_cache
):
    availability_cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(10, 0, 11, 0, AvailabilityStatus.FREE)],
    )

    result = validate(
        court_id, availability_cache, make_time_interval(10, 30, 11, 0)
    )

    assert result.valid is True


def test_rejects_booking_across_adjacent_free_and_booked_intervals(
    court_id, availability_cache
):
    availability_cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_availability_interval(10, 0, 11, 0, AvailabilityStatus.FREE),
            make_availability_interval(11, 0, 12, 0, AvailabilityStatus.BOOKED),
        ],
    )

    result = validate(
        court_id, availability_cache, make_time_interval(10, 30, 11, 30)
    )

    assert result.valid is False
    assert "BOOKED" in result.errors[0]


def test_rejects_booking_across_adjacent_free_and_blocked_intervals(
    court_id, availability_cache
):
    availability_cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_availability_interval(10, 0, 11, 0, AvailabilityStatus.FREE),
            make_availability_interval(11, 0, 12, 0, AvailabilityStatus.BLOCKED),
        ],
    )

    result = validate(
        court_id, availability_cache, make_time_interval(10, 30, 11, 30)
    )

    assert result.valid is False
    assert "BLOCKED" in result.errors[0]


def test_rejects_booking_that_extends_into_a_gap(court_id, availability_cache):
    availability_cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [
            make_availability_interval(10, 0, 11, 0, AvailabilityStatus.FREE),
            make_availability_interval(11, 30, 12, 0, AvailabilityStatus.FREE),
        ],
    )

    result = validate(
        court_id, availability_cache, make_time_interval(10, 30, 11, 45)
    )

    assert result.valid is False
    assert "covered" in result.errors[0]


def test_does_not_treat_missing_date_as_available(
    court_id, availability_cache
):
    availability_cache.set_intervals(
        court_id,
        date(2026, 11, 24),
        [make_availability_interval(10, 0, 12, 0, AvailabilityStatus.FREE)],
    )

    result = validate(
        court_id, availability_cache, make_time_interval(10, 30, 11, 0)
    )

    assert result.valid is False
    assert "No availability data" in result.errors[0]


@pytest.mark.parametrize(
    ("start_hour", "start_minute", "end_hour", "end_minute"),
    [
        (18, 0, 19, 0),
        (19, 0, 19, 30),
        (19, 20, 19, 40),
        (19, 19, 19, 20),
    ],
)
def test_rejects_elapsed_or_started_slots_without_changing_cache(
    court_id,
    availability_cache,
    start_hour,
    start_minute,
    end_hour,
    end_minute,
):
    availability_cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(6, 0, 20, 0, AvailabilityStatus.FREE)],
    )
    before = availability_cache.get_intervals(court_id, BOOKING_DATE)

    result = validate(
        court_id,
        availability_cache,
        make_time_interval(start_hour, start_minute, end_hour, end_minute),
        current_datetime=datetime(2026, 11, 23, 19, 20),
    )

    assert result.valid is False
    assert "already started or passed" in result.errors[0]
    assert availability_cache.get_intervals(court_id, BOOKING_DATE) == before


def test_rejects_past_date():
    court_id = uuid4()
    past_date = BOOKING_DATE - timedelta(days=1)
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        past_date,
        [
            AvailabilityInterval(
                interval=make_time_interval(10, 0, 11, 0, past_date),
                status=AvailabilityStatus.FREE,
            )
        ],
    )

    result = validate(
        court_id,
        cache,
        make_time_interval(10, 0, 11, 0, past_date),
        booking_date=past_date,
        current_datetime=datetime(2026, 11, 23, 19, 20),
    )

    assert result.valid is False
    assert "date is in the past" in result.errors[0]


def test_accepts_interval_starting_one_minute_after_now():
    court_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(6, 0, 20, 0, AvailabilityStatus.FREE)],
    )

    result = validate(
        court_id,
        cache,
        make_time_interval(19, 21, 19, 40),
        current_datetime=datetime(2026, 11, 23, 19, 20),
    )

    assert result.valid is True


def test_accepts_future_date_if_slot_is_free():
    court_id = uuid4()
    future_date = BOOKING_DATE + timedelta(days=1)
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

    result = validate(
        court_id,
        cache,
        make_time_interval(6, 0, 8, 0, future_date),
        booking_date=future_date,
        current_datetime=datetime(2026, 11, 23, 19, 20),
    )

    assert result.valid is True


def test_rejects_timezone_aware_now():
    court_id = uuid4()
    cache = AvailabilityCache()
    cache.set_intervals(
        court_id,
        BOOKING_DATE,
        [make_availability_interval(6, 0, 20, 0, AvailabilityStatus.FREE)],
    )

    result = validate(
        court_id,
        cache,
        make_time_interval(10, 0, 11, 0),
        current_datetime=datetime(2026, 11, 23, 5, 0, tzinfo=timezone.utc),
    )

    assert result.valid is False
    assert "naive venue-local" in result.errors[0]
