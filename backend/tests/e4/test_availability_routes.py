from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.e4_communication.auth import AuthService
from app.e4_communication.routes import get_auth_service, get_booking_coordinator
from app.main import app


JWT_SECRET = "test-only-signing-key-with-at-least-32-bytes"


class AvailabilityCoordinator:
    def __init__(self, court_id: UUID) -> None:
        self.court_id = court_id
        self.intervals_by_date = {}

    async def get_court_availability(self, court_id: UUID, reference_date: date):
        if court_id != self.court_id:
            from app.e4_communication.coordinator import CourtAvailabilityNotFoundError
            raise CourtAvailabilityNotFoundError
        days = tuple(
            (
                booking_date,
                self.intervals_by_date.get(
                    booking_date,
                    [
                        _availability_interval(
                            booking_date,
                            time(6, 0),
                            time(9, 30),
                            "FREE",
                        )
                    ],
                ),
            )
            for offset in range(7)
            for booking_date in [reference_date + timedelta(days=offset)]
        )
        return court_id, reference_date, days


def _availability_interval(
    booking_date: date,
    start_time: time,
    end_time: time,
    status: str,
    owner_id: UUID | None = None,
    reference_id: UUID | None = None,
):
    return SimpleNamespace(
        interval=SimpleNamespace(
            start=datetime.combine(booking_date, start_time),
            end=datetime.combine(booking_date, end_time),
        ),
        status=SimpleNamespace(value=status),
        owner_id=owner_id,
        reference_id=reference_id,
    )


@pytest.fixture
def availability_client():
    court_id = uuid4()
    user_id = uuid4()
    auth_service = AuthService(
        repository=type("Repository", (), {})(),
        secret_key=JWT_SECRET,
        issuer="test-issuer",
        access_token_minutes=30,
    )
    coordinator = AvailabilityCoordinator(court_id)
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_booking_coordinator] = lambda: coordinator
    token = auth_service.create_access_token(user_id)
    try:
        with TestClient(app) as client:
            yield client, court_id, token, user_id, auth_service, coordinator
    finally:
        app.dependency_overrides.pop(get_auth_service, None)
        app.dependency_overrides.pop(get_booking_coordinator, None)


def test_availability_route_requires_authentication(availability_client):
    client, court_id, *_ = availability_client
    response = client.get(f"/api/courts/{court_id}/availability")
    assert response.status_code == 401


def test_availability_route_returns_seven_day_serialized_data(availability_client):
    client, court_id, token, *_ = availability_client
    reference_date = date(2027, 1, 3)
    response = client.get(
        f"/api/courts/{court_id}/availability",
        params={"reference_date": reference_date.isoformat()},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["court_id"] == str(court_id)
    assert body["reference_date"] == reference_date.isoformat()
    assert body["timezone"] == "Asia/Kolkata"
    assert body["opening_time"] == "06:00:00"
    assert body["closing_time"] == "20:00:00"
    assert len(body["days"]) == 7
    assert body["days"][0]["intervals"] == [
        {
            "start_time": "06:00:00",
            "end_time": "09:30:00",
            "status": "FREE",
            "is_mine": False,
        }
    ]
    assert "reference_id" not in body["days"][0]["intervals"][0]
    assert set(body["days"][0]["intervals"][0]) == {
        "start_time",
        "end_time",
        "status",
        "is_mine",
    }


@pytest.mark.parametrize(
    ("viewer", "owner", "expected_is_mine"),
    [
        ("student_a", "student_a", True),
        ("student_b", "student_a", False),
        ("student_a", "student_b", False),
    ],
)
def test_availability_route_marks_only_the_authenticated_booking_owner(
    availability_client,
    viewer,
    owner,
    expected_is_mine,
):
    client, court_id, _, student_a, auth_service, coordinator = availability_client
    student_b = uuid4()
    users = {"student_a": student_a, "student_b": student_b}
    owner_id = users[owner]
    booking_id = uuid4()
    reference_date = date(2027, 1, 3)
    coordinator.intervals_by_date[reference_date] = [
        _availability_interval(
            reference_date,
            time(9, 0),
            time(10, 0),
            "BOOKED",
            owner_id=owner_id,
            reference_id=booking_id,
        )
    ]

    token = auth_service.create_access_token(users[viewer])
    response = client.get(
        f"/api/courts/{court_id}/availability",
        params={"reference_date": reference_date.isoformat()},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    interval = response.json()["days"][0]["intervals"][0]
    assert interval["is_mine"] is expected_is_mine
    assert set(interval) == {"start_time", "end_time", "status", "is_mine"}
    assert str(owner_id) not in response.text
    assert str(booking_id) not in response.text


def test_adjacent_bookings_keep_individual_ownership_in_api_response(
    availability_client,
):
    client, court_id, _, student_a, auth_service, coordinator = availability_client
    student_b = uuid4()
    first_booking_id, second_booking_id = uuid4(), uuid4()
    reference_date = date(2027, 1, 3)
    coordinator.intervals_by_date[reference_date] = [
        _availability_interval(
            reference_date,
            time(9, 0),
            time(10, 0),
            "BOOKED",
            owner_id=student_a,
            reference_id=first_booking_id,
        ),
        _availability_interval(
            reference_date,
            time(10, 0),
            time(11, 0),
            "BOOKED",
            owner_id=student_b,
            reference_id=second_booking_id,
        ),
    ]

    for viewer_id, expected in (
        (student_a, [True, False]),
        (student_b, [False, True]),
    ):
        token = auth_service.create_access_token(viewer_id)
        response = client.get(
            f"/api/courts/{court_id}/availability",
            params={"reference_date": reference_date.isoformat()},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        intervals = response.json()["days"][0]["intervals"]
        assert [interval["is_mine"] for interval in intervals] == expected
        assert all(set(interval) == {
            "start_time",
            "end_time",
            "status",
            "is_mine",
        } for interval in intervals)
        assert str(student_a) not in response.text
        assert str(student_b) not in response.text
        assert str(first_booking_id) not in response.text
        assert str(second_booking_id) not in response.text


def test_free_and_blocked_intervals_are_not_owned(availability_client):
    client, court_id, _, student_a, auth_service, coordinator = availability_client
    reference_date = date(2027, 1, 3)
    coordinator.intervals_by_date[reference_date] = [
        _availability_interval(
            reference_date, time(6, 0), time(9, 0), "FREE"
        ),
        _availability_interval(
            reference_date,
            time(9, 0),
            time(10, 0),
            "BLOCKED",
            owner_id=student_a,
            reference_id=uuid4(),
        ),
        _availability_interval(
            reference_date, time(10, 0), time(20, 0), "FREE"
        ),
    ]

    token = auth_service.create_access_token(student_a)
    response = client.get(
        f"/api/courts/{court_id}/availability",
        params={"reference_date": reference_date.isoformat()},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    intervals = response.json()["days"][0]["intervals"]
    assert [interval["status"] for interval in intervals] == [
        "FREE",
        "BLOCKED",
        "FREE",
    ]
    assert [interval["is_mine"] for interval in intervals] == [
        False,
        False,
        False,
    ]
    assert all("owner_id" not in interval for interval in intervals)
    assert all("reference_id" not in interval for interval in intervals)


def test_availability_route_reports_unknown_court(availability_client):
    client, _, token, *_ = availability_client
    response = client.get(
        f"/api/courts/{uuid4()}/availability",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


def test_availability_route_rejects_invalid_uuid(availability_client):
    client, _, token, *_ = availability_client
    response = client.get(
        "/api/courts/not-a-uuid/availability",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
