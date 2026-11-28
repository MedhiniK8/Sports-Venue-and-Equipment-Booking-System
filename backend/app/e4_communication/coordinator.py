import asyncio
from datetime import date, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError

from ..contracts.booking import BookingRequest, BookingResponse, LockToken, TimeInterval
from ..e2_allocation import (
    AllocationService,
    CommittedBooking,
    EquipmentAllocationRequest,
    EffectiveCourtBlock,
    EquipmentInventory,
    EquipmentRequestLine,
    EquipmentReservation,
)
from ..e3_persistence.errors import (
    BookingAlreadyCancelledError,
    BookingCancellationExpiredError,
    BookingConflictError,
    BookingNotFoundError,
    BookingResourceUnavailableError,
    BookingStartTimeExpiredError,
    EquipmentUnavailableError,
)
from ..e3_persistence.inputs import (
    AllocationSnapshot,
    BookingEquipmentLine,
    BookingRecord,
    CreateBookingInput,
)
from ..e3_persistence.repository import PersistenceRepository
from .schemas import (
    BookingRequestCancelledResponse,
    EquipmentDecisionRequiredResponse,
    EquipmentShortageResponse,
    StudentBookingRequest,
)


class WaitAwareConcurrency(Protocol):
    async def acquire_with_wait(
        self,
        interval: TimeInterval,
        resource_id: str,
        timeout: float = 3.0,
    ) -> LockToken: ...

    async def release(self, token: LockToken) -> None: ...


class BookingAvailabilityError(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("The requested court or equipment is unavailable")


class AllocationSnapshotError(Exception):
    pass


class BookingCommittedCacheRefreshError(Exception):
    def __init__(self, booking_id: UUID) -> None:
        self.booking_id = booking_id
        super().__init__("The booking committed, but availability refresh failed")


class CourtAvailabilityNotFoundError(Exception):
    """The court is missing or inactive."""


class BookingCoordinator:
    """Coordinate authenticated student bookings across E1, E2, and E3."""

    def __init__(
        self,
        allocation: AllocationService | None = None,
        concurrency: WaitAwareConcurrency | None = None,
        persistence: PersistenceRepository | None = None,
    ) -> None:
        self.allocation = allocation
        self.concurrency = concurrency
        self.persistence = persistence
        self._snapshot_lock = asyncio.Lock()
        self._state_revision = 0
        self._allocation_revision = -1
        self._allocation_window: tuple[date, date] | None = None

    async def coordinate_booking(self, request: BookingRequest) -> BookingResponse:
        raise NotImplementedError(
            "Use coordinate_student_booking with the student booking contract"
        )

    async def get_court_availability(
        self,
        court_id: UUID,
        reference_date: date,
    ):
        if self.persistence is None:
            raise RuntimeError("Persistence repository is not configured")

        snapshot = await self.persistence.load_allocation_snapshot(reference_date)
        if court_id not in snapshot.active_court_ids:
            raise CourtAvailabilityNotFoundError

        allocation = self._build_allocation_service(snapshot, reference_date)
        days = []
        for offset in range(7):
            booking_date = reference_date + timedelta(days=offset)
            intervals = allocation.get_court_availability(court_id, booking_date)
            if intervals is None:
                raise AllocationSnapshotError(
                    "Court availability was not generated for the requested date"
                )
            days.append((booking_date, intervals))
        return court_id, reference_date, days

    async def get_equipment_availability(
        self,
        equipment_id: UUID,
        booking_date: date,
        start_time,
        end_time,
    ):
        if self.persistence is None:
            raise RuntimeError("Persistence repository is not configured")
        snapshot = await self.persistence.load_allocation_snapshot(booking_date)
        allocation = self._build_allocation_service(snapshot, booking_date)
        interval = TimeInterval(
            start=datetime.combine(booking_date, start_time),
            end=datetime.combine(booking_date, end_time),
        )
        result = allocation.get_equipment_availability(
            equipment_id,
            interval,
            requested_quantity=1,
        )
        if not result.valid and not result.errors:
            raise AllocationSnapshotError("Equipment availability could not be calculated")
        if not result.valid and any("Inventory is missing" in error for error in result.errors):
            raise CourtAvailabilityNotFoundError
        return result

    async def coordinate_student_booking(
        self,
        request: StudentBookingRequest,
        user_id: UUID,
    ) -> (
        BookingRecord
        | EquipmentDecisionRequiredResponse
        | BookingRequestCancelledResponse
    ):
        if self.concurrency is None or self.persistence is None:
            raise RuntimeError("Booking coordinator dependencies are not configured")

        interval = TimeInterval(
            start=datetime.combine(request.booking_date, request.start_time),
            end=datetime.combine(request.booking_date, request.end_time),
        )
        allocation = await self._ensure_allocation_snapshot(request.booking_date)
        court_result = allocation.check_court_availability(
            request.court_id,
            request.booking_date,
            interval,
        )
        if not court_result.valid:
            raise BookingAvailabilityError(court_result.errors)

        booking_id = uuid4()
        equipment_request = EquipmentAllocationRequest(
            booking_id=booking_id,
            court_id=request.court_id,
            interval=interval,
            items=tuple(
                EquipmentRequestLine(
                    equipment_id=item.equipment_id,
                    quantity=item.quantity,
                )
                for item in request.equipment
            ),
        )
        equipment_result = (
            allocation.validate_equipment_request(equipment_request)
            if request.equipment
            else None
        )

        if request.equipment_decision == "CANCEL_REQUEST":
            return BookingRequestCancelledResponse()

        if (
            equipment_result is not None
            and equipment_result.shortages
            and request.equipment_decision is None
        ):
            return EquipmentDecisionRequiredResponse(
                shortages=tuple(
                    EquipmentShortageResponse(
                        equipment_id=shortage.equipment_id,
                        requested_quantity=shortage.requested_quantity,
                        available_quantity=shortage.available_quantity,
                    )
                    for shortage in equipment_result.shortages
                )
            )

        if (
            equipment_result is not None
            and not equipment_result.valid
            and not equipment_result.shortages
        ):
            raise BookingAvailabilityError(equipment_result.errors)

        final_items = tuple(request.equipment)
        if request.equipment_decision == "CONTINUE_WITHOUT_EQUIPMENT":
            final_allocation = await self._load_fresh_allocation_service(
                request.booking_date
            )
            final_court_result = final_allocation.check_court_availability(
                request.court_id,
                request.booking_date,
                interval,
            )
            if not final_court_result.valid:
                raise BookingAvailabilityError(final_court_result.errors)

            final_equipment_result = (
                final_allocation.validate_equipment_request(equipment_request)
                if request.equipment
                else None
            )
            if final_equipment_result is not None and (
                not final_equipment_result.valid
                and not final_equipment_result.shortages
            ):
                raise BookingAvailabilityError(final_equipment_result.errors)
            unavailable_ids = {
                shortage.equipment_id
                for shortage in (
                    final_equipment_result.shortages
                    if final_equipment_result is not None
                    else ()
                )
            }
            final_items = tuple(
                item
                for item in request.equipment
                if item.equipment_id not in unavailable_ids
            )

        lock_token = await self.concurrency.acquire_with_wait(
            interval,
            str(request.court_id),
        )
        try:
            try:
                record = await self.persistence.create_booking(
                    CreateBookingInput(
                        booking_id=booking_id,
                        user_id=user_id,
                        court_id=request.court_id,
                        booking_date=request.booking_date,
                        start_time=request.start_time,
                        end_time=request.end_time,
                        items=tuple(
                            BookingEquipmentLine(
                                equipment_id=item.equipment_id,
                                quantity=item.quantity,
                            )
                            for item in final_items
                        ),
                    )
                )
            except (
                BookingConflictError,
                BookingResourceUnavailableError,
                BookingStartTimeExpiredError,
                EquipmentUnavailableError,
                SQLAlchemyError,
            ):
                self._invalidate_allocation_snapshot()
                raise
            self._state_revision += 1
            try:
                await self._ensure_allocation_snapshot(request.booking_date)
            except (AllocationSnapshotError, SQLAlchemyError) as error:
                self._invalidate_allocation_snapshot()
                raise BookingCommittedCacheRefreshError(record.booking_id) from error
            return record
        finally:
            await self.concurrency.release(lock_token)

    async def list_student_bookings(self, user_id: UUID) -> list[BookingRecord]:
        if self.persistence is None:
            raise RuntimeError("Persistence repository is not configured")
        return await self.persistence.list_student_bookings(user_id)

    async def coordinate_student_cancellation(
        self,
        booking_id: UUID,
        user_id: UUID,
    ) -> BookingRecord:
        if self.concurrency is None or self.persistence is None:
            raise RuntimeError("Booking coordinator dependencies are not configured")

        booking = await self.persistence.get_booking_for_student(
            booking_id,
            user_id,
        )
        if booking is None:
            raise BookingNotFoundError
        interval = TimeInterval(
            start=datetime.combine(booking.booking_date, booking.start_time),
            end=datetime.combine(booking.booking_date, booking.end_time),
        )
        lock_token = await self.concurrency.acquire_with_wait(
            interval,
            str(booking.court_id),
        )
        try:
            try:
                record = await self.persistence.cancel_booking(
                    booking_id,
                    user_id,
                )
            except (
                BookingAlreadyCancelledError,
                BookingCancellationExpiredError,
                BookingNotFoundError,
                SQLAlchemyError,
            ):
                self._invalidate_allocation_snapshot()
                raise
            self._state_revision += 1
            try:
                await self._ensure_allocation_snapshot(booking.booking_date)
            except (AllocationSnapshotError, SQLAlchemyError) as error:
                self._invalidate_allocation_snapshot()
                raise BookingCommittedCacheRefreshError(record.booking_id) from error
            return record
        finally:
            await self.concurrency.release(lock_token)

    def _invalidate_allocation_snapshot(self) -> None:
        self._allocation_revision = -1

    async def _ensure_allocation_snapshot(
        self,
        reference_date: date,
    ) -> AllocationService:
        if self.persistence is None:
            raise RuntimeError("Persistence repository is not configured")
        window_end = reference_date + timedelta(days=6)
        if (
            self.allocation is not None
            and self._allocation_revision == self._state_revision
            and self._allocation_window is not None
            and self._allocation_window[0] <= reference_date <= self._allocation_window[1]
        ):
            return self.allocation

        async with self._snapshot_lock:
            while True:
                if (
                    self.allocation is not None
                    and self._allocation_revision == self._state_revision
                    and self._allocation_window is not None
                    and self._allocation_window[0]
                    <= reference_date
                    <= self._allocation_window[1]
                ):
                    return self.allocation

                revision = self._state_revision
                snapshot = await self.persistence.load_allocation_snapshot(
                    reference_date
                )
                if revision != self._state_revision:
                    continue
                allocation = self._build_allocation_service(
                    snapshot,
                    reference_date,
                )
                self.allocation = allocation
                self._allocation_revision = revision
                self._allocation_window = (reference_date, window_end)
                return allocation

    async def _load_fresh_allocation_service(
        self,
        reference_date: date,
    ) -> AllocationService:
        if self.persistence is None:
            raise RuntimeError("Persistence repository is not configured")

        async with self._snapshot_lock:
            while True:
                revision = self._state_revision
                snapshot = await self.persistence.load_allocation_snapshot(
                    reference_date
                )
                if revision != self._state_revision:
                    continue
                return self._build_allocation_service(snapshot, reference_date)

    @staticmethod
    def _build_allocation_service(
        snapshot: AllocationSnapshot,
        reference_date: date,
    ) -> AllocationService:
        allocation = AllocationService()
        try:
            bookings = [
                CommittedBooking(
                    booking_id=booking.booking_id,
                    court_id=booking.court_id,
                    owner_id=booking.user_id,
                    interval=TimeInterval(
                        start=datetime.combine(
                            booking.booking_date,
                            booking.start_time,
                        ),
                        end=datetime.combine(
                            booking.booking_date,
                            booking.end_time,
                        ),
                    ),
                )
                for booking in snapshot.bookings
            ]
            blocks = [
                EffectiveCourtBlock(
                    block_id=block.block_out_id,
                    court_id=block.court_id,
                    interval=TimeInterval(
                        start=block.starts_at,
                        end=block.ends_at,
                    ),
                )
                for block in snapshot.blocks
            ]
            allocation.generate_availability(
                active_court_ids=snapshot.active_court_ids,
                bookings=bookings,
                blocks=blocks,
                reference_date=reference_date,
            )
            for item in snapshot.equipment_inventory:
                result = allocation.set_equipment_inventory(
                    EquipmentInventory(
                        equipment_id=item.equipment_id,
                        total_quantity=item.total_quantity,
                    )
                )
                if not result.valid:
                    raise AllocationSnapshotError("; ".join(result.errors))

            reservations = [
                EquipmentReservation(
                    equipment_id=item.equipment_id,
                    booking_id=item.booking_id,
                    interval=TimeInterval(
                        start=datetime.combine(
                            item.booking_date,
                            item.start_time,
                        ),
                        end=datetime.combine(
                            item.booking_date,
                            item.end_time,
                        ),
                    ),
                    quantity=item.quantity,
                )
                for item in snapshot.equipment_reservations
            ]
            result = allocation.refresh_equipment_reservations(reservations)
            if not result.valid:
                raise AllocationSnapshotError("; ".join(result.errors))
        except (TypeError, ValueError) as error:
            raise AllocationSnapshotError(
                "The persisted allocation snapshot is invalid"
            ) from error
        return allocation
