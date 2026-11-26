from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts.booking import TimeInterval
from app.e2_allocation.models import AvailabilityInterval, AvailabilityStatus


def make_interval() -> TimeInterval:
    return TimeInterval(
        start=datetime(2026, 11, 23, 18, 0),
        end=datetime(2026, 11, 23, 18, 30),
    )


def test_create_free_interval():
    interval = AvailabilityInterval(
        interval=make_interval(),
        status=AvailabilityStatus.FREE,
    )

    assert interval.status is AvailabilityStatus.FREE
    assert interval.reference_id is None


def test_create_booked_interval_with_reference():
    reference_id = uuid4()
    interval = AvailabilityInterval(
        interval=make_interval(),
        status=AvailabilityStatus.BOOKED,
        reference_id=reference_id,
    )

    assert interval.status is AvailabilityStatus.BOOKED
    assert interval.reference_id == reference_id


def test_create_blocked_interval_with_reference():
    reference_id = uuid4()
    interval = AvailabilityInterval(
        interval=make_interval(),
        status=AvailabilityStatus.BLOCKED,
        reference_id=reference_id,
    )

    assert interval.status is AvailabilityStatus.BLOCKED
    assert interval.reference_id == reference_id


@pytest.mark.parametrize(
    "status",
    [AvailabilityStatus.BOOKED, AvailabilityStatus.BLOCKED],
)
def test_reference_id_is_optional_for_booked_and_blocked(status):
    interval = AvailabilityInterval(interval=make_interval(), status=status)

    assert interval.reference_id is None


def test_free_interval_rejects_reference_id():
    with pytest.raises(ValidationError, match="FREE intervals cannot have a reference ID"):
        AvailabilityInterval(
            interval=make_interval(),
            status=AvailabilityStatus.FREE,
            reference_id=uuid4(),
        )


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (datetime(2026, 11, 23, 18, 0), datetime(2026, 11, 23, 18, 0)),
        (datetime(2026, 11, 23, 18, 30), datetime(2026, 11, 23, 18, 0)),
        (
            datetime(2026, 11, 23, 18, 0, 1),
            datetime(2026, 11, 23, 18, 30),
        ),
        (
            datetime(2026, 11, 23, 18, 0, 0, 1),
            datetime(2026, 11, 23, 18, 30),
        ),
    ],
)
def test_rejects_invalid_time_interval(start, end):
    with pytest.raises(ValidationError):
        AvailabilityInterval(
            interval=TimeInterval(start=start, end=end),
            status=AvailabilityStatus.FREE,
        )


def test_rejects_unknown_status():
    with pytest.raises(ValidationError):
        AvailabilityInterval(interval=make_interval(), status="MAINTENANCE")


def test_status_values():
    assert [status.value for status in AvailabilityStatus] == [
        "FREE",
        "BOOKED",
        "BLOCKED",
    ]
