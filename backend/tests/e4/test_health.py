from fastapi.testclient import TestClient

from app.main import app
import pytest


@pytest.fixture
def client():
    original_coordinator = getattr(app.state, "booking_coordinator", None)
    app.state.booking_coordinator = None
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.state.booking_coordinator = original_coordinator


def test_app_starts(client):
    assert app.title
    assert getattr(app.state, "booking_coordinator", None) is None


def test_health_endpoint(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "sports-venue-booking",
    }
