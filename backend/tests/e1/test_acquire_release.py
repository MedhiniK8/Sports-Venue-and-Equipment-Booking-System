import asyncio
from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.contracts.booking import LockToken, TimeInterval
from app.e1_concurrency.service import (
    ConcurrencyService,
    InvalidLockTokenError,
    LockConflictError,
)


def make_interval(
    start_hour: int,
    start_minute: int, 
    end_hour: int,
    end_minute: int,
    booking_date: datetime | None = None,
) -> TimeInterval:
    date = booking_date or datetime(2026, 11, 24)
    return TimeInterval(
        start=date.replace(hour=start_hour, minute=start_minute),
        end=date.replace(hour=end_hour, minute=end_minute),
    )


@pytest.mark.asyncio
async def test_m3_01_acquire_free_interval():
    service = ConcurrencyService()

    token = await service.acquire(make_interval(8, 0, 10, 0), "court-1")

    assert isinstance(token, LockToken)
    assert len(await service.get_active_reservations()) == 1


@pytest.mark.asyncio
async def test_m3_02_independent_intervals_have_unique_tokens():
    service = ConcurrencyService()

    first = await service.acquire(make_interval(8, 0, 10, 0), "court-1")
    second = await service.acquire(make_interval(12, 0, 14, 0), "court-1")

    assert first.token != second.token


@pytest.mark.asyncio
async def test_m3_03_same_interval_different_courts():
    service = ConcurrencyService()
    interval = make_interval(8, 0, 10, 0)

    first = await service.acquire(interval, "court-1")
    second = await service.acquire(interval, "court-2")

    assert first.token != second.token
    assert len(await service.get_active_reservations()) == 2


@pytest.mark.asyncio
async def test_m3_04_same_interval_different_dates():
    service = ConcurrencyService()

    first = await service.acquire(
        make_interval(8, 0, 10, 0),
        "court-1",
    )
    second = await service.acquire(
        make_interval(8, 0, 10, 0, datetime(2026, 11, 25)),
        "court-1",
    )

    assert first.token != second.token
    assert len(await service.get_active_reservations()) == 2


@pytest.mark.asyncio
async def test_m3_05_release_valid_token():
    service = ConcurrencyService()
    token = await service.acquire(make_interval(8, 0, 10, 0), "court-1")

    await service.release(token)

    assert await service.get_active_reservations() == ()


@pytest.mark.asyncio
async def test_m3_06_reacquire_after_release():
    service = ConcurrencyService()
    interval = make_interval(8, 0, 10, 0)
    released = await service.acquire(interval, "court-1")

    await service.release(released)
    replacement = await service.acquire(interval, "court-1")

    assert replacement.token != released.token
    assert len(await service.get_active_reservations()) == 1


@pytest.mark.asyncio
async def test_m3_07_overlapping_acquisition_rejected():
    service = ConcurrencyService()
    await service.acquire(make_interval(8, 0, 10, 0), "court-1")

    with pytest.raises(LockConflictError):
        await service.acquire(make_interval(9, 0, 11, 0), "court-1")

    assert len(await service.get_active_reservations()) == 1


@pytest.mark.asyncio
async def test_m3_08_identical_interval_rejected():
    service = ConcurrencyService()
    interval = make_interval(8, 0, 10, 0)
    await service.acquire(interval, "court-1")

    with pytest.raises(LockConflictError):
        await service.acquire(interval, "court-1")

    assert len(await service.get_active_reservations()) == 1


@pytest.mark.asyncio
async def test_m3_09_adjacent_intervals():
    service = ConcurrencyService()

    first = await service.acquire(make_interval(8, 0, 9, 0), "court-1")
    second = await service.acquire(make_interval(9, 0, 10, 0), "court-1")

    assert first.token != second.token
    assert len(await service.get_active_reservations()) == 2


@pytest.mark.asyncio
async def test_m3_10_unknown_token():
    service = ConcurrencyService()
    interval = make_interval(8, 0, 10, 0)
    existing = await service.acquire(interval, "court-1")
    unknown = LockToken(token=uuid4(), interval=interval)

    with pytest.raises(InvalidLockTokenError):
        await service.release(unknown)

    reservations = await service.get_active_reservations()
    assert len(reservations) == 1
    assert existing.token != unknown.token


@pytest.mark.asyncio
async def test_m3_11_double_release():
    service = ConcurrencyService()
    interval = make_interval(8, 0, 10, 0)
    first = await service.acquire(interval, "court-1")
    second = await service.acquire(make_interval(12, 0, 14, 0), "court-1")

    await service.release(first)
    with pytest.raises(InvalidLockTokenError):
        await service.release(first)

    reservations = await service.get_active_reservations()
    assert len(reservations) == 1
    assert reservations[0].interval == second.interval


@pytest.mark.asyncio
async def test_m3_12_release_one_of_two_tokens():
    service = ConcurrencyService()
    first = await service.acquire(make_interval(8, 0, 10, 0), "court-1")
    second = await service.acquire(make_interval(12, 0, 14, 0), "court-1")

    await service.release(first)

    reservations = await service.get_active_reservations()
    assert len(reservations) == 1
    assert reservations[0].interval == second.interval


@pytest.mark.asyncio
async def test_m3_13_concurrent_conflicting_acquisitions():
    service = ConcurrencyService()
    start = asyncio.Event()

    async def acquire():
        await start.wait()
        try:
            return await service.acquire(
                make_interval(8, 0, 10, 0),
                "court-1",
            )
        except LockConflictError:
            return None

    tasks = [asyncio.create_task(acquire()) for _ in range(20)]
    start.set()
    results = await asyncio.gather(*tasks)

    successful = [result for result in results if result is not None]
    assert len(successful) == 1
    assert len(await service.get_active_reservations()) == 1


@pytest.mark.asyncio
async def test_m3_14_concurrent_non_overlapping_acquisitions():
    service = ConcurrencyService()
    start = asyncio.Event()

    async def acquire(interval: TimeInterval):
        await start.wait()
        return await service.acquire(interval, "court-1")

    tasks = [
        asyncio.create_task(acquire(make_interval(8, 0, 10, 0))),
        asyncio.create_task(acquire(make_interval(12, 0, 14, 0))),
    ]
    start.set()
    results = await asyncio.gather(*tasks)

    assert len({result.token for result in results}) == 2
    assert len(await service.get_active_reservations()) == 2


@pytest.mark.asyncio
async def test_m3_15_release_and_retry_conflicting_acquisition():
    service = ConcurrencyService()
    interval_a = make_interval(8, 0, 10, 0)
    interval_b = make_interval(9, 0, 11, 0)
    token_a = await service.acquire(interval_a, "court-1")

    with pytest.raises(LockConflictError):
        await service.acquire(interval_b, "court-1")

    await service.release(token_a)
    retry = await service.acquire(interval_b, "court-1")

    assert retry.token != token_a.token
    assert len(await service.get_active_reservations()) == 1


@pytest.mark.asyncio
async def test_mismatched_interval_release_is_rejected():
    service = ConcurrencyService()
    correct_interval = make_interval(8, 0, 10, 0)
    token = await service.acquire(correct_interval, "court-1")
    mismatched = LockToken(
        token=token.token,
        interval=make_interval(9, 0, 11, 0),
    )

    with pytest.raises(InvalidLockTokenError):
        await service.release(mismatched)

    reservations = await service.get_active_reservations()
    assert len(reservations) == 1
    assert reservations[0].interval == correct_interval

    await service.release(token)
    assert await service.get_active_reservations() == ()


@pytest.mark.asyncio
async def test_token_from_another_instance_cannot_release_reservation():
    first_service = ConcurrencyService()
    second_service = ConcurrencyService()
    interval = make_interval(8, 0, 10, 0)
    local_token = await first_service.acquire(interval, "court-1")
    foreign_token = await second_service.acquire(interval, "court-1")

    with pytest.raises(InvalidLockTokenError):
        await first_service.release(foreign_token)

    assert len(await first_service.get_active_reservations()) == 1
    await first_service.release(local_token)
    assert await first_service.get_active_reservations() == ()


@pytest.mark.asyncio
async def test_token_construction_failure_does_not_leak_reservation():
    service = ConcurrencyService()

    with patch(
        "app.e1_concurrency.service.LockToken",
        side_effect=RuntimeError("simulated token construction failure"),
    ):
        with pytest.raises(RuntimeError):
            await service.acquire(make_interval(8, 0, 10, 0), "court-1")

    assert await service.get_active_reservations() == ()
    async with service._registry_mutex:
        assert service._token_reservations == {}


@pytest.mark.asyncio
async def test_token_failure_preserves_unrelated_reservation():
    service = ConcurrencyService()
    unrelated = await service.acquire(make_interval(8, 0, 10, 0), "court-1")

    with patch(
        "app.e1_concurrency.service.LockToken",
        side_effect=RuntimeError("simulated token construction failure"),
    ):
        with pytest.raises(RuntimeError):
            await service.acquire(make_interval(12, 0, 14, 0), "court-1")

    reservations = await service.get_active_reservations()
    assert len(reservations) == 1
    assert reservations[0].interval == unrelated.interval


@pytest.mark.asyncio
async def test_acquire_succeeds_after_token_construction_failure():
    service = ConcurrencyService()

    with patch(
        "app.e1_concurrency.service.LockToken",
        side_effect=RuntimeError("simulated token construction failure"),
    ):
        with pytest.raises(RuntimeError):
            await service.acquire(make_interval(8, 0, 10, 0), "court-1")

    token = await service.acquire(make_interval(8, 0, 10, 0), "court-1")

    assert len(await service.get_active_reservations()) == 1
    await service.release(token)
    assert await service.get_active_reservations() == ()
