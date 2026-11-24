from datetime import date, datetime
from uuid import UUID

from pydantic import ValidationError

from ..contracts.booking import TimeInterval, ValidationResult
from .cache import AvailabilityCache
from .interval_utils import find_interval_containing
from .models import AvailabilityStatus


_OPENING_MINUTE = 6 * 60
_CLOSING_MINUTE = 20 * 60


def validate_booking_availability(
    court_id: UUID,
    booking_date: date,
    requested_interval: TimeInterval,
    availability_cache: AvailabilityCache,
    current_datetime: datetime | None = None,
) -> ValidationResult:
    """Validate availability and ensure a booking has not already started."""
    return _validate_availability(
        court_id,
        booking_date,
        requested_interval,
        availability_cache,
        current_datetime,
        enforce_temporal=True,
    )


def validate_block_availability(
    court_id: UUID,
    booking_date: date,
    requested_interval: TimeInterval,
    availability_cache: AvailabilityCache,
    current_datetime: datetime | None = None,
) -> ValidationResult:
    """Validate a block interval against FREE and BOOKED availability."""
    return _validate_availability(
        court_id,
        booking_date,
        requested_interval,
        availability_cache,
        current_datetime,
        enforce_temporal=True,
        allowed_statuses={
            AvailabilityStatus.FREE,
            AvailabilityStatus.BOOKED,
        },
        operation="block",
    )


def _validate_availability(
    court_id: UUID,
    booking_date: date,
    requested_interval: TimeInterval,
    availability_cache: AvailabilityCache,
    current_datetime: datetime | None,
    enforce_temporal: bool,
    allowed_statuses: set[AvailabilityStatus] | None = None,
    operation: str = "booking",
) -> ValidationResult:
    try:
        requested_interval = TimeInterval.model_validate(
            {
                "start": requested_interval.start,
                "end": requested_interval.end,
            }
        )
    except ValidationError as error:
        reason = error.errors()[0]["msg"]
        return ValidationResult(
            valid=False,
            errors=[f"Requested interval is invalid: {reason}"],
        )

    start = requested_interval.start
    end = requested_interval.end
    if start.utcoffset() is not None or end.utcoffset() is not None:
        return ValidationResult(
            valid=False,
            errors=["Requested datetimes must be naive venue-local values."],
        )

    if start.date() != booking_date or end.date() != booking_date:
        return ValidationResult(
            valid=False,
            errors=["Requested interval must be on the selected booking date."],
        )

    start_minute = start.hour * 60 + start.minute
    end_minute = end.hour * 60 + end.minute
    if start_minute < _OPENING_MINUTE or end_minute > _CLOSING_MINUTE:
        return ValidationResult(
            valid=False,
            errors=["Requested interval must be within court hours (06:00-20:00)."],
        )

    if enforce_temporal:
        now = current_datetime or datetime.now()
        if now.utcoffset() is not None:
            return ValidationResult(
                valid=False,
                errors=["Current datetime must be a naive venue-local value."],
            )
        if booking_date < now.date():
            return ValidationResult(
                valid=False,
                errors=[f"Requested {operation} date is in the past."],
            )
        if start <= now:
            return ValidationResult(
                valid=False,
                errors=[
                    f"Requested {operation} interval has already started or passed."
                ],
            )

    intervals = availability_cache.get_intervals(court_id, booking_date)
    if intervals is None:
        return ValidationResult(
            valid=False,
            errors=["No availability data exists for the selected court and date."],
        )

    cursor = start
    while cursor < end:
        current = find_interval_containing(intervals, cursor)
        if current is None:
            return ValidationResult(
                valid=False,
                errors=["Requested interval is not fully covered by available intervals."],
            )

        if current.status not in (
            allowed_statuses or {AvailabilityStatus.FREE}
        ):
            if operation == "block" and current.status is AvailabilityStatus.BLOCKED:
                return ValidationResult(
                    valid=False,
                    errors=["Requested block conflicts with an existing BLOCKED interval."],
                )
            return ValidationResult(
                valid=False,
                errors=[f"Requested interval overlaps a {current.status.value} interval."],
            )

        if current.interval.end >= end:
            return ValidationResult(valid=True)

        cursor = current.interval.end

    return ValidationResult(valid=True)
