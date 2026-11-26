import asyncio
from datetime import datetime
from unittest.mock import patch

import pytest

from app.contracts.booking import TimeInterval
from app.e1_concurrency.service import (
    ConcurrencyService,
    LockConflictError,
    LockQueueFullError,
    LockWaitTimeoutError,
)


def interval(start_hour: int, end_hour: int, date: datetime | None = None) -> TimeInterval:
    day = date or datetime(2026, 11, 24)
    return TimeInterval(
        start=day.replace(hour=start_hour, minute=0),
        end=day.replace(hour=end_hour, minute=0),
    )


async def wait_for_waiter_count(
    service: ConcurrencyService,
    expected: int,
) -> None:
    for _ in range(100):
        snapshot = await service.get_waiting_snapshot()
        if len(snapshot) == expected:
            return
        await asyncio.sleep(0)
    raise AssertionError(
        f"Waiting queue did not reach {expected} entries"
    )


@pytest.mark.asyncio
async def test_m4_01_immediate_acquisition():
    service = ConcurrencyService()

    token = await service.acquire_with_wait(interval(8, 10), "court-1")

    assert token.token is not None
    assert len(await service.get_waiting_snapshot()) == 0


@pytest.mark.asyncio
async def test_m4_02_conflicting_request_waits():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")
    waiter = asyncio.create_task(
        service.acquire_with_wait(interval(9, 11), "court-1")
    )
    await asyncio.sleep(0)

    assert not waiter.done()
    assert len(await service.get_waiting_snapshot()) == 1
    await service.release(active)
    await waiter


@pytest.mark.asyncio
async def test_m4_03_release_wakes_waiter():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")
    waiter = asyncio.create_task(
        service.acquire_with_wait(interval(9, 11), "court-1")
    )
    await asyncio.sleep(0)

    await service.release(active)
    token = await waiter

    assert token.token is not None
    assert len(await service.get_active_reservations()) == 1


@pytest.mark.asyncio
async def test_m4_04_fifo_order():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")
    first = asyncio.create_task(
        service.acquire_with_wait(interval(9, 11), "court-1")
    )
    await asyncio.sleep(0)
    second = asyncio.create_task(
        service.acquire_with_wait(interval(9, 10), "court-1")
    )
    await asyncio.sleep(0)

    await service.release(active)
    first_token = await first

    assert not second.done()
    assert len(await service.get_waiting_snapshot()) == 1
    await service.release(first_token)
    await second


@pytest.mark.asyncio
async def test_m4_05_non_overlapping_request_proceeds():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")
    waiter = asyncio.create_task(
        service.acquire_with_wait(interval(9, 11), "court-1")
    )
    await asyncio.sleep(0)

    independent = await service.acquire_with_wait(interval(12, 14), "court-1")

    assert independent.token is not None
    assert not waiter.done()
    await service.release(active)
    await service.release(independent)
    await waiter


@pytest.mark.asyncio
async def test_m4_06_different_courts():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")

    independent = await service.acquire_with_wait(interval(9, 11), "court-2")

    assert independent.token is not None
    assert len(await service.get_active_reservations()) == 2
    await service.release(active)
    await service.release(independent)


@pytest.mark.asyncio
async def test_m4_07_three_second_timeout():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")

    with pytest.raises(LockWaitTimeoutError):
        await service.acquire_with_wait(
            interval(9, 11),
            "court-1",
        )

    await service.release(active)


@pytest.mark.asyncio
async def test_m4_08_timeout_cleanup():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")

    with pytest.raises(LockWaitTimeoutError):
        await service.acquire_with_wait(
            interval(9, 11),
            "court-1",
            timeout=0.05,
        )

    assert await service.get_waiting_snapshot() == ()
    await service.release(active)


@pytest.mark.asyncio
async def test_m4_09_queue_full():
    service = ConcurrencyService(max_waiting_requests=2)
    active = await service.acquire(interval(8, 10), "court-1")
    waiters = [
        asyncio.create_task(
            service.acquire_with_wait(interval(9, 11), "court-1")
        ),
        asyncio.create_task(
            service.acquire_with_wait(interval(9, 10), "court-1")
        ),
    ]
    await wait_for_waiter_count(service, 2)

    with pytest.raises(LockQueueFullError):
        await service.acquire_with_wait(
            interval(9, 11),
            "court-1",
            timeout=1,
        )

    await service.release(active)
    first = await waiters[0]
    await service.release(first)
    second = await waiters[1]
    await service.release(second)


@pytest.mark.asyncio
async def test_m4_10_cancellation():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")
    waiter = asyncio.create_task(
        service.acquire_with_wait(interval(9, 11), "court-1")
    )
    await asyncio.sleep(0)

    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    assert await service.get_waiting_snapshot() == ()
    await service.release(active)


@pytest.mark.asyncio
async def test_m4_11_multiple_waiting_requests():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")
    waiters = [
        asyncio.create_task(
            service.acquire_with_wait(interval(9, 11), "court-1")
        )
        for _ in range(3)
    ]
    await wait_for_waiter_count(service, 3)

    await service.release(active)
    tokens = await asyncio.gather(*waiters, return_exceptions=True)

    successful = [item for item in tokens if hasattr(item, "token")]
    assert len(successful) == 1
    assert len(await service.get_active_reservations()) == 1
    await service.release(successful[0])


@pytest.mark.asyncio
async def test_m4_12_release_timeout_race():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")
    waiter = asyncio.create_task(
        service.acquire_with_wait(
            interval(9, 11),
            "court-1",
            timeout=0.05,
        )
    )
    await asyncio.sleep(0)
    await service.release(active)

    result = await asyncio.gather(waiter, return_exceptions=True)
    outcome = result[0]
    assert isinstance(outcome, LockWaitTimeoutError) or hasattr(outcome, "token")
    if isinstance(outcome, LockWaitTimeoutError):
        assert await service.get_active_reservations() == ()
    else:
        assert hasattr(outcome, "token")
        await service.release(outcome)
    assert len(await service.get_waiting_snapshot()) == 0


@pytest.mark.asyncio
async def test_m4_13_cancellation_grant_race():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")
    waiter = asyncio.create_task(
        service.acquire_with_wait(interval(9, 11), "court-1")
    )
    await asyncio.sleep(0)

    await service.release(active)
    waiter.cancel()
    result = await asyncio.gather(waiter, return_exceptions=True)

    assert isinstance(result[0], asyncio.CancelledError)
    assert await service.get_waiting_snapshot() == ()
    assert len(await service.get_active_reservations()) == 0

    replacement = await service.acquire_with_wait(interval(9, 11), "court-1")
    await service.release(replacement)
    assert await service.get_waiting_snapshot() == ()


@pytest.mark.asyncio
async def test_m4_14_fail_fast_acquire_preserved():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")

    with pytest.raises(LockConflictError):
        await service.acquire(interval(9, 11), "court-1")

    await service.release(active)


@pytest.mark.asyncio
async def test_m4_15_repeated_acquire_after_timeout():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")

    with pytest.raises(LockWaitTimeoutError):
        await service.acquire_with_wait(
            interval(9, 11),
            "court-1",
            timeout=0.05,
        )

    await service.release(active)
    retry = await service.acquire_with_wait(interval(9, 11), "court-1")
    assert retry.token is not None


@pytest.mark.asyncio
async def test_m4_16_queue_state_consistency():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")
    waiter = asyncio.create_task(
        service.acquire_with_wait(interval(9, 11), "court-1")
    )
    await asyncio.sleep(0)

    await service.release(active)
    token = await waiter
    await service.release(token)

    assert await service.get_waiting_snapshot() == ()
    assert await service.get_active_reservations() == ()


@pytest.mark.asyncio
async def test_fifo_bypass_prevention():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")

    b_waiter = asyncio.create_task(
        service.acquire_with_wait(interval(9, 11), "court-1")
    )
    await wait_for_waiter_count(service, 1)

    c_waiter = asyncio.create_task(
        service.acquire_with_wait(interval(10, 11), "court-1")
    )
    await wait_for_waiter_count(service, 2)

    await service.release(active)
    token_b = await b_waiter

    assert not c_waiter.done()
    await service.release(token_b)
    token_c = await c_waiter

    await service.release(token_c)
    assert await service.get_waiting_snapshot() == ()
    assert await service.get_active_reservations() == ()


@pytest.mark.asyncio
async def test_direct_registration_cannot_bypass_waiter():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")
    b_waiter = asyncio.create_task(
        service.acquire_with_wait(interval(9, 11), "court-1")
    )
    await wait_for_waiter_count(service, 1)

    rejected = await service.register_reservation(
        interval(10, 11),
        "court-1",
    )
    assert rejected.registered is False
    assert rejected.reason == "earlier_conflicting_waiter"

    unrelated = await service.register_reservation(
        interval(12, 14),
        "court-1",
    )
    assert unrelated.registered is True

    await service.release(active)
    await service.remove_reservation(unrelated.reservation_id)
    token_b = await b_waiter
    await service.release(token_b)


@pytest.mark.asyncio
async def test_expired_waiter_is_not_granted():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")
    waiter_task = asyncio.create_task(
        service.acquire_with_wait(
            interval(9, 11),
            "court-1",
            timeout=1,
        )
    )
    await wait_for_waiter_count(service, 1)

    async with service._registry_mutex:
        waiter = next(iter(service._waiting_requests))
        waiter.deadline = asyncio.get_running_loop().time() - 1
        service._reconsider_waiters_locked()

    with pytest.raises(LockWaitTimeoutError):
        await waiter_task

    assert await service.get_waiting_snapshot() == ()
    assert len(await service.get_active_reservations()) == 1
    await service.release(active)


@pytest.mark.asyncio
async def test_cleanup_enables_later_waiter():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")
    earlier = asyncio.create_task(
        service.acquire_with_wait(
            interval(9, 11),
            "court-1",
            timeout=1,
        )
    )
    await wait_for_waiter_count(service, 1)

    later = asyncio.create_task(
        service.acquire_with_wait(
            interval(9, 10),
            "court-1",
            timeout=1,
        )
    )
    await wait_for_waiter_count(service, 2)

    earlier.cancel()
    with pytest.raises(asyncio.CancelledError):
        await earlier

    await service.release(active)
    later_token = await later
    await service.release(later_token)

    assert await service.get_waiting_snapshot() == ()
    assert await service.get_active_reservations() == ()


@pytest.mark.asyncio
async def test_waiter_token_construction_failure():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")
    waiter_task = asyncio.create_task(
        service.acquire_with_wait(interval(9, 11), "court-1")
    )
    await wait_for_waiter_count(service, 1)

    with patch(
        "app.e1_concurrency.service.LockToken",
        side_effect=RuntimeError("simulated grant token failure"),
    ):
        await service.release(active)

    with pytest.raises(RuntimeError):
        await waiter_task

    assert await service.get_waiting_snapshot() == ()
    assert await service.get_active_reservations() == ()


@pytest.mark.asyncio
async def test_m4_fix_01_expired_waiter_does_not_block_new_request():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")
    b_waiter = asyncio.create_task(
        service.acquire_with_wait(interval(9, 11), "court-1")
    )
    await wait_for_waiter_count(service, 1)

    async with service._registry_mutex:
        expired = next(iter(service._waiting_requests))
        expired.deadline = asyncio.get_running_loop().time() - 1

    c_token = await service.acquire_with_wait(interval(10, 11), "court-1")

    with pytest.raises(LockWaitTimeoutError):
        await b_waiter

    assert await service.get_waiting_snapshot() == ()
    assert len(await service.get_active_reservations()) == 2
    await service.release(c_token)
    await service.release(active)


@pytest.mark.asyncio
async def test_m4_fix_02_fifo_works_after_expiry_cleanup():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")
    first = asyncio.create_task(
        service.acquire_with_wait(interval(9, 11), "court-1")
    )
    await wait_for_waiter_count(service, 1)
    second = asyncio.create_task(
        service.acquire_with_wait(interval(9, 10), "court-1")
    )
    await wait_for_waiter_count(service, 2)

    async with service._registry_mutex:
        first_waiter = next(iter(service._waiting_requests))
        first_waiter.deadline = asyncio.get_running_loop().time() - 1
        service._reconsider_waiters_locked()

    with pytest.raises(LockWaitTimeoutError):
        await first

    await service.release(active)
    second_token = await second
    await service.release(second_token)

    assert await service.get_waiting_snapshot() == ()
    assert await service.get_active_reservations() == ()


@pytest.mark.asyncio
async def test_m4_fix_03_capacity_released_after_expiry_cleanup():
    service = ConcurrencyService(max_waiting_requests=1)
    active = await service.acquire(interval(8, 10), "court-1")
    expired = asyncio.create_task(
        service.acquire_with_wait(interval(9, 11), "court-1")
    )
    await wait_for_waiter_count(service, 1)

    async with service._registry_mutex:
        waiter = next(iter(service._waiting_requests))
        waiter.deadline = asyncio.get_running_loop().time() - 1
        service._reconsider_waiters_locked()

    with pytest.raises(LockWaitTimeoutError):
        await expired

    replacement = asyncio.create_task(
        service.acquire_with_wait(
            interval(9, 11),
            "court-1",
            timeout=1,
        )
    )
    await wait_for_waiter_count(service, 1)

    await service.release(active)
    replacement_token = await replacement
    await service.release(replacement_token)


@pytest.mark.asyncio
async def test_m4_fix_04_timeout_starts_at_queue_entry():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")
    waiter = asyncio.create_task(
        service.acquire_with_wait(
            interval(9, 11),
            "court-1",
            timeout=1,
        )
    )
    snapshot = None
    for _ in range(100):
        snapshot = await service.get_waiting_snapshot()
        if snapshot:
            break
        await asyncio.sleep(0)

    assert snapshot is not None and len(snapshot) == 1
    first_deadline = snapshot[0].deadline

    await service.get_waiting_snapshot()
    snapshot = await service.get_waiting_snapshot()
    assert snapshot[0].deadline == first_deadline

    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    await service.release(active)


@pytest.mark.asyncio
async def test_m4_fix_05_mutex_wait_does_not_timeout_immediate_acquisition():
    service = ConcurrencyService()
    acquired = asyncio.Event()
    release_mutex = asyncio.Event()

    async def hold_mutex():
        async with service._registry_mutex:
            await release_mutex.wait()

    holder = asyncio.create_task(hold_mutex())
    await asyncio.sleep(0)
    candidate = asyncio.create_task(
        service.acquire_with_wait(
            interval(12, 14),
            "court-1",
            timeout=0.01,
        )
    )
    await asyncio.sleep(0)

    release_mutex.set()
    await holder
    token = await candidate
    acquired.set()

    assert acquired.is_set()
    await service.release(token)


@pytest.mark.asyncio
async def test_m4_fix_06_deadline_is_not_reset():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")
    waiter = asyncio.create_task(
        service.acquire_with_wait(
            interval(9, 11),
            "court-1",
            timeout=1,
        )
    )
    await wait_for_waiter_count(service, 1)
    original = (await service.get_waiting_snapshot())[0].deadline

    await asyncio.sleep(0)
    async with service._registry_mutex:
        service._reconsider_waiters_locked()

    snapshot = await service.get_waiting_snapshot()
    assert snapshot[0].deadline == original

    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    await service.release(active)


@pytest.mark.asyncio
async def test_m4_fix_07_grant_deadline_boundary():
    service = ConcurrencyService()
    active = await service.acquire(interval(8, 10), "court-1")
    waiter = asyncio.create_task(
        service.acquire_with_wait(
            interval(9, 11),
            "court-1",
            timeout=1,
        )
    )
    await wait_for_waiter_count(service, 1)

    async with service._registry_mutex:
        waiting = next(iter(service._waiting_requests))
        waiting.deadline = asyncio.get_running_loop().time() - 1
        lock_token = service._grant_waiter_locked(waiting)

    assert lock_token is None
    with pytest.raises(LockWaitTimeoutError):
        await waiter

    assert await service.get_waiting_snapshot() == ()
    assert len(await service.get_active_reservations()) == 1
    await service.release(active)
