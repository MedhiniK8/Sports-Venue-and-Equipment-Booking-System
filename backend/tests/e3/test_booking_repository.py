from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.e3_persistence.errors import (
    BookingAlreadyCancelledError,
    BookingCancellationExpiredError,
    BookingConflictError,
    BookingNotFoundError,
    BookingStartTimeExpiredError,
    EquipmentUnavailableError,
)
from app.e3_persistence.inputs import (
    BookingEquipmentLine,
    CreateBookingInput,
)
from app.e3_persistence.models import (
    Base,
    Booking,
    Court,
    EquipmentAllocation,
    EquipmentItem,
    SlotClaim,
    Sport,
    User,
)
from app.e3_persistence import repository as repository_module
from app.e3_persistence.repository import SqlAlchemyPersistenceRepository


async def make_sqlite_session_factory():
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
async def test_repository_rejects_booking_starting_at_local_now(monkeypatch):
    engine, session_factory = await make_sqlite_session_factory()
    try:
        local_now = datetime(2026, 11, 25, 14, 30)
        monkeypatch.setattr(
            repository_module,
            "current_venue_local_naive",
            lambda: local_now,
        )
        command = CreateBookingInput(
            booking_id=uuid4(),
            user_id=uuid4(),
            court_id=uuid4(),
            booking_date=local_now.date(),
            start_time=local_now.time(),
            end_time=time(14, 31),
        )
        repository = SqlAlchemyPersistenceRepository(session_factory)

        with pytest.raises(BookingStartTimeExpiredError):
            await repository.create_booking(command)

        async with session_factory() as session:
            assert await session.scalar(
                select(func.count()).select_from(Booking)
            ) == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_booking_repository_claims_minutes_and_enforces_equipment_capacity():
    engine, session_factory = await make_sqlite_session_factory()
    try:
        user_id, sport_id, court_one, court_two, court_three, equipment_id = [
            uuid4() for _ in range(6)
        ]
        async with session_factory.begin() as session:
            session.add_all(
                [
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
                    Sport(sport_id=sport_id, name="Tennis"),
                    Court(court_id=court_one, sport_id=sport_id, name="Court 1"),
                    Court(court_id=court_two, sport_id=sport_id, name="Court 2"),
                    Court(court_id=court_three, sport_id=sport_id, name="Court 3"),
                    EquipmentItem(
                        equipment_id=equipment_id,
                        name="Racket",
                        total_quantity=3,
                    ),
                ]
            )

        repository = SqlAlchemyPersistenceRepository(session_factory)
        booking_date = date.today() + timedelta(days=1)
        first = CreateBookingInput(
            booking_id=uuid4(),
            user_id=user_id,
            court_id=court_one,
            booking_date=booking_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
            items=(BookingEquipmentLine(equipment_id, 2),),
        )
        first_record = await repository.create_booking(first)
        assert first_record.status == "BOOKED"

        overlapping_equipment = CreateBookingInput(
            booking_id=uuid4(),
            user_id=user_id,
            court_id=court_two,
            booking_date=booking_date,
            start_time=time(9, 30),
            end_time=time(10, 30),
            items=(BookingEquipmentLine(equipment_id, 2),),
        )
        with pytest.raises(EquipmentUnavailableError):
            await repository.create_booking(overlapping_equipment)

        adjacent = CreateBookingInput(
            booking_id=uuid4(),
            user_id=user_id,
            court_id=court_two,
            booking_date=booking_date,
            start_time=time(10, 0),
            end_time=time(11, 0),
            items=(BookingEquipmentLine(equipment_id, 2),),
        )
        await repository.create_booking(adjacent)

        duplicate_court_minutes = CreateBookingInput(
            booking_id=uuid4(),
            user_id=user_id,
            court_id=court_one,
            booking_date=booking_date,
            start_time=time(9, 30),
            end_time=time(9, 45),
        )
        with pytest.raises(BookingConflictError):
            await repository.create_booking(duplicate_court_minutes)

        adjacent_reservations = CreateBookingInput(
            booking_id=uuid4(),
            user_id=user_id,
            court_id=court_three,
            booking_date=booking_date,
            start_time=time(9, 0),
            end_time=time(11, 0),
            items=(BookingEquipmentLine(equipment_id, 1),),
        )
        await repository.create_booking(adjacent_reservations)
        snapshot = await repository.load_allocation_snapshot(booking_date)

        async with session_factory() as session:
            booking_count = await session.scalar(
                select(func.count()).select_from(Booking)
            )
            claim_count = await session.scalar(
                select(func.count()).select_from(SlotClaim)
            )
            allocation_count = await session.scalar(
                select(func.count()).select_from(EquipmentAllocation)
            )

        assert booking_count == 3
        assert claim_count == 240
        assert allocation_count == 3
        assert set(snapshot.active_court_ids) == {
            court_one,
            court_two,
            court_three,
        }
        assert len(snapshot.bookings) == 3
        assert len(snapshot.equipment_reservations) == 3
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    ("status", "cancelled_at", "accepted"),
    [
        ("BOOKED", None, True),
        ("CANCELLED", datetime(2026, 1, 1, 8, 0), True),
        ("booked", None, False),
        ("cancelled", datetime(2026, 1, 1, 8, 0), False),
        ("PENDING", None, False),
    ],
)
@pytest.mark.asyncio
async def test_booking_status_constraint_accepts_only_exact_status_values(
    status,
    cancelled_at,
    accepted,
):
    engine, session_factory = await make_sqlite_session_factory()
    try:
        user_id, sport_id, court_id = [uuid4() for _ in range(3)]
        async with session_factory.begin() as session:
            session.add_all(
                [
                    User(
                        user_id=user_id,
                        usn="1AB23CS004",
                        password_hash="test-hash",
                        college_email="student4@example.edu",
                        phone_number="9876543213",
                        year_of_admission=2023,
                        gender="unspecified",
                        branch="Computer Science",
                    ),
                    Sport(sport_id=sport_id, name="Volleyball"),
                    Court(court_id=court_id, sport_id=sport_id, name="Court 1"),
                ]
            )

        booking = Booking(
            booking_id=uuid4(),
            user_id=user_id,
            court_id=court_id,
            booking_date=date.today() + timedelta(days=1),
            start_time=time(9, 0),
            end_time=time(10, 0),
            status=status,
            cancelled_at=cancelled_at,
        )
        try:
            async with session_factory.begin() as session:
                session.add(booking)
                await session.flush()
        except IntegrityError:
            if accepted:
                raise
        else:
            assert accepted
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cancellation_releases_slot_claims_and_retains_equipment_history():
    engine, session_factory = await make_sqlite_session_factory()
    try:
        user_id, sport_id, court_id, equipment_id = [uuid4() for _ in range(4)]
        async with session_factory.begin() as session:
            session.add_all(
                [
                    User(
                        user_id=user_id,
                        usn="1AB23CS002",
                        password_hash="test-hash",
                        college_email="student2@example.edu",
                        phone_number="9876543211",
                        year_of_admission=2023,
                        gender="unspecified",
                        branch="Computer Science",
                    ),
                    Sport(sport_id=sport_id, name="Badminton"),
                    Court(court_id=court_id, sport_id=sport_id, name="Court 1"),
                    EquipmentItem(
                        equipment_id=equipment_id,
                        name="Shuttlecock",
                        total_quantity=5,
                    ),
                ]
            )

        repository = SqlAlchemyPersistenceRepository(session_factory)
        booking_date = date.today() + timedelta(days=1)
        command = CreateBookingInput(
            booking_id=uuid4(),
            user_id=user_id,
            court_id=court_id,
            booking_date=booking_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
            items=(BookingEquipmentLine(equipment_id, 2),),
        )
        await repository.create_booking(command)

        assert await repository.get_booking_for_student(
            command.booking_id,
            uuid4(),
        ) is None
        with pytest.raises(BookingNotFoundError):
            await repository.cancel_booking(
                command.booking_id,
                uuid4(),
                datetime.combine(booking_date, time(8, 0)),
            )
        cancelled = await repository.cancel_booking(
            command.booking_id,
            user_id,
            datetime.combine(booking_date, time(8, 0)),
        )
        listed = await repository.list_student_bookings(user_id)
        snapshot = await repository.load_allocation_snapshot(booking_date)

        assert cancelled.status == "CANCELLED"
        assert len(cancelled.items) == 1
        assert len(listed) == 1
        assert listed[0].status == "CANCELLED"
        assert not snapshot.bookings
        assert not snapshot.equipment_reservations
        async with session_factory() as session:
            assert await session.scalar(
                select(func.count()).select_from(SlotClaim)
            ) == 0
            assert await session.scalar(
                select(func.count()).select_from(EquipmentAllocation)
            ) == 1

        with pytest.raises(BookingAlreadyCancelledError):
            await repository.cancel_booking(
                command.booking_id,
                user_id,
                datetime.combine(booking_date, time(8, 0)),
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cancellation_after_booking_start_is_rejected_without_state_change():
    engine, session_factory = await make_sqlite_session_factory()
    try:
        user_id, sport_id, court_id = [uuid4() for _ in range(3)]
        async with session_factory.begin() as session:
            session.add_all(
                [
                    User(
                        user_id=user_id,
                        usn="1AB23CS003",
                        password_hash="test-hash",
                        college_email="student3@example.edu",
                        phone_number="9876543212",
                        year_of_admission=2023,
                        gender="unspecified",
                        branch="Computer Science",
                    ),
                    Sport(sport_id=sport_id, name="Football"),
                    Court(court_id=court_id, sport_id=sport_id, name="Court 1"),
                ]
            )

        repository = SqlAlchemyPersistenceRepository(session_factory)
        booking_date = date.today() + timedelta(days=1)
        command = CreateBookingInput(
            booking_id=uuid4(),
            user_id=user_id,
            court_id=court_id,
            booking_date=booking_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )
        await repository.create_booking(command)

        with pytest.raises(BookingCancellationExpiredError):
            await repository.cancel_booking(
                command.booking_id,
                user_id,
                datetime.combine(booking_date, time(9, 0)),
            )

        record = await repository.get_booking_for_student(
            command.booking_id,
            user_id,
        )
        assert record is not None
        assert record.status == "BOOKED"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_default_cancellation_clock_uses_asia_kolkata(monkeypatch):
    engine, session_factory = await make_sqlite_session_factory()
    try:
        user_id, sport_id, court_id = [uuid4() for _ in range(3)]
        async with session_factory.begin() as session:
            session.add_all(
                [
                    User(
                        user_id=user_id,
                        usn="1AB23CS005",
                        password_hash="test-hash",
                        college_email="student5@example.edu",
                        phone_number="9876543214",
                        year_of_admission=2023,
                        gender="unspecified",
                        branch="Computer Science",
                    ),
                    Sport(sport_id=sport_id, name="Squash"),
                    Court(court_id=court_id, sport_id=sport_id, name="Court 1"),
                ]
            )

        booking_date = date.today() + timedelta(days=1)
        command = CreateBookingInput(
            booking_id=uuid4(),
            user_id=user_id,
            court_id=court_id,
            booking_date=booking_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )
        repository = SqlAlchemyPersistenceRepository(session_factory)
        await repository.create_booking(command)

        real_datetime = datetime
        clock_calls = []

        def fixed_venue_now():
            clock_calls.append(True)
            return real_datetime(
                booking_date.year,
                booking_date.month,
                booking_date.day,
                8,
                0,
            )

        monkeypatch.setattr(
            repository_module,
            "current_venue_local_naive",
            fixed_venue_now,
        )

        cancelled = await repository.cancel_booking(
            command.booking_id,
            user_id,
        )
        async with session_factory() as session:
            cancelled_at = await session.scalar(
                select(Booking.cancelled_at).where(
                    Booking.booking_id == command.booking_id
                )
            )

        assert clock_calls == [True]
        assert cancelled.status == "CANCELLED"
        assert cancelled_at == real_datetime.combine(
            booking_date,
            time(8, 0),
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_aware_cancellation_time_is_normalized_to_venue_local_time():
    engine, session_factory = await make_sqlite_session_factory()
    try:
        user_id, sport_id, court_id = [uuid4() for _ in range(3)]
        async with session_factory.begin() as session:
            session.add_all(
                [
                    User(
                        user_id=user_id,
                        usn="1AB23CS009",
                        password_hash="test-hash",
                        college_email="student9@example.edu",
                        phone_number="9876543218",
                        year_of_admission=2023,
                        gender="unspecified",
                        branch="Computer Science",
                    ),
                    Sport(sport_id=sport_id, name="Squash"),
                    Court(court_id=court_id, sport_id=sport_id, name="Court 1"),
                ]
            )

        booking_date = date.today() + timedelta(days=1)
        command = CreateBookingInput(
            booking_id=uuid4(),
            user_id=user_id,
            court_id=court_id,
            booking_date=booking_date,
            start_time=time(15, 0),
            end_time=time(16, 0),
        )
        repository = SqlAlchemyPersistenceRepository(session_factory)
        await repository.create_booking(command)

        cancelled = await repository.cancel_booking(
            command.booking_id,
            user_id,
            datetime.combine(booking_date, time(9, 29)).replace(
                tzinfo=timezone.utc
            ),
        )
        async with session_factory() as session:
            cancelled_at = await session.scalar(
                select(Booking.cancelled_at).where(
                    Booking.booking_id == command.booking_id
                )
            )

        assert cancelled.status == "CANCELLED"
        assert cancelled_at == datetime.combine(booking_date, time(14, 59))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cancellation_rolls_back_status_and_claims_when_claim_release_fails():
    engine, session_factory = await make_sqlite_session_factory()
    try:
        user_id, sport_id, court_id, equipment_id = [uuid4() for _ in range(4)]
        async with session_factory.begin() as session:
            session.add_all(
                [
                    User(
                        user_id=user_id,
                        usn="1AB23CS006",
                        password_hash="test-hash",
                        college_email="student6@example.edu",
                        phone_number="9876543215",
                        year_of_admission=2023,
                        gender="unspecified",
                        branch="Computer Science",
                    ),
                    Sport(sport_id=sport_id, name="Badminton"),
                    Court(court_id=court_id, sport_id=sport_id, name="Court 1"),
                    EquipmentItem(
                        equipment_id=equipment_id,
                        name="Racket",
                        total_quantity=2,
                    ),
                ]
            )

        repository = SqlAlchemyPersistenceRepository(session_factory)
        booking_date = date.today() + timedelta(days=1)
        command = CreateBookingInput(
            booking_id=uuid4(),
            user_id=user_id,
            court_id=court_id,
            booking_date=booking_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
            items=(BookingEquipmentLine(equipment_id, 2),),
        )
        await repository.create_booking(command)

        def fail_claim_delete(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("DELETE FROM SLOT_CLAIM"):
                raise RuntimeError("simulated slot-claim release failure")

        event.listen(
            engine.sync_engine,
            "before_cursor_execute",
            fail_claim_delete,
        )
        try:
            with pytest.raises(RuntimeError, match="slot-claim release failure"):
                await repository.cancel_booking(
                    command.booking_id,
                    user_id,
                    datetime.combine(booking_date, time(8, 0)),
                )
        finally:
            event.remove(
                engine.sync_engine,
                "before_cursor_execute",
                fail_claim_delete,
            )

        record = await repository.get_booking_for_student(
            command.booking_id,
            user_id,
        )
        async with session_factory() as session:
            claim_count = await session.scalar(
                select(func.count()).select_from(SlotClaim)
            )
            allocation_count = await session.scalar(
                select(func.count()).select_from(EquipmentAllocation)
            )
            cancelled_at = await session.scalar(
                select(Booking.cancelled_at).where(
                    Booking.booking_id == command.booking_id
                )
            )

        assert record is not None
        assert record.status == "BOOKED"
        assert cancelled_at is None
        assert claim_count == 60
        assert allocation_count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_another_student_can_rebook_cancelled_court_interval_and_equipment():
    engine, session_factory = await make_sqlite_session_factory()
    try:
        first_user, second_user, sport_id, court_id, equipment_id = [
            uuid4() for _ in range(5)
        ]
        async with session_factory.begin() as session:
            session.add_all(
                [
                    User(
                        user_id=first_user,
                        usn="1AB23CS007",
                        password_hash="test-hash",
                        college_email="student7@example.edu",
                        phone_number="9876543216",
                        year_of_admission=2023,
                        gender="unspecified",
                        branch="Computer Science",
                    ),
                    User(
                        user_id=second_user,
                        usn="1AB23CS008",
                        password_hash="test-hash",
                        college_email="student8@example.edu",
                        phone_number="9876543217",
                        year_of_admission=2023,
                        gender="unspecified",
                        branch="Computer Science",
                    ),
                    Sport(sport_id=sport_id, name="Badminton"),
                    Court(court_id=court_id, sport_id=sport_id, name="Court 1"),
                    EquipmentItem(
                        equipment_id=equipment_id,
                        name="Shuttlecock",
                        total_quantity=2,
                    ),
                ]
            )

        repository = SqlAlchemyPersistenceRepository(session_factory)
        booking_date = date.today() + timedelta(days=1)
        first_booking = CreateBookingInput(
            booking_id=uuid4(),
            user_id=first_user,
            court_id=court_id,
            booking_date=booking_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
            items=(BookingEquipmentLine(equipment_id, 2),),
        )
        await repository.create_booking(first_booking)
        await repository.cancel_booking(
            first_booking.booking_id,
            first_user,
            datetime.combine(booking_date, time(8, 0)),
        )

        second_booking = CreateBookingInput(
            booking_id=uuid4(),
            user_id=second_user,
            court_id=court_id,
            booking_date=booking_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
            items=(BookingEquipmentLine(equipment_id, 2),),
        )
        result = await repository.create_booking(second_booking)
        history = await repository.list_student_bookings(first_user)
        snapshot = await repository.load_allocation_snapshot(booking_date)

        assert result.status == "BOOKED"
        assert history[0].status == "CANCELLED"
        assert len(history[0].items) == 1
        assert [booking.booking_id for booking in snapshot.bookings] == [
            second_booking.booking_id
        ]
        assert [item.booking_id for item in snapshot.equipment_reservations] == [
            second_booking.booking_id
        ]
        async with session_factory() as session:
            assert await session.scalar(
                select(func.count()).select_from(SlotClaim)
            ) == 60
            assert await session.scalar(
                select(func.count()).select_from(EquipmentAllocation)
            ) == 2
    finally:
        await engine.dispose()
