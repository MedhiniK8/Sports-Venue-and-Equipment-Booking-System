import asyncio
from datetime import datetime

import pytest

from app.contracts.booking import LockToken, TimeInterval
from app.e1_concurrency import (
    ConcurrencyService,
    InvalidLockTokenError,
    LockConflictError,
    LockQueueFullError,
    LockWaitTimeoutError,
)


def runtime_interval(
    start_hour: int,
    end_hour: int,
    booking_date: datetime,
) -> TimeInterval:
    return TimeInterval(
        start=booking_date.replace(hour=start_hour, minute=0),
        end=booking_date.replace(hour=end_hour, minute=0),
    )


@pytest.mark.asyncio
async def test_new_service_starts_empty():
    service = ConcurrencyService()

    assert await service.get_active_reservations() == ()
    assert await service.get_waiting_snapshot() == ()


@pytest.mark.asyncio
async def test_runtime_resource_and_interval_are_used():
    service = ConcurrencyService()
    booking_date = datetime(2027, 3, 15)

    token = await service.acquire(
        runtime_interval(9, 11, booking_date),
        "runtime-court-7",
    )

    reservations = await service.get_active_reservations()
    assert isinstance(token, LockToken)
    assert reservations[0].resource_id == "runtime-court-7"
    assert reservations[0].interval.start.date() == booking_date.date()


@pytest.mark.asyncio
async def test_shared_service_rejects_conflict():
    service = ConcurrencyService()
    interval = runtime_interval(
        9,
        11,
        datetime(2027, 3, 15),
    )
    await service.acquire(interval, "court-shared")

    with pytest.raises(LockConflictError):
        await service.acquire(
            runtime_interval(
                10,
                12,
                datetime(2027, 3, 15),
            ),
            "court-shared",
        )


@pytest.mark.asyncio
async def test_shared_service_allows_non_overlapping_requests():
    service = ConcurrencyService()
    booking_date = datetime(2027, 3, 15)

    first = await service.acquire(
        runtime_interval(8, 10, booking_date),
        "court-shared",
    )
    second = await service.acquire(
        runtime_interval(12, 14, booking_date),
        "court-shared",
    )

    assert first.token != second.token
    assert len(await service.get_active_reservations()) == 2


@pytest.mark.asyncio
async def test_public_acquire_release_contract():
    service = ConcurrencyService()
    token = await service.acquire(
        runtime_interval(8, 10, datetime(2027, 3, 15)),
        "court-public-api",
    )

    await service.release(token)

    assert await service.get_active_reservations() == ()


def test_public_exceptions_are_importable():
    assert LockConflictError is not None
    assert LockQueueFullError is not None
    assert LockWaitTimeoutError is not None
    assert InvalidLockTokenError is not None


@pytest.mark.asyncio
async def test_invalid_released_token_is_rejected():
    service = ConcurrencyService()
    token = await service.acquire(
        runtime_interval(8, 10, datetime(2027, 3, 15)),
        "court-release",
    )
    await service.release(token)

    with pytest.raises(InvalidLockTokenError):
        await service.release(token)


@pytest.mark.asyncio
async def test_protected_operation_releases_in_finally():
    service = ConcurrencyService()
    interval = runtime_interval(
        8,
        10,
        datetime(2027, 3, 15),
    )
    token = None

    try:
        token = await service.acquire(interval, "court-protected")
        await asyncio.sleep(0)
    finally:
        if token is not None:
            await service.release(token)

    assert await service.get_active_reservations() == ()


@pytest.mark.asyncio
async def test_import_does_not_create_state_or_tasks():
    import app.e1_concurrency as e1_package

    service = e1_package.ConcurrencyService()
    assert await service.get_active_reservations() == ()
    assert await service.get_waiting_snapshot() == ()
