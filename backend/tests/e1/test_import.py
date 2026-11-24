from datetime import datetime

import pytest
from pydantic import ValidationError

from app.contracts.booking import TimeInterval
from app.e1_concurrency.service import (
    ConcurrencyService,
    intervals_overlap,
    lock_conflicts,
)


def make_interval(start_hour: int, start_minute: int, end_hour: int, end_minute: int) -> TimeInterval:
    return TimeInterval(
        start=datetime(2026, 11, 23, start_hour, start_minute),
        end=datetime(2026, 11, 23, end_hour, end_minute),
    )


def test_e1_service_imports():
    assert ConcurrencyService is not None


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (make_interval(8, 0, 10, 0), make_interval(9, 0, 11, 0), True),
        (make_interval(8, 0, 9, 0), make_interval(9, 0, 10, 0), False),
        (make_interval(8, 0, 10, 0), make_interval(8, 0, 10, 0), True),
        (make_interval(6, 0, 8, 0), make_interval(18, 0, 20, 0), False),
        (make_interval(8, 0, 12, 0), make_interval(9, 0, 10, 0), True),
    ],
)
def test_interval_overlap(left, right, expected):
    assert intervals_overlap(left, right) is expected


def test_lock_conflict_requires_same_court():
    left = make_interval(8, 0, 10, 0)
    right = make_interval(9, 0, 11, 0)

    assert lock_conflicts(left, "court-1", right, "court-1") is True
    assert lock_conflicts(left, "court-1", right, "court-2") is False


def test_lock_conflict_requires_same_booking_date():
    left = make_interval(8, 0, 10, 0)
    right = TimeInterval(
        start=datetime(2026, 11, 24, 9, 0),
        end=datetime(2026, 11, 24, 11, 0),
    )

    assert lock_conflicts(left, "court-1", right, "court-1") is False


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (datetime(2026, 11, 23, 10, 0), datetime(2026, 11, 23, 9, 0)),
        (datetime(2026, 11, 23, 9, 0, 30), datetime(2026, 11, 23, 10, 0)),
    ],
)
def test_invalid_interval_boundaries_are_rejected(start, end):
    with pytest.raises(ValidationError):
        TimeInterval(start=start, end=end)
