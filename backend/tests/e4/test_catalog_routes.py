from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.e3_persistence.inputs import (
    CourtCatalogRecord,
    EquipmentCatalogRecord,
    SportCatalogRecord,
)
from app.e4_communication.auth import AuthService
from app.e4_communication.routes import (
    get_auth_service,
    get_persistence_repository,
)
from app.main import app

JWT_SECRET = "test-only-signing-key-with-at-least-32-bytes"


class CatalogRepository:
    def __init__(self) -> None:
        self.user_id = uuid4()
        self.sport_id = uuid4()
        self.court_id = uuid4()
        self.equipment_id = uuid4()
        self.sports = (SportCatalogRecord(self.sport_id, "Badminton"),)
        self.courts = (CourtCatalogRecord(self.court_id, "Court A"),)
        self.equipment = (EquipmentCatalogRecord(self.equipment_id, "Racket"),)
        self.calls: list[tuple[str, UUID | None]] = []

    async def list_active_sports(self):
        self.calls.append(("sports", None))
        return self.sports

    async def list_active_courts_for_sport(self, sport_id: UUID):
        self.calls.append(("courts", sport_id))
        return self.courts if sport_id == self.sport_id else None

    async def list_active_equipment(self):
        self.calls.append(("equipment", None))
        return self.equipment


@pytest.fixture
def catalog_client():
    repository = CatalogRepository()
    auth_service = AuthService(
        repository=repository,
        secret_key=JWT_SECRET,
        issuer="test-issuer",
        access_token_minutes=30,
    )
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_persistence_repository] = lambda: repository
    token = auth_service.create_access_token(repository.user_id)
    try:
        with TestClient(app) as client:
            yield client, repository, token
    finally:
        app.dependency_overrides.pop(get_auth_service, None)
        app.dependency_overrides.pop(get_persistence_repository, None)


def test_catalog_routes_require_authentication(catalog_client):
    client, repository, _ = catalog_client

    responses = (
        client.get("/api/catalog/sports"),
        client.get("/api/catalog/sports/" + str(repository.sport_id) + "/courts"),
        client.get("/api/catalog/equipment"),
    )

    assert [response.status_code for response in responses] == [401, 401, 401]
    assert repository.calls == []


def test_catalog_routes_return_active_items_and_serialize_uuids(catalog_client):
    client, repository, token = catalog_client
    headers = {"Authorization": f"Bearer {token}"}

    sports = client.get("/api/catalog/sports", headers=headers)
    courts = client.get(
        f"/api/catalog/sports/{repository.sport_id}/courts",
        headers=headers,
    )
    equipment = client.get("/api/catalog/equipment", headers=headers)

    assert sports.status_code == courts.status_code == equipment.status_code == 200
    assert sports.json() == [
        {"sport_id": str(repository.sport_id), "name": "Badminton"}
    ]
    assert courts.json() == [
        {"court_id": str(repository.court_id), "name": "Court A"}
    ]
    assert equipment.json() == [
        {"equipment_id": str(repository.equipment_id), "name": "Racket"}
    ]
    assert repository.calls == [
        ("sports", None),
        ("courts", repository.sport_id),
        ("equipment", None),
    ]


def test_catalog_routes_return_empty_lists_for_empty_results(catalog_client):
    client, repository, token = catalog_client
    repository.sports = ()
    repository.courts = ()
    repository.equipment = ()
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/catalog/sports", headers=headers).json() == []
    assert (
        client.get(
            f"/api/catalog/sports/{repository.sport_id}/courts",
            headers=headers,
        ).json()
        == []
    )
    assert client.get("/api/catalog/equipment", headers=headers).json() == []


def test_catalog_courts_report_unknown_sport_and_invalid_uuid(catalog_client):
    client, repository, token = catalog_client
    headers = {"Authorization": f"Bearer {token}"}

    unknown = client.get(f"/api/catalog/sports/{uuid4()}/courts", headers=headers)
    invalid = client.get("/api/catalog/sports/not-a-uuid/courts", headers=headers)

    assert unknown.status_code == 404
    assert unknown.json()["detail"] == {
        "code": "sport_not_found",
        "message": "Sport was not found or is inactive",
    }
    assert invalid.status_code == 422
