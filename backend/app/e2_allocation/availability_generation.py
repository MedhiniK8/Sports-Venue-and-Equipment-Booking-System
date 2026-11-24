from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from ..contracts.booking import TimeInterval
from .cache import AvailabilityCache
from .models import AvailabilityInterval, AvailabilityStatus, CourtAvailabilityKey


_OPENING_TIME = time(6, 0)
_CLOSING_TIME = time(20, 0)
_WINDOW_DAYS = 7


class CommittedBooking(BaseModel):
    """A committed booking supplied for availability generation."""

    model_config = ConfigDict(extra="forbid")

    booking_id: UUID
    court_id: UUID
    interval: TimeInterval


class EffectiveCourtBlock(BaseModel):
    """An effective court block supplied for availability generation."""

    model_config = ConfigDict(extra="forbid")

    block_id: UUID
    court_id: UUID
    interval: TimeInterval


def populate_seven_day_availability(
    availability_cache: AvailabilityCache,
    active_court_ids: Iterable[UUID],
    bookings: Iterable[CommittedBooking],
    blocks: Iterable[EffectiveCourtBlock],
    reference_date: date,
) -> None:
    """Generate and cache availability for the reference date and next six dates.

    Datetimes must be naive venue-local values. Bookings must fit within one
    operating day; effective blocks may span days and are clipped per day.
    """
    if isinstance(reference_date, datetime):
        raise ValueError("reference_date must be a date, not a datetime")

    court_ids = sorted(set(active_court_ids))
    active_courts = set(court_ids)
    window_dates = [
        reference_date + timedelta(days=offset) for offset in range(_WINDOW_DAYS)
    ]
    window_start = datetime.combine(window_dates[0], time.min)
    window_end = datetime.combine(window_dates[-1] + timedelta(days=1), time.min)
    occupied: dict[CourtAvailabilityKey, list[AvailabilityInterval]] = {}

    for booking in bookings:
        interval = _validated_interval(booking.interval, f"booking {booking.booking_id}")
        _require_active_court(booking.court_id, active_courts, "booking")
        if not _overlaps_window(interval, window_start, window_end):
            continue
        if interval.start.date() != interval.end.date():
            raise ValueError(
                f"booking {booking.booking_id} must be contained within one date"
            )
        if not _within_operating_hours(interval):
            raise ValueError(
                f"booking {booking.booking_id} must be within court hours "
                "(06:00-20:00)"
            )

        key = (booking.court_id, interval.start.date())
        occupied.setdefault(key, []).append(
            AvailabilityInterval(
                interval=interval,
                status=AvailabilityStatus.BOOKED,
                reference_id=booking.booking_id,
            )
        )

    for block in blocks:
        interval = _validated_interval(block.interval, f"block {block.block_id}")
        _require_active_court(block.court_id, active_courts, "block")
        if not _overlaps_window(interval, window_start, window_end):
            continue

        for booking_date in window_dates:
            day_open = datetime.combine(booking_date, _OPENING_TIME)
            day_close = datetime.combine(booking_date, _CLOSING_TIME)
            clipped_start = max(interval.start, day_open)
            clipped_end = min(interval.end, day_close)
            if clipped_start < clipped_end:
                key = (block.court_id, booking_date)
                occupied.setdefault(key, []).append(
                    AvailabilityInterval(
                        interval=TimeInterval(start=clipped_start, end=clipped_end),
                        status=AvailabilityStatus.BLOCKED,
                        reference_id=block.block_id,
                    )
                )

    generated: dict[CourtAvailabilityKey, list[AvailabilityInterval]] = {}
    for court_id in court_ids:
        for booking_date in window_dates:
            key = (court_id, booking_date)
            generated[key] = _build_day_intervals(
                court_id,
                booking_date,
                occupied.get(key, []),
            )

    for (court_id, booking_date), intervals in generated.items():
        availability_cache.set_intervals(court_id, booking_date, intervals)


def _validated_interval(interval: TimeInterval, record_label: str) -> TimeInterval:
    try:
        validated = TimeInterval.model_validate(
            {"start": interval.start, "end": interval.end}
        )
    except ValidationError as error:
        reason = error.errors()[0]["msg"]
        raise ValueError(f"{record_label} has an invalid interval: {reason}") from error

    if validated.start.utcoffset() is not None or validated.end.utcoffset() is not None:
        raise ValueError(f"{record_label} datetimes must be naive venue-local values")
    return validated


def _require_active_court(
    court_id: UUID, active_courts: set[UUID], record_type: str
) -> None:
    if court_id not in active_courts:
        raise ValueError(
            f"{record_type} references a court that is unknown or inactive: {court_id}"
        )


def _overlaps_window(
    interval: TimeInterval, window_start: datetime, window_end: datetime
) -> bool:
    return interval.start < window_end and interval.end > window_start


def _within_operating_hours(interval: TimeInterval) -> bool:
    return (
        interval.start.hour * 60 + interval.start.minute >= 6 * 60
        and interval.end.hour * 60 + interval.end.minute <= 20 * 60
    )


def _build_day_intervals(
    court_id: UUID,
    booking_date: date,
    occupied_intervals: list[AvailabilityInterval],
) -> list[AvailabilityInterval]:
    sorted_occupied = sorted(
        occupied_intervals, key=lambda item: item.interval.start
    )
    for previous, current in zip(sorted_occupied, sorted_occupied[1:]):
        if current.interval.start < previous.interval.end:
            raise ValueError(
                "conflicting availability records overlap for court "
                f"{court_id} on {booking_date}: "
                f"{previous.reference_id} and {current.reference_id}"
            )

    day_open = datetime.combine(booking_date, _OPENING_TIME)
    day_close = datetime.combine(booking_date, _CLOSING_TIME)
    result: list[AvailabilityInterval] = []
    cursor = day_open

    for occupied in sorted_occupied:
        if cursor < occupied.interval.start:
            result.append(
                AvailabilityInterval(
                    interval=TimeInterval(
                        start=cursor,
                        end=occupied.interval.start,
                    ),
                    status=AvailabilityStatus.FREE,
                )
            )
        result.append(occupied)
        cursor = occupied.interval.end

    if cursor < day_close:
        result.append(
            AvailabilityInterval(
                interval=TimeInterval(start=cursor, end=day_close),
                status=AvailabilityStatus.FREE,
            )
        )

    return result
