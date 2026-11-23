import pytest
from fastapi.testclient import TestClient

from app.e4_communication.coordinator import BookingCoordinator
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_app_starts(client):
    assert app.title
    coordinator = BookingCoordinator(
        allocation=object(),
        concurrency=object(),
        persistence=object(),
    )
    assert coordinator.allocation is not None
    assert coordinator.concurrency is not None
    assert coordinator.persistence is not None


def test_health_endpoint(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "sports-venue-booking",
    }
