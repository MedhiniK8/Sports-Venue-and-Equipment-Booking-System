import importlib.util
from datetime import date, time, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.e3_persistence.catalog import APPROVED_SPORT_NAMES
from app.e3_persistence.models import (
    Base,
    Booking,
    Court,
    EquipmentItem,
    Sport,
    User,
)


SEED_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "seed_catalog.py"
)
SPEC = importlib.util.spec_from_file_location(
    "seed_catalog_script",
    SEED_SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
seed_catalog_script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(seed_catalog_script)


async def make_seed_session_factory():
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
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_seed_catalog_reconciles_approved_sports_idempotently_without_deleting_history(
    monkeypatch,
):
    engine, session_factory = await make_seed_session_factory()
    try:
        football_id, tennis_id, basketball_id = uuid4(), uuid4(), uuid4()
        tennis_court_id, user_id, booking_id = uuid4(), uuid4(), uuid4()
        booking_date = date.today() + timedelta(days=1)
        async with session_factory.begin() as session:
            session.add_all(
                [
                    Sport(
                        sport_id=football_id,
                        name="Football",
                        is_active=True,
                    ),
                    Sport(
                        sport_id=tennis_id,
                        name="Tennis",
                        is_active=True,
                    ),
                    Sport(
                        sport_id=basketball_id,
                        name="Basketball",
                        is_active=False,
                    ),
                    Court(
                        court_id=tennis_court_id,
                        sport_id=tennis_id,
                        name="Tennis Court 1",
                    ),
                    User(
                        user_id=user_id,
                        usn="1AB23CS001",
                        password_hash="test-hash",
                        college_email="student@example.edu",
                        phone_number="9876543210",
                        year_of_admission=2023,
                        gender="unspecified",
                        branch="Computer Science",
                    ),
                    Booking(
                        booking_id=booking_id,
                        user_id=user_id,
                        court_id=tennis_court_id,
                        booking_date=booking_date,
                        start_time=time(9, 0),
                        end_time=time(10, 0),
                        status="BOOKED",
                    ),
                ]
            )

        monkeypatch.setattr(
            seed_catalog_script,
            "get_session_factory",
            lambda: session_factory,
        )

        await seed_catalog_script.seed_catalog()
        async with session_factory() as session:
            sports_after_first_run = (
                await session.scalars(select(Sport).order_by(Sport.name))
            ).all()
            first_sport_ids = {
                sport.name: sport.sport_id for sport in sports_after_first_run
            }
            first_court_ids = {
                court.court_id
                for court in (await session.scalars(select(Court))).all()
            }
            first_equipment_count = len(
                (await session.scalars(select(EquipmentItem))).all()
            )
            historical_booking = await session.get(Booking, booking_id)

        assert {
            sport.name for sport in sports_after_first_run if sport.is_active
        } == set(APPROVED_SPORT_NAMES)
        assert first_sport_ids["Football"] == football_id
        assert first_sport_ids["Tennis"] == tennis_id
        assert first_sport_ids["Basketball"] == basketball_id
        assert not next(
            sport for sport in sports_after_first_run if sport.sport_id == football_id
        ).is_active
        assert not next(
            sport for sport in sports_after_first_run if sport.sport_id == tennis_id
        ).is_active
        assert next(
            sport for sport in sports_after_first_run if sport.sport_id == basketball_id
        ).is_active
        assert "Squash" in first_sport_ids
        assert tennis_court_id in first_court_ids
        assert historical_booking is not None
        assert historical_booking.status == "BOOKED"

        await seed_catalog_script.seed_catalog()
        async with session_factory() as session:
            sports_after_second_run = (
                await session.scalars(select(Sport).order_by(Sport.name))
            ).all()
            second_court_ids = {
                court.court_id
                for court in (await session.scalars(select(Court))).all()
            }
            second_equipment_count = len(
                (await session.scalars(select(EquipmentItem))).all()
            )
            retained_booking = await session.get(Booking, booking_id)

        assert {
            sport.name for sport in sports_after_second_run if sport.is_active
        } == set(APPROVED_SPORT_NAMES)
        assert {
            sport.name: sport.sport_id for sport in sports_after_second_run
        } == first_sport_ids
        assert second_court_ids == first_court_ids
        assert second_equipment_count == first_equipment_count
        assert retained_booking is not None
        assert retained_booking.status == "BOOKED"
    finally:
        await engine.dispose()
