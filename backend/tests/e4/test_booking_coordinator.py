from datetime import date, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.contracts.booking import LockToken, TimeInterval
from app.e2_allocation.service import AllocationService
from app.e3_persistence.errors import (
    BookingAlreadyCancelledError,
    BookingCancellationExpiredError,
    BookingConflictError,
    BookingNotFoundError,
    BookingStartTimeExpiredError,
    EquipmentUnavailableError,
)
from app.e3_persistence.inputs import (
    AllocationSnapshot,
    BlockOutSnapshotRecord,
    BookingRecord,
    BookingSnapshotRecord,
    CreateBookingInput,
    EquipmentInventorySnapshotRecord,
    EquipmentReservationSnapshotRecord,
)
from app.e4_communication.coordinator import (
    AllocationSnapshotError,
    BookingAvailabilityError,
    BookingCommittedCacheRefreshError,
    BookingCoordinator,
)
from app.e4_communication.schemas import (
    BookingRequestCancelledResponse,
    EquipmentDecisionRequiredResponse,
    StudentBookingRequest,
)


class FakeConcurrency:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def acquire_with_wait(
        self,
        interval: TimeInterval,
        resource_id: str,
        timeout: float = 3.0,
    ) -> LockToken:
        self.events.append(f"lock:{resource_id}")
        return LockToken(token=uuid4(), interval=interval)

    async def release(self, token: LockToken) -> None:
        self.events.append("release")


class FakePersistence:
    def __init__(
        self,
        events: list[str],
        court_id: UUID,
        equipment_id: UUID,
        should_conflict: bool = False,
    ) -> None:
        self.events = events
        self.court_id = court_id
        self.equipment_id = equipment_id
        self.should_conflict = should_conflict
        self.equipment_inventory = (
            EquipmentInventorySnapshotRecord(equipment_id, 3),
        )
        self.snapshot_overrides: list[AllocationSnapshot] = []
        self.snapshot_failure_after_create: Exception | None = None
        self.create_error: Exception | None = None
        self.create_calls: list[CreateBookingInput] = []
        self.on_create = None
        self.cancel_error: Exception | None = None
        self.on_cancel = None
        self.bookings: tuple[BookingSnapshotRecord, ...] = ()
        self.reservations: tuple[EquipmentReservationSnapshotRecord, ...] = ()
        self.last_record: BookingRecord | None = None

    async def load_allocation_snapshot(
        self, reference_date: date
    ) -> AllocationSnapshot:
        self.events.append("snapshot")
        if self.last_record is not None and self.snapshot_failure_after_create:
            raise self.snapshot_failure_after_create
        if self.snapshot_overrides:
            return self.snapshot_overrides.pop(0)
        return AllocationSnapshot(
            active_court_ids=(self.court_id,),
            bookings=self.bookings,
            blocks=(),
            equipment_inventory=self.equipment_inventory,
            equipment_reservations=self.reservations,
        )

    async def create_booking(self, command: CreateBookingInput) -> BookingRecord:
        self.events.append("create")
        self.create_calls.append(command)
        if self.on_create is not None:
            self.on_create()
        if self.should_conflict:
            raise BookingConflictError("slot already claimed")
        if self.create_error is not None:
            raise self.create_error
        self.bookings = (
            BookingSnapshotRecord(
                command.booking_id,
                command.court_id,
                command.booking_date,
                command.start_time,
                command.end_time,
            ),
        )
        self.reservations = tuple(
            EquipmentReservationSnapshotRecord(
                item.equipment_id,
                command.booking_id,
                command.booking_date,
                command.start_time,
                command.end_time,
                item.quantity,
            )
            for item in command.items
        )
        self.last_record = BookingRecord(
            booking_id=command.booking_id,
            user_id=command.user_id,
            court_id=command.court_id,
            booking_date=command.booking_date,
            start_time=command.start_time,
            end_time=command.end_time,
            status="BOOKED",
            items=command.items,
        )
        return self.last_record

    async def get_booking_for_student(
        self,
        booking_id: UUID,
        user_id: UUID,
    ) -> BookingRecord | None:
        self.events.append("get-booking")
        if (
            self.last_record is None
            or self.last_record.booking_id != booking_id
            or self.last_record.user_id != user_id
        ):
            return None
        return self.last_record

    async def list_student_bookings(self, user_id: UUID) -> list[BookingRecord]:
        if self.last_record is None or self.last_record.user_id != user_id:
            return []
        return [self.last_record]

    async def cancel_booking(
        self,
        booking_id: UUID,
        user_id: UUID,
        now=None,
    ) -> BookingRecord:
        self.events.append("cancel")
        if self.on_cancel is not None:
            self.on_cancel()
        if self.cancel_error is not None:
            raise self.cancel_error
        assert self.last_record is not None
        if self.last_record.status == "CANCELLED":
            raise BookingAlreadyCancelledError
        self.last_record = BookingRecord(
            booking_id=self.last_record.booking_id,
            user_id=self.last_record.user_id,
            court_id=self.last_record.court_id,
            booking_date=self.last_record.booking_date,
            start_time=self.last_record.start_time,
            end_time=self.last_record.end_time,
            status="CANCELLED",
            items=self.last_record.items,
        )
        self.bookings = ()
        self.reservations = ()
        return self.last_record


def booking_request(
    court_id: UUID,
    equipment_id: UUID | None,
    *,
    equipment_decision: str | None = None,
) -> StudentBookingRequest:
    return StudentBookingRequest(
        court_id=court_id,
        booking_date=date.today() + timedelta(days=1),
        start_time=time(9, 0),
        end_time=time(10, 0),
        equipment=(
            [{"equipment_id": equipment_id, "quantity": 2}]
            if equipment_id is not None
            else []
        ),
        equipment_decision=equipment_decision,
    )


def request_with_equipment(
    court_id: UUID,
    equipment: tuple[tuple[UUID, int], ...],
    *,
    decision: str | None = None,
) -> StudentBookingRequest:
    return StudentBookingRequest(
        court_id=court_id,
        booking_date=date.today() + timedelta(days=1),
        start_time=time(9, 0),
        end_time=time(10, 0),
        equipment=[
            {"equipment_id": equipment_id, "quantity": quantity}
            for equipment_id, quantity in equipment
        ],
        equipment_decision=decision,
    )


def allocation_snapshot(
    court_id: UUID,
    inventory: tuple[EquipmentInventorySnapshotRecord, ...],
    bookings: tuple[BookingSnapshotRecord, ...] = (),
) -> AllocationSnapshot:
    return AllocationSnapshot(
        active_court_ids=(court_id,),
        bookings=bookings,
        blocks=(),
        equipment_inventory=inventory,
        equipment_reservations=(),
    )


@pytest.mark.asyncio
async def test_booking_checks_e2_then_locks_persists_and_refreshes_after_commit():
    events: list[str] = []
    court_id, equipment_id, user_id = uuid4(), uuid4(), uuid4()
    persistence = FakePersistence(events, court_id, equipment_id)
    coordinator = BookingCoordinator(
        concurrency=FakeConcurrency(events),
        persistence=persistence,
    )

    result = await coordinator.coordinate_student_booking(
        booking_request(court_id, equipment_id),
        user_id,
    )

    assert result.user_id == user_id
    assert events == [
        "snapshot",
        f"lock:{court_id}",
        "create",
        "snapshot",
        "release",
    ]
    intervals = coordinator.allocation.get_court_availability(
        court_id,
        result.booking_date,
    )
    assert intervals is not None
    assert any(
        interval.reference_id == result.booking_id
        and interval.interval.start == datetime.combine(
            result.booking_date, result.start_time
        )
        for interval in intervals
    )


@pytest.mark.asyncio
async def test_e2_precheck_rejects_conflict_before_e1_lock():
    events: list[str] = []
    court_id, equipment_id = uuid4(), uuid4()
    request = booking_request(court_id, equipment_id)
    persistence = FakePersistence(events, court_id, equipment_id)
    persistence.bookings = (
        BookingSnapshotRecord(
            uuid4(),
            court_id,
            request.booking_date,
            time(9, 0),
            time(10, 0),
        ),
    )
    coordinator = BookingCoordinator(
        concurrency=FakeConcurrency(events),
        persistence=persistence,
    )

    with pytest.raises(BookingAvailabilityError):
        await coordinator.coordinate_student_booking(request, uuid4())

    assert events == ["snapshot"]


@pytest.mark.asyncio
async def test_initial_court_conflict_precedes_equipment_shortage_decision():
    events: list[str] = []
    court_id, equipment_id = uuid4(), uuid4()
    request = booking_request(court_id, equipment_id)
    persistence = FakePersistence(events, court_id, equipment_id)
    persistence.bookings = (
        BookingSnapshotRecord(
            uuid4(),
            court_id,
            request.booking_date,
            request.start_time,
            request.end_time,
        ),
    )
    persistence.equipment_inventory = (
        EquipmentInventorySnapshotRecord(equipment_id, 0),
    )
    coordinator = BookingCoordinator(
        concurrency=FakeConcurrency(events),
        persistence=persistence,
    )

    with pytest.raises(BookingAvailabilityError) as raised:
        await coordinator.coordinate_student_booking(request, uuid4())

    assert raised.value.errors == [
        "Requested interval overlaps a BOOKED interval."
    ]
    assert events == ["snapshot"]
    assert persistence.create_calls == []


@pytest.mark.asyncio
async def test_multiple_equipment_shortages_return_decision_required_without_side_effects():
    events: list[str] = []
    court_id, first, second = uuid4(), uuid4(), uuid4()
    persistence = FakePersistence(events, court_id, first)
    persistence.equipment_inventory = (
        EquipmentInventorySnapshotRecord(first, 1),
        EquipmentInventorySnapshotRecord(second, 0),
    )
    coordinator = BookingCoordinator(
        concurrency=FakeConcurrency(events),
        persistence=persistence,
    )

    result = await coordinator.coordinate_student_booking(
        request_with_equipment(court_id, ((first, 2), (second, 3))),
        uuid4(),
    )

    assert isinstance(result, EquipmentDecisionRequiredResponse)
    assert result.code == "EQUIPMENT_DECISION_REQUIRED"
    assert result.permitted_decisions == (
        "CONTINUE_WITHOUT_EQUIPMENT",
        "CANCEL_REQUEST",
    )
    assert [
        (item.equipment_id, item.requested_quantity, item.available_quantity)
        for item in result.shortages
    ] == [(first, 2, 1), (second, 3, 0)]
    assert events == ["snapshot"]
    assert persistence.create_calls == []
    assert coordinator._state_revision == 0


@pytest.mark.asyncio
async def test_cancel_request_does_not_lock_persist_or_refresh():
    events: list[str] = []
    court_id, equipment_id = uuid4(), uuid4()
    persistence = FakePersistence(events, court_id, equipment_id)
    persistence.equipment_inventory = (
        EquipmentInventorySnapshotRecord(equipment_id, 0),
    )
    coordinator = BookingCoordinator(
        concurrency=FakeConcurrency(events),
        persistence=persistence,
    )

    result = await coordinator.coordinate_student_booking(
        booking_request(
            court_id,
            equipment_id,
            equipment_decision="CANCEL_REQUEST",
        ),
        uuid4(),
    )

    assert isinstance(result, BookingRequestCancelledResponse)
    assert result.booking_created is False
    assert result.request_cancelled is True
    assert events == ["snapshot"]
    assert persistence.create_calls == []
    assert coordinator._state_revision == 0


@pytest.mark.asyncio
async def test_continue_rechecks_fresh_e2_before_lock_and_keeps_only_available_items(
    monkeypatch,
):
    events: list[str] = []
    court_id, available_id, unavailable_id, user_id = [uuid4() for _ in range(4)]
    persistence = FakePersistence(events, court_id, available_id)
    persistence.equipment_inventory = (
        EquipmentInventorySnapshotRecord(available_id, 5),
        EquipmentInventorySnapshotRecord(unavailable_id, 1),
    )
    coordinator = BookingCoordinator(
        concurrency=FakeConcurrency(events),
        persistence=persistence,
    )
    original_court_check = AllocationService.check_court_availability
    original_equipment_check = AllocationService.validate_equipment_request

    def observe_court_check(service, *args, **kwargs):
        events.append("court-check")
        return original_court_check(service, *args, **kwargs)

    def observe_equipment_check(service, *args, **kwargs):
        events.append("equipment-check")
        return original_equipment_check(service, *args, **kwargs)

    monkeypatch.setattr(
        AllocationService,
        "check_court_availability",
        observe_court_check,
    )
    monkeypatch.setattr(
        AllocationService,
        "validate_equipment_request",
        observe_equipment_check,
    )

    allocation_during_create = []

    def observe_create():
        allocation_during_create.append(coordinator.allocation)

    persistence.on_create = observe_create
    result = await coordinator.coordinate_student_booking(
        request_with_equipment(
            court_id,
            ((available_id, 2), (unavailable_id, 2)),
            decision="CONTINUE_WITHOUT_EQUIPMENT",
        ),
        user_id,
    )

    assert isinstance(result, BookingRecord)
    assert [(item.equipment_id, item.quantity) for item in result.items] == [
        (available_id, 2)
    ]
    assert [item.equipment_id for item in persistence.create_calls[0].items] == [
        available_id
    ]
    lock_index = next(i for i, event in enumerate(events) if event.startswith("lock:"))
    assert events[lock_index - 1] == "equipment-check"
    create_index = events.index("create")
    assert events.index("snapshot", create_index + 1) > create_index
    assert events[-2:] == ["snapshot", "release"]
    assert len(allocation_during_create) == 1
    assert coordinator.allocation is not None
    assert allocation_during_create[0] is not coordinator.allocation


@pytest.mark.asyncio
async def test_continue_with_all_equipment_unavailable_creates_court_only_booking():
    events: list[str] = []
    court_id, equipment_id = uuid4(), uuid4()
    persistence = FakePersistence(events, court_id, equipment_id)
    persistence.equipment_inventory = (
        EquipmentInventorySnapshotRecord(equipment_id, 0),
    )
    coordinator = BookingCoordinator(
        concurrency=FakeConcurrency(events),
        persistence=persistence,
    )

    result = await coordinator.coordinate_student_booking(
        booking_request(
            court_id,
            equipment_id,
            equipment_decision="CONTINUE_WITHOUT_EQUIPMENT",
        ),
        uuid4(),
    )

    assert isinstance(result, BookingRecord)
    assert result.items == ()
    assert persistence.create_calls[0].items == ()
    assert events == [
        "snapshot",
        "snapshot",
        f"lock:{court_id}",
        "create",
        "snapshot",
        "release",
    ]


@pytest.mark.asyncio
async def test_continue_retains_equipment_that_becomes_available_in_fresh_snapshot():
    events: list[str] = []
    court_id, equipment_id = uuid4(), uuid4()
    persistence = FakePersistence(events, court_id, equipment_id)
    persistence.equipment_inventory = (
        EquipmentInventorySnapshotRecord(equipment_id, 2),
    )
    persistence.snapshot_overrides = [
        allocation_snapshot(
            court_id,
            (EquipmentInventorySnapshotRecord(equipment_id, 0),),
        ),
        allocation_snapshot(
            court_id,
            (EquipmentInventorySnapshotRecord(equipment_id, 2),),
        ),
    ]
    coordinator = BookingCoordinator(
        concurrency=FakeConcurrency(events),
        persistence=persistence,
    )

    result = await coordinator.coordinate_student_booking(
        booking_request(
            court_id,
            equipment_id,
            equipment_decision="CONTINUE_WITHOUT_EQUIPMENT",
        ),
        uuid4(),
    )

    assert isinstance(result, BookingRecord)
    assert [(item.equipment_id, item.quantity) for item in result.items] == [
        (equipment_id, 2)
    ]


@pytest.mark.asyncio
async def test_final_court_conflict_prevents_lock_and_persistence():
    events: list[str] = []
    court_id, equipment_id = uuid4(), uuid4()
    request = booking_request(
        court_id,
        equipment_id,
        equipment_decision="CONTINUE_WITHOUT_EQUIPMENT",
    )
    conflict = BookingSnapshotRecord(
        uuid4(),
        court_id,
        request.booking_date,
        request.start_time,
        request.end_time,
    )
    persistence = FakePersistence(events, court_id, equipment_id)
    persistence.equipment_inventory = (
        EquipmentInventorySnapshotRecord(equipment_id, 0),
    )
    persistence.snapshot_overrides = [
        allocation_snapshot(
            court_id,
            (EquipmentInventorySnapshotRecord(equipment_id, 0),),
        ),
        allocation_snapshot(
            court_id,
            (EquipmentInventorySnapshotRecord(equipment_id, 0),),
            bookings=(conflict,),
        ),
    ]
    coordinator = BookingCoordinator(
        concurrency=FakeConcurrency(events),
        persistence=persistence,
    )

    with pytest.raises(BookingAvailabilityError):
        await coordinator.coordinate_student_booking(request, uuid4())

    assert events == ["snapshot", "snapshot"]
    assert persistence.create_calls == []


@pytest.mark.asyncio
async def test_database_conflict_after_lock_releases_e1_token():
    events: list[str] = []
    court_id, equipment_id = uuid4(), uuid4()
    persistence = FakePersistence(
        events,
        court_id,
        equipment_id,
        should_conflict=True,
    )
    coordinator = BookingCoordinator(
        concurrency=FakeConcurrency(events),
        persistence=persistence,
    )

    with pytest.raises(BookingConflictError):
        await coordinator.coordinate_student_booking(
            booking_request(court_id, equipment_id),
            uuid4(),
        )

    assert events == ["snapshot", f"lock:{court_id}", "create", "release"]


@pytest.mark.asyncio
async def test_equipment_capacity_rejection_after_lock_does_not_refresh_and_releases():
    events: list[str] = []
    court_id, equipment_id = uuid4(), uuid4()
    persistence = FakePersistence(events, court_id, equipment_id)
    persistence.create_error = EquipmentUnavailableError(
        equipment_id,
        requested_quantity=2,
        available_quantity=1,
    )
    coordinator = BookingCoordinator(
        concurrency=FakeConcurrency(events),
        persistence=persistence,
    )

    with pytest.raises(EquipmentUnavailableError):
        await coordinator.coordinate_student_booking(
            booking_request(court_id, equipment_id),
            uuid4(),
        )

    assert events == ["snapshot", f"lock:{court_id}", "create", "release"]
    assert persistence.last_record is None
    assert coordinator._state_revision == 0
    assert coordinator._allocation_revision == -1


@pytest.mark.asyncio
async def test_unexpected_persistence_error_releases_lock_without_cache_refresh():
    events: list[str] = []
    court_id, equipment_id = uuid4(), uuid4()
    persistence = FakePersistence(events, court_id, equipment_id)
    persistence.create_error = RuntimeError("unexpected persistence failure")
    coordinator = BookingCoordinator(
        concurrency=FakeConcurrency(events),
        persistence=persistence,
    )

    with pytest.raises(RuntimeError, match="unexpected persistence failure"):
        await coordinator.coordinate_student_booking(
            booking_request(court_id, equipment_id),
            uuid4(),
        )

    assert events == ["snapshot", f"lock:{court_id}", "create", "release"]
    assert persistence.last_record is None
    assert coordinator._state_revision == 0


@pytest.mark.asyncio
async def test_persistence_start_time_rejection_releases_lock_without_refresh():
    events: list[str] = []
    court_id, equipment_id = uuid4(), uuid4()
    persistence = FakePersistence(events, court_id, equipment_id)
    persistence.create_error = BookingStartTimeExpiredError()
    coordinator = BookingCoordinator(
        concurrency=FakeConcurrency(events),
        persistence=persistence,
    )

    with pytest.raises(BookingStartTimeExpiredError):
        await coordinator.coordinate_student_booking(
            booking_request(court_id, equipment_id),
            uuid4(),
        )

    assert events == ["snapshot", f"lock:{court_id}", "create", "release"]
    assert persistence.last_record is None
    assert coordinator._state_revision == 0


@pytest.mark.asyncio
async def test_refresh_failure_reports_committed_booking_and_invalidates_snapshot():
    events: list[str] = []
    court_id, equipment_id, user_id = uuid4(), uuid4(), uuid4()
    persistence = FakePersistence(events, court_id, equipment_id)
    persistence.snapshot_failure_after_create = SQLAlchemyError(
        "simulated snapshot read failure"
    )
    coordinator = BookingCoordinator(
        concurrency=FakeConcurrency(events),
        persistence=persistence,
    )

    with pytest.raises(BookingCommittedCacheRefreshError) as raised:
        await coordinator.coordinate_student_booking(
            booking_request(court_id, equipment_id),
            user_id,
        )

    assert persistence.last_record is not None
    assert persistence.last_record.status == "BOOKED"
    assert raised.value.booking_id == persistence.last_record.booking_id
    assert events == [
        "snapshot",
        f"lock:{court_id}",
        "create",
        "snapshot",
        "release",
    ]
    assert coordinator._allocation_revision == -1


@pytest.mark.asyncio
async def test_court_only_booking_without_equipment_still_succeeds():
    events: list[str] = []
    court_id, equipment_id, user_id = uuid4(), uuid4(), uuid4()
    persistence = FakePersistence(events, court_id, equipment_id)
    coordinator = BookingCoordinator(
        concurrency=FakeConcurrency(events),
        persistence=persistence,
    )

    result = await coordinator.coordinate_student_booking(
        booking_request(court_id, None),
        user_id,
    )

    assert isinstance(result, BookingRecord)
    assert result.status == "BOOKED"
    assert result.items == ()
    assert events == [
        "snapshot",
        f"lock:{court_id}",
        "create",
        "snapshot",
        "release",
    ]


@pytest.mark.asyncio
async def test_cancellation_reads_metadata_then_locks_persists_and_refreshes():
    events: list[str] = []
    court_id, equipment_id, user_id = uuid4(), uuid4(), uuid4()
    persistence = FakePersistence(events, court_id, equipment_id)
    coordinator = BookingCoordinator(
        concurrency=FakeConcurrency(events),
        persistence=persistence,
    )
    created = await coordinator.coordinate_student_booking(
        booking_request(court_id, equipment_id),
        user_id,
    )
    events.clear()
    allocation_before_cancel = coordinator.allocation
    persistence.on_cancel = lambda: (
        events.append(
            "cache-unchanged-before-cancel-commit"
            if coordinator.allocation is allocation_before_cancel
            else "cache-changed-before-cancel-commit"
        )
    )

    cancelled = await coordinator.coordinate_student_cancellation(
        created.booking_id,
        user_id,
    )

    assert cancelled.status == "CANCELLED"
    assert events == [
        "get-booking",
        f"lock:{court_id}",
        "cancel",
        "cache-unchanged-before-cancel-commit",
        "snapshot",
        "release",
    ]
    assert coordinator.allocation is not allocation_before_cancel
    assert coordinator.allocation is not None
    assert coordinator.allocation.get_equipment_availability(
        equipment_id,
        TimeInterval(
            start=datetime.combine(created.booking_date, created.start_time),
            end=datetime.combine(created.booking_date, created.end_time),
        ),
    ).available_quantity == 3


@pytest.mark.asyncio
async def test_non_owner_cannot_cancel_and_never_acquires_lock():
    events: list[str] = []
    court_id, equipment_id, user_id = uuid4(), uuid4(), uuid4()
    persistence = FakePersistence(events, court_id, equipment_id)
    coordinator = BookingCoordinator(
        concurrency=FakeConcurrency(events),
        persistence=persistence,
    )
    created = await coordinator.coordinate_student_booking(
        booking_request(court_id, equipment_id),
        user_id,
    )
    events.clear()

    with pytest.raises(BookingNotFoundError):
        await coordinator.coordinate_student_cancellation(
            created.booking_id,
            uuid4(),
        )

    assert events == ["get-booking"]


@pytest.mark.asyncio
async def test_cancellation_persistence_failure_releases_e1_lock():
    events: list[str] = []
    court_id, equipment_id, user_id = uuid4(), uuid4(), uuid4()
    persistence = FakePersistence(events, court_id, equipment_id)
    coordinator = BookingCoordinator(
        concurrency=FakeConcurrency(events),
        persistence=persistence,
    )
    created = await coordinator.coordinate_student_booking(
        booking_request(court_id, equipment_id),
        user_id,
    )
    events.clear()
    persistence.cancel_error = BookingCancellationExpiredError(
        "booking has already started"
    )

    with pytest.raises(BookingCancellationExpiredError):
        await coordinator.coordinate_student_cancellation(
            created.booking_id,
            user_id,
        )

    assert events == [
        "get-booking",
        f"lock:{court_id}",
        "cancel",
        "release",
    ]


@pytest.mark.asyncio
async def test_repeated_cancellation_is_rejected_and_releases_lock():
    events: list[str] = []
    court_id, equipment_id, user_id = uuid4(), uuid4(), uuid4()
    persistence = FakePersistence(events, court_id, equipment_id)
    coordinator = BookingCoordinator(
        concurrency=FakeConcurrency(events),
        persistence=persistence,
    )
    created = await coordinator.coordinate_student_booking(
        booking_request(court_id, equipment_id),
        user_id,
    )
    await coordinator.coordinate_student_cancellation(created.booking_id, user_id)
    events.clear()

    with pytest.raises(BookingAlreadyCancelledError):
        await coordinator.coordinate_student_cancellation(
            created.booking_id,
            user_id,
        )

    assert events == [
        "get-booking",
        f"lock:{court_id}",
        "cancel",
        "release",
    ]


@pytest.mark.asyncio
async def test_cancellation_refresh_failure_reports_commit_and_releases_lock():
    events: list[str] = []
    court_id, equipment_id, user_id = uuid4(), uuid4(), uuid4()
    persistence = FakePersistence(events, court_id, equipment_id)
    coordinator = BookingCoordinator(
        concurrency=FakeConcurrency(events),
        persistence=persistence,
    )
    created = await coordinator.coordinate_student_booking(
        booking_request(court_id, equipment_id),
        user_id,
    )
    events.clear()
    persistence.snapshot_failure_after_create = SQLAlchemyError(
        "simulated cancellation snapshot failure"
    )

    with pytest.raises(BookingCommittedCacheRefreshError) as raised:
        await coordinator.coordinate_student_cancellation(
            created.booking_id,
            user_id,
        )

    assert raised.value.booking_id == created.booking_id
    assert persistence.last_record is not None
    assert persistence.last_record.status == "CANCELLED"
    assert events == [
        "get-booking",
        f"lock:{court_id}",
        "cancel",
        "snapshot",
        "release",
    ]


@pytest.mark.asyncio
async def test_availability_read_returns_free_booked_and_blocked_segments():
    events: list[str] = []
    court_id, equipment_id, owner_id = uuid4(), uuid4(), uuid4()
    booking_id = uuid4()
    block_id = uuid4()
    reference_date = date.today() + timedelta(days=1)
    persistence = FakePersistence(events, court_id, equipment_id)
    persistence.snapshot_overrides = [
        AllocationSnapshot(
            active_court_ids=(court_id,),
            bookings=(
                BookingSnapshotRecord(
                    booking_id=booking_id,
                    court_id=court_id,
                    booking_date=reference_date,
                    start_time=time(9, 0),
                    end_time=time(10, 0),
                    user_id=owner_id,
                ),
            ),
            blocks=(
                BlockOutSnapshotRecord(
                    block_out_id=block_id,
                    court_id=court_id,
                    starts_at=datetime.combine(reference_date, time(13, 15)),
                    ends_at=datetime.combine(reference_date, time(14, 0)),
                ),
            ),
            equipment_inventory=(),
            equipment_reservations=(),
        )
    ]
    coordinator = BookingCoordinator(persistence=persistence)

    returned_court, returned_date, days = await coordinator.get_court_availability(
        court_id,
        reference_date,
    )

    assert returned_court == court_id
    assert returned_date == reference_date
    assert len(days) == 7
    intervals = days[0][1]
    assert [(item.status.value, item.interval.start.time(), item.interval.end.time()) for item in intervals] == [
        ("FREE", time(6, 0), time(9, 0)),
        ("BOOKED", time(9, 0), time(10, 0)),
        ("FREE", time(10, 0), time(13, 15)),
        ("BLOCKED", time(13, 15), time(14, 0)),
        ("FREE", time(14, 0), time(20, 0)),
    ]
    assert intervals[1].owner_id == owner_id
    assert intervals[3].owner_id is None


@pytest.mark.asyncio
async def test_availability_read_supports_adjacent_arbitrary_minute_intervals():
    events: list[str] = []
    court_id, equipment_id = uuid4(), uuid4()
    reference_date = date.today() + timedelta(days=1)
    persistence = FakePersistence(events, court_id, equipment_id)
    persistence.snapshot_overrides = [
        AllocationSnapshot(
            active_court_ids=(court_id,),
            bookings=(
                BookingSnapshotRecord(
                    uuid4(), court_id, reference_date, time(9, 12), time(9, 27)
                ),
                BookingSnapshotRecord(
                    uuid4(), court_id, reference_date, time(9, 27), time(10, 7)
                ),
            ),
            blocks=(),
            equipment_inventory=(),
            equipment_reservations=(),
        )
    ]
    coordinator = BookingCoordinator(persistence=persistence)

    _, _, days = await coordinator.get_court_availability(court_id, reference_date)
    intervals = days[0][1]

    assert [
        (
            item.status.value,
            item.interval.start.strftime("%H:%M"),
            item.interval.end.strftime("%H:%M"),
        )
        for item in intervals
    ] == [
        ("FREE", "06:00", "09:12"),
        ("BOOKED", "09:12", "09:27"),
        ("BOOKED", "09:27", "10:07"),
        ("FREE", "10:07", "20:00"),
    ]


@pytest.mark.asyncio
async def test_availability_read_rejects_overlapping_persisted_intervals():
    events: list[str] = []
    court_id, equipment_id = uuid4(), uuid4()
    reference_date = date.today() + timedelta(days=1)
    persistence = FakePersistence(events, court_id, equipment_id)
    persistence.snapshot_overrides = [
        AllocationSnapshot(
            active_court_ids=(court_id,),
            bookings=(
                BookingSnapshotRecord(
                    uuid4(), court_id, reference_date, time(9, 0), time(10, 0)
                ),
                BookingSnapshotRecord(
                    uuid4(), court_id, reference_date, time(9, 30), time(10, 30)
                ),
            ),
            blocks=(),
            equipment_inventory=(),
            equipment_reservations=(),
        )
    ]
    coordinator = BookingCoordinator(persistence=persistence)

    with pytest.raises(AllocationSnapshotError):
        await coordinator.get_court_availability(court_id, reference_date)
    assert coordinator._allocation_revision == -1
