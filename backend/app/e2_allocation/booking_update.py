from datetime import date, datetime
from uuid import UUID

from ..contracts.booking import TimeInterval, ValidationResult
from .cache import AvailabilityCache
from .interval_utils import find_interval_containing, sort_availability_intervals
from .models import AvailabilityInterval, AvailabilityStatus
from .validation import validate_booking_availability


def apply_booking_to_cache(
    court_id: UUID,
    booking_date: date,
    requested_interval: TimeInterval,
    booking_id: UUID,
    availability_cache: AvailabilityCache,
    current_datetime: datetime | None = None,
) -> ValidationResult:
    """Validate a booking and update the in-memory availability cache."""
    validation = validate_booking_availability(
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

    first_free = find_interval_containing(intervals, requested_interval.start)
    if first_free is None or first_free.status is not AvailabilityStatus.FREE:
        return ValidationResult(
            valid=False,
            errors=["Requested interval is no longer covered by FREE availability."],
        )

    updated: list[AvailabilityInterval] = []
    booking_inserted = False

    for current in intervals:
        overlaps_request = (
            current.status is AvailabilityStatus.FREE
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
                    status=AvailabilityStatus.FREE,
                )
            )

        if not booking_inserted:
            updated.append(
                AvailabilityInterval(
                    interval=requested_interval,
                    status=AvailabilityStatus.BOOKED,
                    reference_id=booking_id,
                )
            )
            booking_inserted = True

        if requested_interval.end < current.interval.end:
            updated.append(
                AvailabilityInterval(
                    interval=TimeInterval(
                        start=requested_interval.end,
                        end=current.interval.end,
                    ),
                    status=AvailabilityStatus.FREE,
                )
            )

    if not booking_inserted:
        return ValidationResult(
            valid=False,
            errors=["Requested interval could not be applied to FREE availability."],
        )

    availability_cache.set_intervals(
        court_id,
        booking_date,
        sort_availability_intervals(updated),
    )
    return ValidationResult(valid=True)
