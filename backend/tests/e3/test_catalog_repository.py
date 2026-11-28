from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.e3_persistence.inputs import (
    CourtCatalogRecord,
    EquipmentCatalogRecord,
    SportCatalogRecord,
)
from app.e3_persistence.catalog import APPROVED_SPORT_NAMES
from app.e3_persistence.models import Base, Court, EquipmentItem, Sport
from app.e3_persistence.repository import SqlAlchemyPersistenceRepository


async def make_catalog_repository():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def install_sqlite_functions(connection, _record):
        async def configure(connection_adapter):
            def second(value: str) -> int:
                return int(value.split(":")[2].split(".")[0])

            await connection_adapter.create_function("SECOND", 1, second)
            await connection_adapter.execute("PRAGMA foreign_keys=ON")

        connection.run_async(configure)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory, SqlAlchemyPersistenceRepository(session_factory)


@pytest.mark.asyncio
async def test_catalog_repository_lists_active_approved_sports_and_active_courts():
    engine, session_factory, repository = await make_catalog_repository()
    try:
        active_sport_id, tennis_id, football_id, inactive_sport_id = (
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
        )
        active_court_id, inactive_court_id, tennis_court_id = (
            uuid4(),
            uuid4(),
            uuid4(),
        )
        async with session_factory.begin() as session:
            session.add_all(
                [
                    Sport(sport_id=active_sport_id, name="Badminton", is_active=True),
                    Sport(sport_id=tennis_id, name="Tennis", is_active=True),
                    Sport(sport_id=football_id, name="Football", is_active=True),
                    Sport(sport_id=inactive_sport_id, name="Archived", is_active=False),
                    Court(
                        court_id=active_court_id,
                        sport_id=active_sport_id,
                        name="Court A",
                        is_active=True,
                    ),
                    Court(
                        court_id=inactive_court_id,
                        sport_id=active_sport_id,
                        name="Court B",
                        is_active=False,
                    ),
                    Court(
                        court_id=tennis_court_id,
                        sport_id=tennis_id,
                        name="Court C",
                        is_active=True,
                    ),
                ]
            )

        assert await repository.list_active_sports() == (
            SportCatalogRecord(active_sport_id, "Badminton"),
        )
        assert await repository.list_active_courts_for_sport(active_sport_id) == (
            CourtCatalogRecord(active_court_id, "Court A"),
        )
        assert await repository.list_active_courts_for_sport(uuid4()) is None
        assert (
            await repository.list_active_courts_for_sport(inactive_sport_id)
            is None
        )
        assert set(APPROVED_SPORT_NAMES) == {
            "Basketball",
            "Badminton",
            "Table Tennis",
            "Squash",
            "Volleyball",
            "Kabaddi",
        }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_catalog_repository_returns_all_active_approved_sports():
    engine, session_factory, repository = await make_catalog_repository()
    try:
        sport_ids = {
            name: uuid4()
            for name in (*APPROVED_SPORT_NAMES, "Football", "Tennis")
        }
        async with session_factory.begin() as session:
            session.add_all(
                Sport(
                    sport_id=sport_ids[name],
                    name=name,
                    is_active=True,
                )
                for name in sport_ids
            )

        sports = await repository.list_active_sports()

        assert {sport.name for sport in sports} == set(APPROVED_SPORT_NAMES)
        assert len(sports) == len(APPROVED_SPORT_NAMES)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_catalog_repository_lists_active_equipment_without_availability_counts():
    engine, session_factory, repository = await make_catalog_repository()
    try:
        active_id, inactive_id = uuid4(), uuid4()
        async with session_factory.begin() as session:
            session.add_all(
                [
                    EquipmentItem(
                        equipment_id=active_id,
                        name="Racket",
                        total_quantity=8,
                        is_active=True,
                    ),
                    EquipmentItem(
                        equipment_id=inactive_id,
                        name="Archived balls",
                        total_quantity=10,
                        is_active=False,
                    ),
                ]
            )

        assert await repository.list_active_equipment() == (
            EquipmentCatalogRecord(active_id, "Racket"),
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_catalog_repository_returns_empty_tuples_for_empty_catalogs():
    engine, _, repository = await make_catalog_repository()
    try:
        assert await repository.list_active_sports() == ()
        assert await repository.list_active_equipment() == ()
    finally:
        await engine.dispose()
