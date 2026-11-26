from datetime import date, time, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.e3_persistence.errors import (
    BookingStartTimeExpiredError,
    DuplicateStudentError,
)
from app.e3_persistence.inputs import (
    BookingRecord,
    CreateStudentInput,
    StudentAccountRecord,
)
from app.e4_communication.auth import AuthService, verify_password
from app.e4_communication.coordinator import BookingCommittedCacheRefreshError
from app.e4_communication.routes import get_auth_service, get_booking_coordinator
from app.e4_communication.schemas import (
    BookingRequestCancelledResponse,
    EquipmentDecisionRequiredResponse,
    EquipmentShortageResponse,
    StudentBookingRequest,
)
from app.main import app

JWT_SECRET = "test-only-signing-key-with-at-least-32-bytes"


class InMemoryStudentRepository:
    def __init__(self) -> None:
        self.accounts: dict[UUID, StudentAccountRecord] = {}
        self.revoked: set[str] = set()

    async def create_student(
        self, student: CreateStudentInput
    ) -> StudentAccountRecord:
        if any(account.usn == student.usn for account in self.accounts.values()):
            raise DuplicateStudentError("USN")
        if any(
            account.college_email == student.college_email
            for account in self.accounts.values()
        ):
            raise DuplicateStudentError("college email")

        account = StudentAccountRecord(
            user_id=uuid4(),
            usn=student.usn,
            student_name=student.student_name,
            role=student.role,
            password_hash=student.password_hash,
            college_email=student.college_email,
            phone_number=student.phone_number,
            year_of_admission=student.year_of_admission,
            gender=student.gender,
            branch=student.branch,
        )
        self.accounts[account.user_id] = account
        return account

    async def get_student_by_usn(self, usn: str) -> StudentAccountRecord | None:
        return next(
            (account for account in self.accounts.values() if account.usn == usn),
            None,
        )

    async def get_student_by_id(self, user_id: UUID) -> StudentAccountRecord | None:
        return self.accounts.get(user_id)

    async def get_student_by_identifier(self, identifier: str) -> StudentAccountRecord | None:
        normalized = identifier.strip().lower()
        return next(
            (
                account
                for account in self.accounts.values()
                if account.usn == identifier.strip()
                or account.college_email.lower() == normalized
            ),
            None,
        )

    async def update_student(
        self,
        user_id: UUID,
        *,
        student_name: str,
    ) -> StudentAccountRecord:
        account = self.accounts[user_id]
        updated = StudentAccountRecord(
            user_id=user_id,
            usn=account.usn,
            password_hash=account.password_hash,
            college_email=account.college_email,
            phone_number=account.phone_number,
            year_of_admission=account.year_of_admission,
            gender=account.gender,
            branch=account.branch,
            student_name=student_name,
            role=account.role,
        )
        self.accounts[user_id] = updated
        return updated

    async def update_student_password(
        self,
        user_id: UUID,
        password_hash: str,
    ) -> bool:
        account = self.accounts[user_id]
        self.accounts[user_id] = StudentAccountRecord(
            **{
                **account.__dict__,
                "password_hash": password_hash,
            }
        )
        return True

    async def revoke_token(self, jti: str, expires_at) -> None:
        self.revoked.add(jti)

    async def is_token_revoked(self, jti: str) -> bool:
        return jti in self.revoked


@pytest.fixture
def auth_client():
    repository = InMemoryStudentRepository()
    service = AuthService(
        repository=repository,
        secret_key=JWT_SECRET,
        issuer="test-issuer",
        access_token_minutes=30,
    )
    app.dependency_overrides[get_auth_service] = lambda: service
    with TestClient(app) as client:
        yield client, repository
    app.dependency_overrides.pop(get_auth_service, None)


def registration_payload() -> dict[str, object]:
    return {
        "student_name": "Test Student",
        "usn": "1AB23CS001",
        "password": "a-strong-password",
        "confirm_password": "a-strong-password",
        "college_email": "student@example.edu",
        "phone_number": "9876543210",
        "branch": "Computer Science",
    }


def test_register_persists_only_password_hash_and_returns_safe_student(auth_client):
    client, repository = auth_client

    response = client.post("/api/auth/register", json=registration_payload())

    assert response.status_code == 201
    body = response.json()
    account = next(iter(repository.accounts.values()))
    assert body["user_id"] == str(account.user_id)
    assert "password" not in body
    assert "password_hash" not in body
    assert "confirm_password" not in body
    assert verify_password("a-strong-password", account.password_hash)
    assert account.year_of_admission is None
    assert account.gender is None


def test_registration_rejects_mismatched_confirmation_without_echoing_password(
    auth_client,
):
    client, _ = auth_client
    payload = registration_payload()
    payload["confirm_password"] = "different-password"

    response = client.post("/api/auth/register", json=payload)

    assert response.status_code == 422
    assert "a-strong-password" not in response.text
    assert "different-password" not in response.text


def test_registration_reports_duplicate_usn_as_conflict(auth_client):
    client, _ = auth_client
    payload = registration_payload()

    assert client.post("/api/auth/register", json=payload).status_code == 201
    duplicate = client.post("/api/auth/register", json=payload)

    assert duplicate.status_code == 409
    assert "USN" in duplicate.json()["detail"]


def test_registration_reports_duplicate_college_email_as_conflict(auth_client):
    client, _ = auth_client
    payload = registration_payload()

    assert client.post("/api/auth/register", json=payload).status_code == 201
    duplicate = client.post(
        "/api/auth/register",
        json={**payload, "usn": "1AB23CS002"},
    )

    assert duplicate.status_code == 409
    assert "college email" in duplicate.json()["detail"]


def test_name_only_profile_patch_preserves_other_profile_fields(auth_client):
    client, repository = auth_client
    assert client.post("/api/auth/register", json=registration_payload()).status_code == 201
    login = client.post(
        "/api/auth/login",
        json={"identifier": "1AB23CS001", "password": "a-strong-password"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    before = next(iter(repository.accounts.values()))

    response = client.patch(
        "/api/auth/me",
        headers=headers,
        json={"student_name": "Updated Student"},
    )

    assert response.status_code == 200
    account = next(iter(repository.accounts.values()))
    assert account.student_name == "Updated Student"
    assert account.college_email == before.college_email
    assert account.usn == before.usn
    assert account.phone_number == before.phone_number
    assert account.branch == before.branch
    assert account.role == before.role


def test_profile_patch_rejects_restricted_fields_without_changes(auth_client):
    client, repository = auth_client
    assert client.post("/api/auth/register", json=registration_payload()).status_code == 201
    login = client.post(
        "/api/auth/login",
        json={"identifier": "1AB23CS001", "password": "a-strong-password"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    before = next(iter(repository.accounts.values()))

    response = client.patch(
        "/api/auth/me",
        headers=headers,
        json={
            "student_name": "Attempted Student",
            "college_email": "other@example.edu",
            "usn": "2CD23CS002",
            "phone_number": "1234567890",
            "branch": "Other Branch",
            "role": "ADMIN",
        },
    )

    assert response.status_code == 422
    account = next(iter(repository.accounts.values()))
    assert account == before


def test_profile_patch_rejects_empty_update(auth_client):
    client, _ = auth_client
    assert client.post("/api/auth/register", json=registration_payload()).status_code == 201
    login = client.post(
        "/api/auth/login",
        json={"identifier": "1AB23CS001", "password": "a-strong-password"},
    )
    response = client.patch(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={},
    )
    assert response.status_code == 422


def test_login_issues_bearer_token_for_database_identity(auth_client):
    client, _ = auth_client
    registration = client.post("/api/auth/register", json=registration_payload())
    assert registration.status_code == 201

    login = client.post(
        "/api/auth/login",
        json={"identifier": "1AB23CS001", "password": "a-strong-password"},
    )
    assert login.status_code == 200
    assert login.json()["token_type"] == "bearer"

    current = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert current.status_code == 200
    assert current.json()["user_id"] == registration.json()["user_id"]
    assert "password_hash" not in current.json()


def test_login_and_bearer_auth_reject_invalid_credentials_and_tokens(auth_client):
    client, _ = auth_client
    bad_login = client.post(
        "/api/auth/login",
        json={"identifier": "missing", "password": "wrong"},
    )
    no_token = client.get("/api/auth/me")
    invalid_token = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer invalid"},
    )

    assert bad_login.status_code == 401
    assert no_token.status_code == 401
    assert invalid_token.status_code == 401


def test_booking_route_uses_authenticated_student_identity(auth_client):
    client, repository = auth_client

    class StubBookingCoordinator:
        async def coordinate_student_booking(self, request, user_id):
            account = next(iter(repository.accounts.values()))
            assert user_id == account.user_id
            return BookingRecord(
                booking_id=uuid4(),
                user_id=user_id,
                court_id=request.court_id,
                booking_date=request.booking_date,
                start_time=request.start_time,
                end_time=request.end_time,
                status="BOOKED",
                items=(),
            )

    app.dependency_overrides[get_booking_coordinator] = lambda: StubBookingCoordinator()
    try:
        registration = client.post("/api/auth/register", json=registration_payload())
        login = client.post(
            "/api/auth/login",
            json={"identifier": "1AB23CS001", "password": "a-strong-password"},
        )
        response = client.post(
            "/api/bookings",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
            json={
                "court_id": str(uuid4()),
                "booking_date": (date.today() + timedelta(days=1)).isoformat(),
                "start_time": "09:00",
                "end_time": "10:00",
                "equipment": [],
            },
        )
    finally:
        app.dependency_overrides.pop(get_booking_coordinator, None)

    assert registration.status_code == 201
    assert login.status_code == 200
    assert response.status_code == 201
    assert response.json()["status"] == "BOOKED"


def test_booking_decision_schema_accepts_only_the_two_confirmed_choices():
    base = {
        "court_id": str(uuid4()),
        "booking_date": (date.today() + timedelta(days=1)).isoformat(),
        "start_time": "09:00",
        "end_time": "10:00",
    }

    for decision in ("CONTINUE_WITHOUT_EQUIPMENT", "CANCEL_REQUEST"):
        request = StudentBookingRequest.model_validate(
            {**base, "equipment_decision": decision}
        )
        assert request.equipment_decision == decision

    with pytest.raises(ValueError):
        StudentBookingRequest.model_validate(
            {**base, "equipment_decision": "PARTIAL_ALLOCATION"}
        )


def test_booking_schema_rejects_timezone_aware_venue_times():
    with pytest.raises(ValueError, match="timezone-naive"):
        StudentBookingRequest(
            court_id=uuid4(),
            booking_date=date.today() + timedelta(days=1),
            start_time=time(9, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))),
            end_time=time(10, 0),
        )


def test_invalid_booking_time_never_reaches_coordinator(auth_client):
    client, _ = auth_client
    coordinator_calls = []

    class StubBookingCoordinator:
        async def coordinate_student_booking(self, request, user_id):
            coordinator_calls.append((request, user_id))

    app.dependency_overrides[get_booking_coordinator] = lambda: StubBookingCoordinator()
    try:
        client.post("/api/auth/register", json=registration_payload())
        login = client.post(
            "/api/auth/login",
            json={"identifier": "1AB23CS001", "password": "a-strong-password"},
        )
        response = client.post(
            "/api/bookings",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
            json={
                "court_id": str(uuid4()),
                "booking_date": (date.today() + timedelta(days=1)).isoformat(),
                "start_time": "09:00+05:30",
                "end_time": "10:00",
            },
        )
    finally:
        app.dependency_overrides.pop(get_booking_coordinator, None)

    assert response.status_code == 422
    assert coordinator_calls == []


def test_persistence_start_time_conflict_maps_to_http_conflict(auth_client):
    client, _ = auth_client

    class StubBookingCoordinator:
        async def coordinate_student_booking(self, request, user_id):
            raise BookingStartTimeExpiredError

    app.dependency_overrides[get_booking_coordinator] = lambda: StubBookingCoordinator()
    try:
        client.post("/api/auth/register", json=registration_payload())
        login = client.post(
            "/api/auth/login",
            json={"identifier": "1AB23CS001", "password": "a-strong-password"},
        )
        response = client.post(
            "/api/bookings",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
            json={
                "court_id": str(uuid4()),
                "booking_date": (date.today() + timedelta(days=1)).isoformat(),
                "start_time": "09:00",
                "end_time": "10:00",
            },
        )
    finally:
        app.dependency_overrides.pop(get_booking_coordinator, None)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "booking_start_time_passed"


def test_booking_route_returns_structured_equipment_decision_required(auth_client):
    client, repository = auth_client
    shortage = EquipmentShortageResponse(
        equipment_id=uuid4(),
        requested_quantity=3,
        available_quantity=1,
    )

    class StubBookingCoordinator:
        async def coordinate_student_booking(self, request, user_id):
            account = next(iter(repository.accounts.values()))
            assert user_id == account.user_id
            assert request.equipment_decision is None
            return EquipmentDecisionRequiredResponse(shortages=(shortage,))

    app.dependency_overrides[get_booking_coordinator] = lambda: StubBookingCoordinator()
    try:
        client.post("/api/auth/register", json=registration_payload())
        login = client.post(
            "/api/auth/login",
            json={"identifier": "1AB23CS001", "password": "a-strong-password"},
        )
        response = client.post(
            "/api/bookings",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
            json={
                "court_id": str(uuid4()),
                "booking_date": (date.today() + timedelta(days=1)).isoformat(),
                "start_time": "09:00",
                "end_time": "10:00",
                "equipment": [
                    {"equipment_id": str(shortage.equipment_id), "quantity": 3}
                ],
            },
        )
    finally:
        app.dependency_overrides.pop(get_booking_coordinator, None)

    assert response.status_code == 409
    assert response.json() == {
        "code": "EQUIPMENT_DECISION_REQUIRED",
        "message": (
            "Choose whether to continue without unavailable equipment or cancel."
        ),
        "shortages": [
            {
                "equipment_id": str(shortage.equipment_id),
                "requested_quantity": 3,
                "available_quantity": 1,
            }
        ],
        "permitted_decisions": [
            "CONTINUE_WITHOUT_EQUIPMENT",
            "CANCEL_REQUEST",
        ],
    }


def test_booking_route_cancel_response_says_no_booking_was_created(auth_client):
    client, repository = auth_client

    class StubBookingCoordinator:
        async def coordinate_student_booking(self, request, user_id):
            account = next(iter(repository.accounts.values()))
            assert user_id == account.user_id
            assert request.equipment_decision == "CANCEL_REQUEST"
            return BookingRequestCancelledResponse()

    app.dependency_overrides[get_booking_coordinator] = lambda: StubBookingCoordinator()
    try:
        client.post("/api/auth/register", json=registration_payload())
        login = client.post(
            "/api/auth/login",
            json={"identifier": "1AB23CS001", "password": "a-strong-password"},
        )
        response = client.post(
            "/api/bookings",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
            json={
                "court_id": str(uuid4()),
                "booking_date": (date.today() + timedelta(days=1)).isoformat(),
                "start_time": "09:00",
                "end_time": "10:00",
                "equipment_decision": "CANCEL_REQUEST",
            },
        )
    finally:
        app.dependency_overrides.pop(get_booking_coordinator, None)

    assert response.status_code == 200
    assert response.json() == {
        "code": "BOOKING_NOT_CREATED",
        "request_cancelled": True,
        "booking_created": False,
        "message": "Request cancelled; no booking was created.",
    }


def test_booking_route_reports_committed_booking_if_cache_refresh_fails(auth_client):
    client, repository = auth_client
    booking_id = uuid4()

    class StubBookingCoordinator:
        async def coordinate_student_booking(self, request, user_id):
            account = next(iter(repository.accounts.values()))
            assert user_id == account.user_id
            raise BookingCommittedCacheRefreshError(booking_id)

    app.dependency_overrides[get_booking_coordinator] = lambda: StubBookingCoordinator()
    try:
        client.post("/api/auth/register", json=registration_payload())
        login = client.post(
            "/api/auth/login",
            json={"identifier": "1AB23CS001", "password": "a-strong-password"},
        )
        response = client.post(
            "/api/bookings",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
            json={
                "court_id": str(uuid4()),
                "booking_date": (date.today() + timedelta(days=1)).isoformat(),
                "start_time": "09:00",
                "end_time": "10:00",
            },
        )
    finally:
        app.dependency_overrides.pop(get_booking_coordinator, None)

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "booking_committed_refresh_failed",
        "booking_id": str(booking_id),
        "committed": True,
    }


def test_booking_history_and_cancellation_routes_require_authenticated_owner(
    auth_client,
):
    client, repository = auth_client
    booking_id = uuid4()
    court_id = uuid4()

    class StubBookingCoordinator:
        async def list_student_bookings(self, user_id):
            account = next(iter(repository.accounts.values()))
            assert user_id == account.user_id
            return [
                BookingRecord(
                    booking_id=booking_id,
                    user_id=user_id,
                    court_id=court_id,
                    booking_date=date.today() + timedelta(days=1),
                    start_time=time(9, 0),
                    end_time=time(10, 0),
                    status="BOOKED",
                    items=(),
                )
            ]

        async def coordinate_student_cancellation(self, requested_id, user_id):
            account = next(iter(repository.accounts.values()))
            assert user_id == account.user_id
            assert requested_id == booking_id
            return BookingRecord(
                booking_id=booking_id,
                user_id=user_id,
                court_id=court_id,
                booking_date=date.today() + timedelta(days=1),
                start_time=time(9, 0),
                end_time=time(10, 0),
                status="CANCELLED",
                items=(),
            )

    app.dependency_overrides[get_booking_coordinator] = lambda: StubBookingCoordinator()
    try:
        client.post("/api/auth/register", json=registration_payload())
        login = client.post(
            "/api/auth/login",
            json={"identifier": "1AB23CS001", "password": "a-strong-password"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        history = client.get("/api/bookings", headers=headers)
        cancelled = client.delete(
            f"/api/bookings/{booking_id}",
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_booking_coordinator, None)

    assert history.status_code == 200
    assert history.json()[0]["booking_id"] == str(booking_id)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
