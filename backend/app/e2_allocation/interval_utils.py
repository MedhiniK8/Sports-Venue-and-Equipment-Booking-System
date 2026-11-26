from collections.abc import Iterable, Sequence
from datetime import datetime

from .models import AvailabilityInterval


def sort_availability_intervals(
    intervals: Iterable[AvailabilityInterval],
) -> list[AvailabilityInterval]:
    """Return a new list ordered by interval start time."""
    return sorted(intervals, key=lambda item: item.interval.start)


def find_interval_containing(
    intervals: Sequence[AvailabilityInterval], target: datetime
) -> AvailabilityInterval | None:
    """Find the interval containing target in a sorted, non-overlapping sequence."""
    low = 0
    high = len(intervals) - 1

    while low <= high:
        middle = (low + high) // 2
        candidate = intervals[middle]

        if target < candidate.interval.start:
            high = middle - 1
        elif target >= candidate.interval.end:
            low = middle + 1
        else:
            return candidate

    return None
