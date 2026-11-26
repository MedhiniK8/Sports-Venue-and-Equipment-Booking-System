from datetime import date, datetime
from uuid import UUID

from pydantic import ValidationError

from ..contracts.booking import TimeInterval, ValidationResult
from .cache import AvailabilityCache
from .interval_utils import sort_availability_intervals
from .models import AvailabilityInterval, AvailabilityStatus
from .validation import validate_block_availability


def apply_block_to_cache(
    court_id: UUID,
    booking_date: date,
    requested_interval: TimeInterval,
    block_id: UUID,
    availability_cache: AvailabilityCache,
    current_datetime: datetime | None = None,
) -> ValidationResult:
    """Apply a block over continuously FREE or BOOKED availability."""
    intervals = availability_cache.get_intervals(court_id, booking_date)
    if intervals is None:
        return ValidationResult(
            valid=False,
            errors=["No availability data exists for the selected court and date."],
        )

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
            errors=[f"Requested block interval is invalid: {reason}"],
        )

    if (
        requested_interval.start.utcoffset() is not None
        or requested_interval.end.utcoffset() is not None
    ):
        return ValidationResult(
            valid=False,
            errors=["Requested block datetimes must be naive venue-local values."],
        )

    if any(
        interval.status is AvailabilityStatus.BLOCKED
        and interval.reference_id == block_id
        for interval in intervals
    ):
        return ValidationResult(
            valid=False,
            errors=["Block ID already exists for the selected court and date."],
        )

    validation = validate_block_availability(
        court_id,
        booking_date,
        requested_interval,
        availability_cache,
        current_datetime=current_datetime,
    )
    if not validation.valid:
        return validation

    intervals = availability_cache.get_intervals(court_id, booking_date)
    if intervals is None:
        return ValidationResult(
            valid=False,
            errors=["No availability data exists for the selected court and date."],
        )

    updated: list[AvailabilityInterval] = []
    block_inserted = False

    for current in intervals:
        overlaps_request = (
            current.status in {
                AvailabilityStatus.FREE,
                AvailabilityStatus.BOOKED,
            }
            and current.interval.start < requested_interval.end
            and requested_interval.start < current.interval.end
        )
        if not overlaps_request:
            updated.append(current)
            continue

        if current.interval.start < requested_interval.start:
            updated.append(
                AvailabilityInterval(
                    interval=TimeInterval(
                        start=current.interval.start,
                        end=requested_interval.start,
                    ),
                    status=current.status,
                    reference_id=current.reference_id,
                )
            )

        if not block_inserted:
            updated.append(
                AvailabilityInterval(
                    interval=requested_interval,
                    status=AvailabilityStatus.BLOCKED,
                    reference_id=block_id,
                )
            )
            block_inserted = True

        if requested_interval.end < current.interval.end:
            updated.append(
                AvailabilityInterval(
                    interval=TimeInterval(
                        start=requested_interval.end,
                        end=current.interval.end,
                    ),
                    status=current.status,
                    reference_id=current.reference_id,
                )
            )

    if not block_inserted:
        return ValidationResult(
            valid=False,
            errors=["Requested block could not be applied to available intervals."],
        )

    try:
        availability_cache.set_intervals(
            court_id,
            booking_date,
            sort_availability_intervals(updated),
        )
    except ValueError as error:
        return ValidationResult(
            valid=False,
            errors=[f"Could not update availability cache: {error}"],
        )

    return ValidationResult(valid=True)
