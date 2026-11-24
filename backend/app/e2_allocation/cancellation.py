from datetime import date
from uuid import UUID

from ..contracts.booking import TimeInterval, ValidationResult
from .cache import AvailabilityCache
from .interval_utils import sort_availability_intervals
from .models import AvailabilityInterval, AvailabilityStatus


def cancel_booking_from_cache(
    court_id: UUID,
    booking_date: date,
    booking_id: UUID,
    availability_cache: AvailabilityCache,
) -> ValidationResult:
    """Cancel one booking and merge any contiguous FREE intervals."""
    intervals = availability_cache.get_intervals(court_id, booking_date)
    if intervals is None:
        return ValidationResult(
            valid=False,
            errors=["No availability data exists for the selected court and date."],
        )

    matching_indices = [
        index
        for index, interval in enumerate(intervals)
        if interval.reference_id == booking_id
    ]
    if len(matching_indices) > 1:
        return ValidationResult(
            valid=False,
            errors=["Booking reference is ambiguous in the selected court/date cache."],
        )
    if not matching_indices:
        return ValidationResult(
            valid=False,
            errors=["Booking was not found in the selected court/date cache."],
        )

    matching_index = matching_indices[0]
    booking_interval = intervals[matching_index]
    if booking_interval.status is not AvailabilityStatus.BOOKED:
        return ValidationResult(
            valid=False,
            errors=["Matching reference does not belong to a BOOKED interval."],
        )

    updated = list(intervals)
    updated[matching_index] = AvailabilityInterval(
        interval=booking_interval.interval,
        status=AvailabilityStatus.FREE,
    )

    merged: list[AvailabilityInterval] = []
    for current in sort_availability_intervals(updated):
        if (
            merged
            and merged[-1].status is AvailabilityStatus.FREE
            and current.status is AvailabilityStatus.FREE
            and merged[-1].interval.end == current.interval.start
        ):
            previous = merged[-1]
            merged[-1] = AvailabilityInterval(
                interval=TimeInterval(
                    start=previous.interval.start,
                    end=current.interval.end,
                ),
                status=AvailabilityStatus.FREE,
            )
        else:
            merged.append(current)

    availability_cache.set_intervals(court_id, booking_date, merged)
    return ValidationResult(valid=True)
