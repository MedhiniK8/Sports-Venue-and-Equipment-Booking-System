import asyncio
from datetime import datetime
from uuid import uuid4

import pytest

from app.contracts.booking import TimeInterval
from app.e1_concurrency.service import ConcurrencyService, InvalidLockTokenError


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
async def test_empty_registry():
    service = ConcurrencyService()

    assert await service.get_active_reservations() == ()


@pytest.mark.asyncio
async def test_first_registration():
    service = ConcurrencyService()

    result = await service.register_reservation(
        make_interval(8, 0, 10, 0),
        "court-1",
    )

    reservations = await service.get_active_reservations()
    assert result.registered is True
    assert result.reservation_id is not None
    assert len(reservations) == 1


@pytest.mark.asyncio
async def test_non_overlapping_registration():
    service = ConcurrencyService()

    first = await service.register_reservation(
        make_interval(8, 0, 10, 0),
        "court-1",
    )
    second = await service.register_reservation(
        make_interval(11, 0, 12, 0),
        "court-1",
    )

    assert first.registered is True
    assert second.registered is True
    assert len(await service.get_active_reservations()) == 2


@pytest.mark.asyncio
async def test_different_courts():
    service = ConcurrencyService()
    interval = make_interval(8, 0, 10, 0)

    first = await service.register_reservation(interval, "court-1")
    second = await service.register_reservation(interval, "court-2")

    assert first.registered is True
    assert second.registered is True
    assert len(await service.get_active_reservations()) == 2


@pytest.mark.asyncio
async def test_different_dates():
    service = ConcurrencyService()

    first = await service.register_reservation(
        make_interval(8, 0, 10, 0),
        "court-1",
    )
    second = await service.register_reservation(
        make_interval(8, 0, 10, 0, datetime(2026, 11, 25)),
        "court-1",
    )

    assert first.registered is True
    assert second.registered is True
    assert len(await service.get_active_reservations()) == 2


@pytest.mark.asyncio
async def test_adjacent_intervals():
    service = ConcurrencyService()

    first = await service.register_reservation(
        make_interval(8, 0, 9, 0),
        "court-1",
    )
    second = await service.register_reservation(
        make_interval(9, 0, 10, 0),
        "court-1",
    )

    assert first.registered is True
    assert second.registered is True
    assert len(await service.get_active_reservations()) == 2


@pytest.mark.asyncio
async def test_identical_interval_rejected():
    service = ConcurrencyService()
    interval = make_interval(8, 0, 10, 0)

    first = await service.register_reservation(interval, "court-1")
    second = await service.register_reservation(interval, "court-1")

    assert first.registered is True
    assert second.registered is False
    assert second.reason == "conflicting_active_reservation"
    assert len(await service.get_active_reservations()) == 1


@pytest.mark.asyncio
async def test_overlapping_registration_preserves_existing():
    service = ConcurrencyService()

    first = await service.register_reservation(
        make_interval(8, 0, 10, 0),
        "court-1",
    )
    second = await service.register_reservation(
        make_interval(9, 0, 11, 0),
        "court-1",
    )

    reservations = await service.get_active_reservations()
    assert first.registered is True
    assert second.registered is False
    assert len(reservations) == 1
    assert reservations[0].reservation_id == first.reservation_id


@pytest.mark.asyncio
async def test_controlled_removal():
    service = ConcurrencyService()
    first = await service.register_reservation(
        make_interval(8, 0, 10, 0),
        "court-1",
    )
    second = await service.register_reservation(
        make_interval(12, 0, 14, 0),
        "court-1",
    )

    assert first.reservation_id is not None
    assert await service.remove_reservation(first.reservation_id) is True
    reservations = await service.get_active_reservations()
    assert len(reservations) == 1
    assert reservations[0].reservation_id == second.reservation_id


@pytest.mark.asyncio
async def test_invalid_removal():
    service = ConcurrencyService()
    existing = await service.register_reservation(
        make_interval(8, 0, 10, 0),
        "court-1",
    )

    removed = await service.remove_reservation(uuid4())

    reservations = await service.get_active_reservations()
    assert removed is False
    assert len(reservations) == 1
    assert reservations[0].reservation_id == existing.reservation_id


@pytest.mark.asyncio
async def test_simultaneous_conflicting_requests():
    service = ConcurrencyService()
    start = asyncio.Event()

    async def register():
        await start.wait()
        return await service.register_reservation(
            make_interval(8, 0, 10, 0),
            "court-1",
        )

    tasks = [asyncio.create_task(register()) for _ in range(20)]
    start.set()
    results = await asyncio.gather(*tasks)

    assert sum(result.registered for result in results) == 1
    assert len(await service.get_active_reservations()) == 1


@pytest.mark.asyncio
async def test_simultaneous_non_overlapping_requests():
    service = ConcurrencyService()
    start = asyncio.Event()

    async def register(interval: TimeInterval):
        await start.wait()
        return await service.register_reservation(interval, "court-1")

    tasks = [
        asyncio.create_task(register(make_interval(8, 0, 10, 0))),
        asyncio.create_task(register(make_interval(12, 0, 14, 0))),
    ]
    start.set()
    results = await asyncio.gather(*tasks)

    assert all(result.registered for result in results)
    assert len(await service.get_active_reservations()) == 2


@pytest.mark.asyncio
async def test_internal_removal_cleans_matching_token_mapping():
    service = ConcurrencyService()
    interval = make_interval(8, 0, 10, 0)

    token = await service.acquire(interval, "court-1")
    async with service._registry_mutex:
        reservation_id = service._token_reservations[token.token]

    assert await service.remove_reservation(reservation_id) is True
    assert await service.get_active_reservations() == ()

    async with service._registry_mutex:
        assert service._token_reservations == {}

    with pytest.raises(InvalidLockTokenError):
        await service.release(token)


@pytest.mark.asyncio
async def test_internal_removal_does_not_affect_other_reservation_mapping():
    service = ConcurrencyService()
    first_interval = make_interval(8, 0, 10, 0)
    second_interval = make_interval(12, 0, 14, 0)

    first = await service.acquire(first_interval, "court-1")
    second = await service.acquire(second_interval, "court-1")
    async with service._registry_mutex:
        first_reservation_id = service._token_reservations[first.token]

    assert await service.remove_reservation(first_reservation_id) is True

    reservations = await service.get_active_reservations()
    assert len(reservations) == 1
    assert reservations[0].interval == second_interval

    async with service._registry_mutex:
        assert first.token not in service._token_reservations
        assert len(service._token_reservations) == 1