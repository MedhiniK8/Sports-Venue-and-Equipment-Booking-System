from datetime import date, datetime, time, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..venue_time import current_venue_local_naive, normalize_venue_local_naive
from .catalog import APPROVED_SPORT_NAMES
from .errors import (
    BookingAlreadyCancelledError,
    BookingCancellationExpiredError,
    BookingConflictError,
    BookingNotFoundError,
    BookingResourceUnavailableError,
    BookingStartTimeExpiredError,
    DuplicateStudentError,
    EquipmentUnavailableError,
)
from .inputs import (
    AllocationSnapshot,
    BlockOutSnapshotRecord,
    BookingEquipmentLine,
    BookingRecord,
    BookingSnapshotRecord,
    CreateBookingInput,
    CreateStudentInput,
    CourtCatalogRecord,
    EquipmentCatalogRecord,
    EquipmentInventorySnapshotRecord,
    EquipmentReservationSnapshotRecord,
    SportCatalogRecord,
    StudentAccountRecord,
)
from .models import (
    BlockOut,
    Booking,
    Court,
    EquipmentAllocation,
    EquipmentItem,
    SlotClaim,
    Sport,
    User,
    RevokedToken,
)
from .session import get_session_factory


class PersistenceRepository(Protocol):
    async def create_student(
        self, student: CreateStudentInput
    ) -> StudentAccountRecord: ...

    async def get_student_by_usn(
        self, usn: str
    ) -> StudentAccountRecord | None: ...

    async def get_student_by_id(
        self, user_id: UUID
    ) -> StudentAccountRecord | None: ...

    async def get_student_by_identifier(
        self, identifier: str
    ) -> StudentAccountRecord | None: ...

    async def update_student(
        self,
        user_id: UUID,
        *,
        student_name: str,
    ) -> StudentAccountRecord: ...

    async def update_student_password(
        self,
        user_id: UUID,
        password_hash: str,
    ) -> bool: ...

    async def revoke_token(self, jti: str, expires_at: datetime) -> None: ...

    async def is_token_revoked(self, jti: str) -> bool: ...

    async def list_block_outs(self) -> tuple: ...

    async def create_block_out(
        self,
        *,
        block_out_id: UUID,
        court_id: UUID,
        starts_at: datetime,
        ends_at: datetime,
        reason: str | None,
        created_by: UUID,
    ) -> BlockOut: ...

    async def update_block_out(
        self,
        block_out_id: UUID,
        *,
        starts_at: datetime,
        ends_at: datetime,
        reason: str | None,
        is_active: bool,
    ) -> BlockOut | None: ...

    async def list_active_sports(self) -> tuple[SportCatalogRecord, ...]: ...

    async def list_active_courts_for_sport(
        self, sport_id: UUID
    ) -> tuple[CourtCatalogRecord, ...] | None: ...

    async def list_active_equipment(self) -> tuple[EquipmentCatalogRecord, ...]: ...

    async def create_booking(self, booking: CreateBookingInput) -> BookingRecord: ...

    async def get_booking_for_student(
        self, booking_id: UUID, user_id: UUID
    ) -> BookingRecord | None: ...

    async def list_student_bookings(self, user_id: UUID) -> list[BookingRecord]: ...

    async def cancel_booking(
        self, booking_id: UUID, user_id: UUID, now: datetime | None = None
    ) -> BookingRecord: ...

    async def load_allocation_snapshot(
        self, reference_date: date
    ) -> AllocationSnapshot: ...


class SqlAlchemyPersistenceRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._session_factory = session_factory

    def _factory(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory or get_session_factory()

    async def create_student(
        self, student: CreateStudentInput
    ) -> StudentAccountRecord:
        try:
            async with self._factory()() as session:
                async with session.begin():
                    existing = await session.execute(
                        select(User.usn, User.college_email).where(
                            or_(
                                User.usn == student.usn,
                                User.college_email == student.college_email,
                            )
                        )
                    )
                    duplicate = existing.first()
                    if duplicate:
                        if duplicate.usn == student.usn:
                            raise DuplicateStudentError("USN")
                        raise DuplicateStudentError("college email")

                    user = User(
                        usn=student.usn,
                        student_name=student.student_name,
                        role=student.role,
                        password_hash=student.password_hash,
                        college_email=student.college_email,
                        phone_number=student.phone_number,
                        year_of_admission=(
                            student.year_of_admission
                            if student.year_of_admission is not None
                            else None
                        ),
                        gender=student.gender,
                        branch=student.branch,
                    )
                    session.add(user)
                    await session.flush()
                    record = self._to_student_record(user)
            return record
        except IntegrityError as error:
            if self._is_duplicate_key(error):
                raise DuplicateStudentError() from error
            raise

    async def get_student_by_usn(self, usn: str) -> StudentAccountRecord | None:
        async with self._factory()() as session:
            user = await session.scalar(select(User).where(User.usn == usn))
            return self._to_student_record(user) if user is not None else None

    async def get_student_by_id(self, user_id: UUID) -> StudentAccountRecord | None:
        async with self._factory()() as session:
            user = await session.get(User, user_id)
            return self._to_student_record(user) if user is not None else None

    async def get_student_by_identifier(
        self, identifier: str
    ) -> StudentAccountRecord | None:
        normalized = identifier.strip().lower()
        async with self._factory()() as session:
            user = await session.scalar(
                select(User).where(
                    or_(User.usn == identifier.strip(), User.college_email == normalized)
                )
            )
            return self._to_student_record(user) if user is not None else None

    async def update_student(
        self,
        user_id: UUID,
        *,
        student_name: str,
    ) -> StudentAccountRecord:
        try:
            async with self._factory()() as session:
                async with session.begin():
                    user = await session.get(User, user_id, with_for_update=True)
                    if user is None:
                        raise BookingResourceUnavailableError(
                            "Student account is unavailable"
                        )
                    user.student_name = student_name
                    await session.flush()
                    record = self._to_student_record(user)
            return record
        except IntegrityError as error:
            if self._is_duplicate_key(error):
                raise DuplicateStudentError("college email") from error
            raise

    async def update_student_password(
        self,
        user_id: UUID,
        password_hash: str,
    ) -> bool:
        async with self._factory()() as session:
            async with session.begin():
                user = await session.get(User, user_id, with_for_update=True)
                if user is None:
                    return False
                user.password_hash = password_hash
                await session.flush()
                return True

    async def revoke_token(self, jti: str, expires_at: datetime) -> None:
        async with self._factory()() as session:
            async with session.begin():
                session.merge(RevokedToken(jti=jti, expires_at=expires_at))
                await session.flush()

    async def is_token_revoked(self, jti: str) -> bool:
        async with self._factory()() as session:
            revoked = await session.get(RevokedToken, jti)
            return revoked is not None

    async def list_block_outs(self) -> tuple:
        async with self._factory()() as session:
            rows = (
                await session.scalars(
                    select(BlockOut).order_by(
                        BlockOut.starts_at.desc(),
                        BlockOut.block_out_id,
                    )
                )
            ).all()
            return tuple(rows)

    async def create_block_out(
        self,
        *,
        block_out_id: UUID,
        court_id: UUID,
        starts_at: datetime,
        ends_at: datetime,
        reason: str | None,
        created_by: UUID,
    ) -> BlockOut:
        async with self._factory()() as session:
            async with session.begin():
                court = await session.scalar(
                    select(Court).where(
                        Court.court_id == court_id,
                        Court.is_active.is_(True),
                    )
                )
                if court is None:
                    raise BookingResourceUnavailableError(
                        "Court is missing or inactive"
                    )
                block = BlockOut(
                    block_out_id=block_out_id,
                    court_id=court_id,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    reason=reason,
                    created_by=created_by,
                    is_active=True,
                )
                session.add(block)
                await session.flush()
                start_minute = starts_at.hour * 60 + starts_at.minute
                end_minute = ends_at.hour * 60 + ends_at.minute
                if starts_at.date() == ends_at.date():
                    session.add_all(
                        SlotClaim(
                            court_id=court_id,
                            slot_date=starts_at.date(),
                            minute_index=minute,
                            block_out_id=block_out_id,
                        )
                        for minute in range(start_minute, end_minute)
                    )
                await session.flush()
                return block

    async def update_block_out(
        self,
        block_out_id: UUID,
        *,
        starts_at: datetime,
        ends_at: datetime,
        reason: str | None,
        is_active: bool,
    ) -> BlockOut | None:
        async with self._factory()() as session:
            async with session.begin():
                block = await session.get(BlockOut, block_out_id, with_for_update=True)
                if block is None:
                    return None
                await session.execute(
                    delete(SlotClaim).where(
                        SlotClaim.block_out_id == block_out_id
                    )
                )
                block.starts_at = starts_at
                block.ends_at = ends_at
                block.reason = reason
                block.is_active = is_active
                if is_active:
                    if starts_at.date() == ends_at.date():
                        session.add_all(
                            SlotClaim(
                                court_id=block.court_id,
                                slot_date=starts_at.date(),
                                minute_index=minute,
                                block_out_id=block_out_id,
                            )
                            for minute in range(
                                starts_at.hour * 60 + starts_at.minute,
                                ends_at.hour * 60 + ends_at.minute,
                            )
                        )
                await session.flush()
                return block

    async def list_active_sports(self) -> tuple[SportCatalogRecord, ...]:
        async with self._factory()() as session:
            async with session.begin():
                sports = (
                    await session.scalars(
                        select(Sport)
                        .where(
                            Sport.is_active.is_(True),
                            Sport.name.in_(APPROVED_SPORT_NAMES),
                        )
                        .order_by(Sport.name, Sport.sport_id)
                    )
                ).all()
                return tuple(
                    SportCatalogRecord(sport.sport_id, sport.name)
                    for sport in sports
                )

    async def list_active_courts_for_sport(
        self, sport_id: UUID
    ) -> tuple[CourtCatalogRecord, ...] | None:
        async with self._factory()() as session:
            async with session.begin():
                active_sport_id = await session.scalar(
                    select(Sport.sport_id).where(
                        Sport.sport_id == sport_id,
                        Sport.is_active.is_(True),
                    )
                )
                if active_sport_id is None:
                    return None

                courts = (
                    await session.scalars(
                        select(Court)
                        .where(
                            Court.sport_id == sport_id,
                            Court.is_active.is_(True),
                        )
                        .order_by(Court.name, Court.court_id)
                    )
                ).all()
                return tuple(
                    CourtCatalogRecord(court.court_id, court.name)
                    for court in courts
                )

    async def list_active_equipment(self) -> tuple[EquipmentCatalogRecord, ...]:
        async with self._factory()() as session:
            async with session.begin():
                equipment_items = (
                    await session.scalars(
                        select(EquipmentItem)
                        .where(EquipmentItem.is_active.is_(True))
                        .order_by(EquipmentItem.name, EquipmentItem.equipment_id)
                    )
                ).all()
                return tuple(
                    EquipmentCatalogRecord(item.equipment_id, item.name)
                    for item in equipment_items
                )

    async def create_booking(self, command: CreateBookingInput) -> BookingRecord:
        self._validate_booking_input(command)
        equipment_ids = [item.equipment_id for item in command.items]
        if len(set(equipment_ids)) != len(equipment_ids):
            raise ValueError("A booking cannot repeat an equipment ID")

        try:
            async with self._factory()() as session:
                async with session.begin():
                    user_exists = await session.scalar(
                        select(User.user_id).where(User.user_id == command.user_id)
                    )
                    court = await session.scalar(
                        select(Court).where(Court.court_id == command.court_id)
                    )
                    if user_exists is None or court is None or not court.is_active:
                        raise BookingResourceUnavailableError(
                            "Student or court is missing or inactive"
                        )

                    locked_equipment = await self._lock_equipment_rows(
                        session,
                        equipment_ids,
                    )
                    if len(locked_equipment) != len(equipment_ids):
                        raise BookingResourceUnavailableError(
                            "One or more equipment items do not exist"
                        )

                    requested_by_id = {
                        item.equipment_id: item.quantity for item in command.items
                    }
                    for equipment in locked_equipment:
                        if not equipment.is_active:
                            raise BookingResourceUnavailableError(
                                "One or more equipment items are inactive"
                            )
                        reserved = await self._max_reserved_quantity(
                            session,
                            equipment.equipment_id,
                            command.booking_date,
                            command.start_time,
                            command.end_time,
                        )
                        available = max(0, equipment.total_quantity - reserved)
                        requested = requested_by_id[equipment.equipment_id]
                        if requested > available:
                            raise EquipmentUnavailableError(
                                equipment.equipment_id,
                                requested,
                                available,
                            )

                    booking = Booking(
                        booking_id=command.booking_id,
                        user_id=command.user_id,
                        court_id=command.court_id,
                        booking_date=command.booking_date,
                        start_time=command.start_time,
                        end_time=command.end_time,
                        status="BOOKED",
                    )
                    session.add(booking)
                    await session.flush()

                    start_minute = (
                        command.start_time.hour * 60 + command.start_time.minute
                    )
                    end_minute = command.end_time.hour * 60 + command.end_time.minute
                    session.add_all(
                        SlotClaim(
                            court_id=command.court_id,
                            slot_date=command.booking_date,
                            minute_index=minute_index,
                            booking_id=command.booking_id,
                        )
                        for minute_index in range(start_minute, end_minute)
                    )
                    session.add_all(
                        EquipmentAllocation(
                            booking_id=command.booking_id,
                            equipment_id=item.equipment_id,
                            quantity=item.quantity,
                        )
                        for item in command.items
                    )
                    await session.flush()

            return BookingRecord(
                booking_id=command.booking_id,
                user_id=command.user_id,
                court_id=command.court_id,
                booking_date=command.booking_date,
                start_time=command.start_time,
                end_time=command.end_time,
                status="BOOKED",
                items=command.items,
            )
        except IntegrityError as error:
            if self._is_duplicate_key(error):
                raise BookingConflictError(
                    "One or more requested court minutes are already claimed"
                ) from error
            raise

    async def get_booking_for_student(
        self,
        booking_id: UUID,
        user_id: UUID,
    ) -> BookingRecord | None:
        async with self._factory()() as session:
            async with session.begin():
                booking = await session.scalar(
                    select(Booking).where(
                        Booking.booking_id == booking_id,
                        Booking.user_id == user_id,
                    )
                )
                if booking is None:
                    return None
                items = await self._booking_equipment_lines(
                    session,
                    (booking.booking_id,),
                )
                return self._to_booking_record(
                    booking,
                    items.get(booking.booking_id, ()),
                )

    async def list_student_bookings(self, user_id: UUID) -> list[BookingRecord]:
        async with self._factory()() as session:
            async with session.begin():
                bookings = (
                    await session.scalars(
                        select(Booking)
                        .where(Booking.user_id == user_id)
                        .order_by(
                            Booking.booking_date.desc(),
                            Booking.start_time.desc(),
                        )
                    )
                ).all()
                if not bookings:
                    return []
                items_by_booking = await self._booking_equipment_lines(
                    session,
                    tuple(booking.booking_id for booking in bookings),
                )
                return [
                    self._to_booking_record(
                        booking,
                        items_by_booking.get(booking.booking_id, ()),
                    )
                    for booking in bookings
                ]

    async def cancel_booking(
        self,
        booking_id: UUID,
        user_id: UUID,
        now: datetime | None = None,
    ) -> BookingRecord:
        async with self._factory()() as session:
            async with session.begin():
                booking = await session.scalar(
                    select(Booking)
                    .where(
                        Booking.booking_id == booking_id,
                        Booking.user_id == user_id,
                    )
                    .with_for_update()
                )
                if booking is None:
                    raise BookingNotFoundError
                if booking.status == "CANCELLED":
                    raise BookingAlreadyCancelledError
                cancellation_time = (
                    current_venue_local_naive()
                    if now is None
                    else normalize_venue_local_naive(now)
                )
                starts_at = datetime.combine(
                    booking.booking_date,
                    booking.start_time,
                )
                if starts_at <= cancellation_time:
                    raise BookingCancellationExpiredError

                booking.status = "CANCELLED"
                booking.cancelled_at = cancellation_time
                await session.execute(
                    delete(SlotClaim).where(SlotClaim.booking_id == booking_id)
                )
                await session.flush()
                items = await self._booking_equipment_lines(
                    session,
                    (booking_id,),
                )
                return self._to_booking_record(
                    booking,
                    items.get(booking_id, ()),
                )

    async def load_allocation_snapshot(
        self,
        reference_date: date,
    ) -> AllocationSnapshot:
        if isinstance(reference_date, datetime):
            raise ValueError("reference_date must be a date, not a datetime")
        window_end_date = reference_date + timedelta(days=7)
        window_start = datetime.combine(reference_date, time.min)
        window_end = datetime.combine(window_end_date, time.min)

        async with self._factory()() as session:
            async with session.begin():
                active_court_ids = tuple(
                    await session.scalars(
                        select(Court.court_id)
                        .where(Court.is_active.is_(True))
                        .order_by(Court.court_id)
                    )
                )
                booking_rows = (
                    await session.scalars(
                        select(Booking).where(
                            Booking.status == "BOOKED",
                            Booking.booking_date >= reference_date,
                            Booking.booking_date < window_end_date,
                        )
                    )
                ).all()
                block_rows = (
                    await session.scalars(
                        select(BlockOut).where(
                            BlockOut.is_active.is_(True),
                            BlockOut.starts_at < window_end,
                            BlockOut.ends_at > window_start,
                        )
                    )
                ).all()
                inventory_rows = (
                    await session.scalars(select(EquipmentItem))
                ).all()
                reservation_rows = (
                    await session.execute(
                        select(
                            EquipmentAllocation.equipment_id,
                            Booking.booking_id,
                            Booking.booking_date,
                            Booking.start_time,
                            Booking.end_time,
                            EquipmentAllocation.quantity,
                        )
                        .join(
                            Booking,
                            Booking.booking_id == EquipmentAllocation.booking_id,
                        )
                        .where(
                            Booking.status == "BOOKED",
                            Booking.booking_date >= reference_date,
                            Booking.booking_date < window_end_date,
                        )
                    )
                ).all()

                return AllocationSnapshot(
                    active_court_ids=active_court_ids,
                    bookings=tuple(
                        BookingSnapshotRecord(
                            booking_id=row.booking_id,
                            court_id=row.court_id,
                            user_id=row.user_id,
                            booking_date=row.booking_date,
                            start_time=row.start_time,
                            end_time=row.end_time,
                        )
                        for row in booking_rows
                    ),
                    blocks=tuple(
                        BlockOutSnapshotRecord(
                            block_out_id=row.block_out_id,
                            court_id=row.court_id,
                            starts_at=row.starts_at,
                            ends_at=row.ends_at,
                        )
                        for row in block_rows
                    ),
                    equipment_inventory=tuple(
                        EquipmentInventorySnapshotRecord(
                            equipment_id=row.equipment_id,
                            total_quantity=row.total_quantity,
                        )
                        for row in inventory_rows
                    ),
                    equipment_reservations=tuple(
                        EquipmentReservationSnapshotRecord(
                            equipment_id=row.equipment_id,
                            booking_id=row.booking_id,
                            booking_date=row.booking_date,
                            start_time=row.start_time,
                            end_time=row.end_time,
                            quantity=row.quantity,
                        )
                        for row in reservation_rows
                    ),
                )

    async def _lock_equipment_rows(
        self,
        session: AsyncSession,
        equipment_ids: list[UUID],
    ) -> list[EquipmentItem]:
        if not equipment_ids:
            return []
        ordered_ids = sorted(equipment_ids, key=lambda equipment_id: equipment_id.hex)
        result = await session.scalars(
            select(EquipmentItem)
            .where(EquipmentItem.equipment_id.in_(ordered_ids))
            .order_by(EquipmentItem.equipment_id)
            .with_for_update()
        )
        return list(result.all())

    async def _max_reserved_quantity(
        self,
        session: AsyncSession,
        equipment_id: UUID,
        booking_date: date,
        requested_start: time,
        requested_end: time,
    ) -> int:
        rows = (
            await session.execute(
                select(
                    Booking.start_time,
                    Booking.end_time,
                    EquipmentAllocation.quantity,
                )
                .join(
                    EquipmentAllocation,
                    EquipmentAllocation.booking_id == Booking.booking_id,
                )
                .where(
                    EquipmentAllocation.equipment_id == equipment_id,
                    Booking.status == "BOOKED",
                    Booking.booking_date == booking_date,
                    Booking.start_time < requested_end,
                    Booking.end_time > requested_start,
                )
                .with_for_update()
            )
        ).all()
        requested_start_dt = datetime.combine(booking_date, requested_start)
        requested_end_dt = datetime.combine(booking_date, requested_end)
        events: list[tuple[datetime, int]] = []
        for existing_start, existing_end, quantity in rows:
            start = max(
                requested_start_dt,
                datetime.combine(booking_date, existing_start),
            )
            end = min(
                requested_end_dt,
                datetime.combine(booking_date, existing_end),
            )
            if start < end:
                events.extend(((start, quantity), (end, -quantity)))

        current = maximum = 0
        for _, change in sorted(events, key=lambda event: (event[0], event[1])):
            current += change
            maximum = max(maximum, current)
        return maximum

    @staticmethod
    async def _booking_equipment_lines(
        session: AsyncSession,
        booking_ids: tuple[UUID, ...],
    ) -> dict[UUID, tuple[BookingEquipmentLine, ...]]:
        if not booking_ids:
            return {}
        rows = (
            await session.execute(
                select(
                    EquipmentAllocation.booking_id,
                    EquipmentAllocation.equipment_id,
                    EquipmentAllocation.quantity,
                )
                .where(EquipmentAllocation.booking_id.in_(booking_ids))
                .order_by(
                    EquipmentAllocation.booking_id,
                    EquipmentAllocation.equipment_id,
                )
            )
        ).all()
        grouped: dict[UUID, list[BookingEquipmentLine]] = {}
        for booking_id, equipment_id, quantity in rows:
            grouped.setdefault(booking_id, []).append(
                BookingEquipmentLine(equipment_id, quantity)
            )
        return {
            booking_id: tuple(items)
            for booking_id, items in grouped.items()
        }

    @staticmethod
    def _validate_booking_input(command: CreateBookingInput) -> None:
        if command.start_time.tzinfo is not None or command.end_time.tzinfo is not None:
            raise ValueError("Booking times must be venue-local and timezone-naive")
        if command.start_time >= command.end_time:
            raise ValueError("A booking must end after it starts on the same day")
        if any(
            value.second != 0 or value.microsecond != 0
            for value in (command.start_time, command.end_time)
        ):
            raise ValueError("Booking times must use minute precision")
        if (
            command.start_time.hour * 60 + command.start_time.minute < 6 * 60
            or command.end_time.hour * 60 + command.end_time.minute > 20 * 60
        ):
            raise ValueError("A booking must be within court hours (06:00-20:00)")
        starts_at = datetime.combine(command.booking_date, command.start_time)
        if starts_at <= current_venue_local_naive():
            raise BookingStartTimeExpiredError
        if any(item.quantity <= 0 for item in command.items):
            raise ValueError("Equipment quantities must be positive")

    @staticmethod
    def _to_student_record(user: User) -> StudentAccountRecord:
        return StudentAccountRecord(
            user_id=user.user_id,
            usn=user.usn,
            password_hash=user.password_hash,
            college_email=user.college_email,
            phone_number=user.phone_number,
            year_of_admission=user.year_of_admission,
            gender=user.gender,
            branch=user.branch,
            student_name=getattr(user, "student_name", ""),
            role=getattr(user, "role", "STUDENT"),
        )

    @staticmethod
    def _to_booking_record(
        booking: Booking,
        items: tuple[BookingEquipmentLine, ...],
    ) -> BookingRecord:
        return BookingRecord(
            booking_id=booking.booking_id,
            user_id=booking.user_id,
            court_id=booking.court_id,
            booking_date=booking.booking_date,
            start_time=booking.start_time,
            end_time=booking.end_time,
            status=booking.status,
            items=items,
        )

    @staticmethod
    def _is_duplicate_key(error: IntegrityError) -> bool:
        original = error.orig
        error_code = original.args[0] if getattr(original, "args", ()) else None
        message = str(original).casefold()
        return (
            error_code == 1062
            or "duplicate entry" in message
            or "unique constraint failed" in message
        )
