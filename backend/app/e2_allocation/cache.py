from collections.abc import Iterable
from datetime import date
from uuid import UUID

from .interval_utils import sort_availability_intervals
from .models import AvailabilityInterval, CourtAvailabilityKey


class AvailabilityCache:
    """In-memory availability intervals indexed by court and date."""

    def __init__(self) -> None:
        self._intervals: dict[CourtAvailabilityKey, list[AvailabilityInterval]] = {}

    def set_intervals(
        self,
        court_id: UUID,
        booking_date: date,
        intervals: Iterable[AvailabilityInterval],
    ) -> None:
        """Store a sorted copy, rejecting any overlapping intervals."""
        sorted_intervals = sort_availability_intervals(intervals)

        for previous, current in zip(sorted_intervals, sorted_intervals[1:]):
            if current.interval.start < previous.interval.end:
                raise ValueError("availability intervals must not overlap")

        self._intervals[(court_id, booking_date)] = sorted_intervals

    def get_intervals(
        self, court_id: UUID, booking_date: date
    ) -> list[AvailabilityInterval] | None:
        """Return a deep defensive copy of the intervals for a court and date."""
        intervals = self._intervals.get((court_id, booking_date))
        if intervals is None:
            return None
        return [
            interval.model_copy(deep=True)
            for interval in intervals
        ]

    def has_intervals(self, court_id: UUID, booking_date: date) -> bool:
        """Return whether the exact court/date entry exists."""
        return (court_id, booking_date) in self._intervals

    def remove_intervals(self, court_id: UUID, booking_date: date) -> None:
        """Remove a court/date entry if it exists."""
        self._intervals.pop((court_id, booking_date), None)

    def clear(self) -> None:
        """Remove all entries from the cache."""
        self._intervals.clear()

    def copy(self) -> "AvailabilityCache":
        """Return an independent staged cache copy."""
        copied = AvailabilityCache()
        copied._intervals = {
            key: [
                interval.model_copy(deep=True)
                for interval in intervals
            ]
            for key, intervals in self._intervals.items()
        }
        return copied

    def snapshot(self) -> dict[CourtAvailabilityKey, list[AvailabilityInterval]]:
        """Return a deep defensive snapshot of all cache entries."""
        return {
            key: [
                interval.model_copy(deep=True)
                for interval in intervals
            ]
            for key, intervals in self._intervals.items()
        }

    def restore_snapshot(
        self,
        snapshot: dict[CourtAvailabilityKey, list[AvailabilityInterval]],
    ) -> None:
        """Replace cache state from an already staged snapshot."""
        self._intervals = {
            key: [
                interval.model_copy(deep=True)
                for interval in intervals
            ]
            for key, intervals in snapshot.items()
        }

    def restore_snapshot_for_rollback(
        self,
        snapshot: dict[CourtAvailabilityKey, list[AvailabilityInterval]],
    ) -> None:
        """Direct, hook-free rollback to an exact court snapshot."""
        self._intervals = {
            key: [
                interval.model_copy(deep=True)
                for interval in intervals
            ]
            for key, intervals in snapshot.items()
        }
