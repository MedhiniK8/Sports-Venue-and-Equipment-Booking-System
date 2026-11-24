from collections.abc import Sequence
from datetime import datetime
from uuid import UUID, uuid4

import pytest

from app.contracts.booking import TimeInterval
from app.e2_allocation.interval_utils import (
    find_interval_containing,
    sort_availability_intervals,
)
from app.e2_allocation.models import AvailabilityInterval, AvailabilityStatus


def make_interval(
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
    status: AvailabilityStatus = AvailabilityStatus.FREE,
    reference_id: UUID | None = None,
) -> AvailabilityInterval:
    return AvailabilityInterval(
        interval=TimeInterval(
            start=datetime(2026, 11, 23, start_hour, start_minute),
            end=datetime(2026, 11, 23, end_hour, end_minute),
        ),
        status=status,
        reference_id=reference_id,
    )


def make_search_intervals() -> list[AvailabilityInterval]:
    return [
        make_interval(6, 0, 7, 0),
        make_interval(7, 0, 8, 0),
        make_interval(9, 0, 10, 0),
        make_interval(11, 0, 12, 0),
        make_interval(12, 0, 13, 0),
    ]


def test_sort_intervals_returns_chronological_copy_and_preserves_models():
    booked_reference = uuid4()
    later = make_interval(
        9, 0, 10, 0, AvailabilityStatus.BOOKED, booked_reference
    )
    earlier = make_interval(6, 0, 7, 0)
    blocked_reference = uuid4()
    middle = make_interval(
        7, 0, 8, 0, AvailabilityStatus.BLOCKED, blocked_reference
    )
    original = [later, earlier, middle]

    sorted_intervals = sort_availability_intervals(original)

    assert sorted_intervals == [earlier, middle, later]
    assert sorted_intervals[0] is earlier
    assert sorted_intervals[1] is middle
    assert sorted_intervals[2] is later
    assert sorted_intervals[1].status is AvailabilityStatus.BLOCKED
    assert sorted_intervals[1].reference_id == blocked_reference
    assert sorted_intervals[2].status is AvailabilityStatus.BOOKED
    assert sorted_intervals[2].reference_id == booked_reference
    assert original == [later, earlier, middle]


def test_sort_already_sorted_intervals():
    intervals = make_search_intervals()

    assert sort_availability_intervals(intervals) == intervals


def test_sort_empty_collection():
    assert sort_availability_intervals([]) == []


def test_sort_single_interval():
    interval = make_interval(6, 0, 7, 0)

    assert sort_availability_intervals([interval]) == [interval]


@pytest.mark.parametrize(
    ("target", "expected_index"),
    [
        (datetime(2026, 11, 23, 6, 30), 0),
        (datetime(2026, 11, 23, 9, 30), 2),
        (datetime(2026, 11, 23, 12, 30), 4),
    ],
)
def test_binary_search_finds_intervals_near_beginning_middle_and_end(
    target, expected_index
):
    intervals = make_search_intervals()

    assert find_interval_containing(intervals, target) is intervals[expected_index]


def test_binary_search_includes_exact_interval_start():
    intervals = make_search_intervals()

    assert (
        find_interval_containing(intervals, datetime(2026, 11, 23, 6, 0))
        is intervals[0]
    )


def test_binary_search_excludes_end_and_finds_next_interval_at_boundary():
    intervals = make_search_intervals()

    assert (
        find_interval_containing(intervals, datetime(2026, 11, 23, 7, 0))
        is intervals[1]
    )


def test_binary_search_returns_none_at_final_end():
    intervals = make_search_intervals()

    assert find_interval_containing(intervals, datetime(2026, 11, 23, 13, 0)) is None


@pytest.mark.parametrize(
    "target",
    [
        datetime(2026, 11, 23, 5, 59),
        datetime(2026, 11, 23, 13, 1),
    ],
)
def test_binary_search_returns_none_outside_all_intervals(target):
    assert find_interval_containing(make_search_intervals(), target) is None


def test_binary_search_returns_none_for_gap():
    intervals = make_search_intervals()

    assert find_interval_containing(intervals, datetime(2026, 11, 23, 8, 30)) is None


def test_binary_search_returns_none_for_empty_sequence():
    assert find_interval_containing([], datetime(2026, 11, 23, 8, 30)) is None


def test_binary_search_handles_single_interval():
    interval = make_interval(6, 0, 7, 0)

    assert (
        find_interval_containing([interval], datetime(2026, 11, 23, 6, 30))
        is interval
    )
    assert find_interval_containing([interval], datetime(2026, 11, 23, 7, 0)) is None


class CountingSequence(Sequence[AvailabilityInterval]):
    def __init__(self, intervals: list[AvailabilityInterval]) -> None:
        self._intervals = intervals
        self.access_count = 0

    def __getitem__(self, index: int) -> AvailabilityInterval:
        self.access_count += 1
        return self._intervals[index]

    def __len__(self) -> int:
        return len(self._intervals)


def test_binary_search_uses_logarithmic_number_of_interval_accesses():
    intervals = [
        make_interval(hour, 0, hour, 30)
        for hour in range(6, 20)
    ]
    counted_intervals = CountingSequence(intervals)

    result = find_interval_containing(
        counted_intervals, datetime(2026, 11, 23, 19, 15)
    )

    assert result is intervals[-1]
    assert counted_intervals.access_count <= 4
