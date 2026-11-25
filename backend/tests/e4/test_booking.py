
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.contracts.booking import (
    LockToken,
    TransactionResult,
    ValidationResult,
)
from app.contracts.interfaces import (
    AllocationInterface,
    ConcurrencyLockInterface,
)
from app.e4_communication.coordinator import (
    BookingCoordinator,
)


COURT_ID = "11111111-1111-4111-8111-111111111111"
EQUIPMENT_ID = "22222222-2222-4222-8222-222222222222"

VALID_PAYLOAD = {
    "court_id": COURT_ID,
    "equipment_id": None,
    "date": "2026-11-25",
    "starting_time": "10:00",
    "ending_time": "11:00",
}


class FakeAllocation(AllocationInterface):

    def __init__(self, valid=True, post_commit_fails=False):
        self.valid = valid
        self.post_commit_fails = post_commit_fails
        self.called = False
        self.post_commit_called = False

    async def validate_time_slot(
        self,
        court_id,
        equipment_id,
        interval,
    ):
        self.called = True

        return ValidationResult(
            valid=self.valid,
            errors=(
                [] if self.valid
                else ["Requested time slot is unavailable"]
            ),
        )

    async def generate_calendar(self, interval):
        return [interval]

    async def process_post_commit_split_merge(self, transaction):
        self.post_commit_called = True
        if self.post_commit_fails:
            raise RuntimeError("Post-commit processing failed")
        return []


class FakeConcurrency(ConcurrencyLockInterface):

    def __init__(self, lock_available=True, release_fails=False):
        self.lock_available = lock_available
        self.release_fails = release_fails
        self.acquire_called = False
        self.release_called = False

    async def acquire(self, interval, resource_id):
        self.acquire_called = True

        if not self.lock_available:
            raise RuntimeError("Lock unavailable")

        return LockToken(
            token=uuid4(),
            interval=interval,
        )

    async def release(self, token):
        self.release_called = True
        if self.release_fails:
            raise RuntimeError("Lock release failed")


class FakePersistence:

    def __init__(self, succeeded=True, missing_booking_id=False):
        self.succeeded = succeeded
        self.missing_booking_id = missing_booking_id
        self.called = False

    async def create_booking(self, request):
        self.called = True

        return TransactionResult(
            succeeded=self.succeeded,
            booking_id=(
                None
                if self.missing_booking_id
                else uuid4() if self.succeeded
                else None
            ),
            transaction_id=uuid4(),
            error_code=(
                None if self.succeeded else "DATABASE_ERROR"
            ),
        )


def create_test_client(
    allocation=None,
    concurrency=None,
    persistence=None,
):
    allocation = allocation or FakeAllocation()
    concurrency = concurrency or FakeConcurrency()
    persistence = persistence or FakePersistence()

    coordinator = BookingCoordinator(
        allocation=allocation,
        concurrency=concurrency,
        persistence=persistence,
    )

    app.state.booking_coordinator = coordinator

    return (
        TestClient(app),
        allocation,
        concurrency,
        persistence,
    )


def test_successful_booking():

    client, allocation, concurrency, persistence = (
        create_test_client()
    )

    response = client.post(
        "/api/bookings",
        json=VALID_PAYLOAD,
    )

    assert response.status_code == 201
    assert response.json()["status"] == "CONFIRMED"
    assert response.json()["court_id"] == COURT_ID
    assert response.json()["equipment_id"] is None

    # Booking ID is returned by the persistence dependency.
    UUID(response.json()["booking_id"])

    assert allocation.called is True
    assert concurrency.acquire_called is True
    assert persistence.called is True
    assert concurrency.release_called is True


def test_invalid_time_slot():

    allocation = FakeAllocation(valid=False)
    concurrency = FakeConcurrency()
    persistence = FakePersistence()

    client, allocation, concurrency, persistence = (
        create_test_client(
            allocation,
            concurrency,
            persistence,
        )
    )

    response = client.post(
        "/api/bookings",
        json=VALID_PAYLOAD,
    )

    assert response.status_code == 422
    assert allocation.called is True
    assert concurrency.acquire_called is False
    assert persistence.called is False


def test_lock_unavailable():

    allocation = FakeAllocation()
    concurrency = FakeConcurrency(lock_available=False)
    persistence = FakePersistence()

    client, allocation, concurrency, persistence = (
        create_test_client(
            allocation,
            concurrency,
            persistence,
        )
    )

    response = client.post(
        "/api/bookings",
        json=VALID_PAYLOAD,
    )

    assert response.status_code == 409
    assert concurrency.acquire_called is True
    assert persistence.called is False


def test_transaction_failure_releases_lock():

    allocation = FakeAllocation()
    concurrency = FakeConcurrency()
    persistence = FakePersistence(succeeded=False)

    client, allocation, concurrency, persistence = (
        create_test_client(
            allocation,
            concurrency,
            persistence,
        )
    )

    response = client.post(
        "/api/bookings",
        json=VALID_PAYLOAD,
    )

    assert response.status_code == 500
    assert persistence.called is True
    assert concurrency.acquire_called is True
    assert concurrency.release_called is True


def test_invalid_request_body():

    invalid_payload = {
        **VALID_PAYLOAD,
        "court_id": "not-a-valid-uuid",
    }

    client, _, concurrency, persistence = (
        create_test_client()
    )

    response = client.post(
        "/api/bookings",
        json=invalid_payload,
    )

    assert response.status_code == 422
    assert concurrency.acquire_called is False
    assert persistence.called is False


def test_coordinator_unavailable():

    original_coordinator = getattr(
        app.state,
        "booking_coordinator",
        None,
    )

    try:
        app.state.booking_coordinator = None

        with TestClient(app) as client:
            response = client.post(
                "/api/bookings",
                json=VALID_PAYLOAD,
            )

        assert response.status_code == 503

    finally:
        app.state.booking_coordinator = original_coordinator


def test_optional_equipment_booking():
    payload = {
        **VALID_PAYLOAD,
        "equipment_id": EQUIPMENT_ID,
    }

    client, allocation, concurrency, persistence = create_test_client()
    response = client.post("/api/bookings", json=payload)

    assert response.status_code == 201
    assert response.json()["equipment_id"] == EQUIPMENT_ID
    assert allocation.called is True
    assert concurrency.acquire_called is True
    assert persistence.called is True
    assert concurrency.release_called is True


def test_missing_persistence_booking_id():
    persistence = FakePersistence(missing_booking_id=True)

    client, _, concurrency, persistence = create_test_client(
        persistence=persistence,
    )
    response = client.post("/api/bookings", json=VALID_PAYLOAD)

    assert response.status_code == 500
    assert persistence.called is True
    assert concurrency.release_called is True


def test_post_commit_failure_does_not_unconfirm_booking():
    allocation = FakeAllocation(post_commit_fails=True)

    client, allocation, concurrency, persistence = create_test_client(
        allocation=allocation,
    )
    response = client.post("/api/bookings", json=VALID_PAYLOAD)

    assert response.status_code == 201
    assert response.json()["status"] == "CONFIRMED"
    assert allocation.post_commit_called is True
    assert concurrency.release_called is True


def test_lock_release_failure_is_logged_and_booking_is_still_confirmed():
    concurrency = FakeConcurrency(release_fails=True)

    client, _, concurrency, persistence = create_test_client(
        concurrency=concurrency,
    )
    response = client.post("/api/bookings", json=VALID_PAYLOAD)

    assert response.status_code == 201
    assert response.json()["status"] == "CONFIRMED"
    assert persistence.called is True
    assert concurrency.release_called is True


def test_not_implemented_dependency_returns_service_unavailable():
    class NotImplementedAllocation(FakeAllocation):
        async def validate_time_slot(
            self,
            court_id,
            equipment_id,
            interval,
        ):
            raise NotImplementedError

    client, _, _, _ = create_test_client(
        allocation=NotImplementedAllocation(),
    )
    response = client.post("/api/bookings", json=VALID_PAYLOAD)

    assert response.status_code == 503


@pytest.mark.parametrize(
    "allocation, concurrency, persistence",
    [
        (object(), FakeConcurrency(), FakePersistence()),
        (FakeAllocation(), object(), FakePersistence()),
        (FakeAllocation(), FakeConcurrency(), object()),
    ],
)
def test_missing_dependency_rejects_coordinator(
    allocation,
    concurrency,
    persistence,
):
    with pytest.raises(ValueError):
        BookingCoordinator(
            allocation=allocation,
            concurrency=concurrency,
            persistence=persistence,
        )
