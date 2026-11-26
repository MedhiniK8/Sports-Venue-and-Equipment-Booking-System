# E1–E2–E3–E4 Integration Design

**Status:** Historical integration design baseline with a current implementation snapshot below. Use the E2 integration guide and current source for the as-built student workflow.  
**Repository state inspected for the historical baseline:** branch `feat/e3-persistence`, commit `f237bab` (`Merge E1 concurrency engine into E3 persistence`), worktree clean at inspection.  
**Evidence labels:** **CONFIRMED** means verified in current source; **MISSING** means no implementation was found; **PROPOSED** means a design recommendation; **UNRESOLVED** means the source or requirements do not settle the point.

Sections 1–15 record the historical inspection and its recommendations. They are not a current API specification; statements in those sections that conflict with the current implementation snapshot are historical.

**Current implementation snapshot:** E3 owns the eight InnoDB models, including the physical `users` table and student persistence. E4 owns student registration, login, authentication, JWT handling, and student-facing APIs. Booking statuses are exactly `BOOKED` and `CANCELLED`. E4 performs E2 court/equipment checks before E1; the continue-without-equipment decision forces a fresh E3 snapshot and final E2 checks before E1. E3 atomically persists the booking, minute claims, and retained equipment allocations, then E4 refreshes E2 after commit. Cancellation uses persisted interval metadata, an E1 lock, transactional E3 ownership/status/start-time checks, and post-commit E2 refresh. Venue-local current-time decisions use `ZoneInfo("Asia/Kolkata")`; student request wall times and E2 interval datetimes remain naive venue-local values. Revision `0002` retains its binary-safe preflight for exact legacy booking statuses. Schema and unit tests use SQLite/fakes and do not verify MySQL locking behavior. No migration has been run against a live database, and no live MySQL schema has been created or tested. Frontend/admin workflows remain unimplemented.

## 1. Executive summary

The backend is a modular monolith: E1, E2, E3, and E4 are Python packages in one FastAPI application. The intended ownership boundaries are:

- **E1** temporarily coordinates concurrent operations on a court and interval.
- **E2** validates and derives court/equipment availability in process memory.
- **E3** owns durable MySQL state and database transactions.
- **E4** owns authentication, HTTP APIs, and orchestration between the other engines.

**CONFIRMED:** E1 has an in-memory asynchronous lock service. E2 has working in-memory court and equipment allocation logic. E3 has only a SQLAlchemy `Base`, a placeholder repository protocol, and lazy async session setup. E4 exposes only a health endpoint; its booking coordinator raises `NotImplementedError`. The React app currently calls only the health endpoint.

**PROPOSED:** E4 should first perform structural validation and preliminary E2 checks, then acquire E1's bounded-wait lock, refresh/revalidate against current database state, and ask E3 to create or cancel all durable records in one InnoDB transaction. After commit, E4 should rebuild/refresh E2 from a consistent E3 snapshot while still holding E1. MySQL constraints and transactions—not E1 or E2 memory—must be the final correctness boundary.

This design depends on several explicit contract changes: replace `venue_id` with `court_id`, support multiple equipment lines with quantities, expose E1's wait-aware method through the integration type, and define E3 repository operations. The E2 snapshot APIs also need a safe full-replacement strategy for court state and inventory, not only equipment reservations.

## 2. Current implementation status

### E1 — Concurrency

**CONFIRMED:** [`backend/app/e1_concurrency/service.py`](backend/app/e1_concurrency/service.py) implements `ConcurrencyService(ConcurrencyLockInterface)`:

```python
async def acquire(interval: TimeInterval, resource_id: str) -> LockToken
async def acquire_with_wait(
    interval: TimeInterval,
    resource_id: str,
    timeout: float = 3.0,
) -> LockToken
async def release(token: LockToken) -> None
```

`acquire()` is fail-fast. `acquire_with_wait()` uses a bounded waiter queue and a queue-wait timeout. It raises `LockQueueFullError` if the queue is full and `LockWaitTimeoutError` if the waiting deadline expires. `release()` requires the original token and matching interval; invalid or repeated release raises `InvalidLockTokenError`. E1 does not create booking IDs.

`lock_conflicts()` compares resource strings, start dates, and half-open interval overlap. It therefore handles overlapping—not merely exactly equal—intervals on the same court. E4 should pass `str(court_id)` as `resource_id` and a validated `TimeInterval`. E1 compares `start.date()` and does not itself reject a cross-date interval; the booking boundary must enforce E2's single-date rule before lock acquisition.

[`backend/app/e1_concurrency/INTEGRATION.md`](backend/app/e1_concurrency/INTEGRATION.md) recommends one shared service per worker and explicit release in `finally`. Its state is process-local; different workers do not share locks.

**Interface gap:** [`backend/app/contracts/interfaces.py`](backend/app/contracts/interfaces.py) declares `acquire()` and `release()` but not `acquire_with_wait()`. The concrete E1 service has the wait-aware method; code typed only against the shared interface cannot call it without changing the contract or using a concrete type.

### E2 — Allocation and conflict

**CONFIRMED:** [`backend/app/e2_allocation/service.py`](backend/app/e2_allocation/service.py) is E2's public service. These normal operations are synchronous:

```python
def generate_availability(
    self,
    active_court_ids: Iterable[UUID],
    bookings: Iterable[CommittedBooking],
    blocks: Iterable[EffectiveCourtBlock],
    reference_date: date,
) -> None

def get_court_availability(
    self, court_id: UUID, booking_date: date
) -> list[AvailabilityInterval] | None

def check_court_availability(
    self,
    court_id: UUID,
    booking_date: date,
    interval: TimeInterval,
    current_datetime: datetime | None = None,
) -> ValidationResult

def allocate_court(
    self,
    court_id: UUID,
    booking_date: date,
    interval: TimeInterval,
    booking_id: UUID,
    current_datetime: datetime | None = None,
) -> ValidationResult

def cancel_court(
    self, court_id: UUID, booking_date: date, booking_id: UUID
) -> ValidationResult

def apply_court_block(
    self,
    court_id: UUID,
    booking_date: date,
    interval: TimeInterval,
    block_id: UUID,
    current_datetime: datetime | None = None,
) -> ValidationResult

def set_equipment_inventory(
    self, inventory: EquipmentInventory
) -> EquipmentValidationResult

def refresh_equipment_reservations(
    self, reservations: Iterable[EquipmentReservation]
) -> EquipmentValidationResult

def get_equipment_availability(
    self,
    equipment_id: UUID,
    interval: TimeInterval,
    requested_quantity: int = 1,
) -> EquipmentAvailabilityResult

def allocate_equipment(
    self,
    request: EquipmentAllocationRequest,
    current_datetime: datetime | None = None,
) -> EquipmentAllocationResult

def cancel_equipment(
    self, booking_id: UUID, equipment_id: UUID | None = None
) -> EquipmentCancellationResult

def allocate_combined(
    self,
    court_id: UUID,
    booking_date: date,
    interval: TimeInterval,
    booking_id: UUID,
    items: tuple[EquipmentRequestLine, ...] = (),
    current_datetime: datetime | None = None,
) -> CombinedAllocationResult

def cancel_combined(
    self,
    booking_id: UUID,
    court_id: UUID | None = None,
    booking_date: date | None = None,
) -> CombinedCancellationResult
```

E2's documented import surface is in [`backend/app/e2_allocation/__init__.py`](backend/app/e2_allocation/__init__.py), and its integration guidance is [`backend/app/e2_allocation/INTEGRATION_GUIDE.md`](backend/app/e2_allocation/INTEGRATION_GUIDE.md).

`populate_seven_day_availability()` in [`availability_generation.py`](backend/app/e2_allocation/availability_generation.py) consumes active court UUIDs, `CommittedBooking(booking_id, court_id, interval)`, `EffectiveCourtBlock(block_id, court_id, interval)`, and a reference date. It generates seven dates, applies 06:00–20:00 operating hours, and rejects conflicting overlapping booking/block records. E2 expects naive venue-local datetimes, minute precision, and same-date court bookings.

Equipment models in [`equipment_models.py`](backend/app/e2_allocation/equipment_models.py) use UUIDs and strict integer quantities: inventory quantity is nonnegative; requested and reserved quantities are positive; duplicate equipment IDs in one request are rejected. An equipment reservation has `equipment_id`, `booking_id`, interval, and quantity, and must be naive and single-date. E2 calculates availability from inventory and overlapping in-memory reservations; no mutable “available quantity” is maintained.

`allocate_combined()` stages court and equipment cache changes together. That is atomic only with respect to the in-process caches. `cancel_combined()` also updates cache state and may return `repeated=True` for a previously cancelled in-memory record. E4/E3 must use persistent booking status to enforce the business rule that repeated cancellation is rejected.

**Important limitations and conflicts:**

- E2 has no database, transaction, lock, authentication, or HTTP responsibilities.
- `refresh_equipment_reservations()` replaces the entire reservation snapshot, not a partial subset. Inventory entries must already exist for all equipment in that snapshot.
- E2 does not expose a public atomic full inventory-and-court snapshot replacement. `generate_availability()` sets its generated court/date entries but does not clear unrelated stale entries.
- `block_update.py` permits a block to overwrite BOOKED cache intervals, while availability generation rejects overlapping persisted booking/block records. Admin block-out is outside the current student scope; this mismatch needs a future policy before block overrides are persisted.
- The legacy `AllocationInterface` methods `generate_calendar()` and `process_post_commit_split_merge()` are compatibility methods, not the normal E2 allocation workflow. `generate_calendar()` returns the supplied interval and `process_post_commit_split_merge()` returns an empty list.

### E3 — Persistence

**MISSING:** E3 currently has no mapped tables or durable repository operations.

- [`backend/app/e3_persistence/models.py`](backend/app/e3_persistence/models.py) contains only an empty declarative `Base`.
- [`backend/app/e3_persistence/repository.py`](backend/app/e3_persistence/repository.py) declares `PersistenceRepository.execute()`, which raises `NotImplementedError`.
- [`backend/app/e3_persistence/session.py`](backend/app/e3_persistence/session.py) lazily creates an async SQLAlchemy engine using `DATABASE_URL`, enables `pool_pre_ping`, creates an `async_sessionmaker(expire_on_commit=False)`, and provides `transaction_session()` using `session.begin()`. No concrete repository calls it.
- No Alembic configuration, migration files, E3 schema, model relationships, booking operations, slot claims, equipment operations, cancellation, or snapshot reads were found.
- [`backend/tests/e3/test_import.py`](backend/tests/e3/test_import.py) only checks imports. It does not establish database behavior.

The root `pyproject.toml` does not declare Alembic. The requirements in this phase select Alembic, so its dependency/configuration and an initial migration are future work, not existing capabilities.

### E4 — Communication

**MISSING:** [`backend/app/e4_communication/routes.py`](backend/app/e4_communication/routes.py) contains only `GET /api/health`. [`coordinator.py`](backend/app/e4_communication/coordinator.py) accepts optional allocation, concurrency, and persistence dependencies, but `coordinate_booking()` raises `NotImplementedError`. No student authentication, request schemas, booking orchestration, cancellation, history, or startup wiring exists.

### Shared contracts, app, and frontend

[`backend/app/contracts/booking.py`](backend/app/contracts/booking.py) defines:

- `TimeInterval(start: datetime, end: datetime)`: rejects end <= start and seconds/microseconds, but does not reject timezone-aware or cross-date intervals.
- `BookingRequest(venue_id: UUID, equipment_id: UUID | None, interval: TimeInterval)`: no `court_id`, equipment quantities/list, or user ID.
- `BookingResponse(booking_id: UUID, status: str, interval: TimeInterval)`: status is an unrestricted string.
- `LockToken(token: UUID, interval: TimeInterval)`, `ValidationResult`, and `TransactionResult`.

The shared interfaces are legacy abstractions. [`backend/app/main.py`](backend/app/main.py) configures FastAPI/CORS and includes the E4 router. [`backend/app/config.py`](backend/app/config.py) reads environment settings and has a `list[str]` setting for CORS origins. The checked-in `.env.example` uses comma-separated CORS values rather than JSON list syntax; this example is incompatible with Pydantic Settings' normal parsing of list environment variables. The actual `.env` was not inspected.

The frontend [`frontend/src/main.jsx`](frontend/src/main.jsx) requests only `/api/health` and displays placeholder cards. It has no booking UI or API client.

## 3. Architecture and responsibility boundaries

| Engine | Owns | Must not own |
|---|---|---|
| E1 | Temporary process-local lock registry, wait queue, token lifecycle | Booking persistence, final availability truth, equipment quantity integrity, HTTP responses |
| E2 | Derived court timeline, interval validation, in-memory equipment inventory/reservation calculations and cache operations | Durable records, database transactions, authentication, HTTP |
| E3 | MySQL models/migrations, repositories, ACID transactions, authoritative booking/claim/allocation state, durable snapshot reads | HTTP routes, password verification policy, a second availability timeline algorithm |
| E4 | Authentication, API schemas/routes, coordination, error mapping, lifecycle/startup, student-facing response | Duplicating E1 locking or E2 allocation algorithms; direct SQL in routes |
| Frontend | Student experience and HTTP requests to E4 | Direct E1/E2/E3 calls or authoritative conflict decisions |

E1 and E2 are both in-memory and worker-local. E3 must protect correctness across workers and restarts. E2 availability is a projection of durable E3 records, never the source of truth.

## 4. Shared data contracts

### 4.1 Proposed student booking request and response

The following is a **PROPOSED API contract**, not an existing model. It uses timezone-aware request timestamps so the conversion boundary is explicit:

```python
class EquipmentLine(BaseModel):
    equipment_id: UUID
    quantity: PositiveInt

class BookingCreateRequest(BaseModel):
    court_id: UUID
    starts_at: datetime  # must include a UTC offset
    ends_at: datetime    # must include a UTC offset
    equipment: list[EquipmentLine] = Field(default_factory=list)

class BookingResponse(BaseModel):
    booking_id: UUID
    court_id: UUID
    starts_at: datetime  # returned in Asia/Kolkata
    ends_at: datetime    # returned in Asia/Kolkata
    status: Literal["BOOKED", "CANCELLED"]
    equipment: list[EquipmentLine]
```

The authenticated `user_id` is not accepted from the client. E4 obtains it from its authenticated principal and supplies it to E3. E4 generates one booking UUID and passes that same value to E2 and E3.

At the E4 request boundary, require timezone-aware datetimes, convert them with `ZoneInfo("Asia/Kolkata")`, verify the interval is within one venue-local calendar date and has not started, then remove `tzinfo` to construct the naive E2 `TimeInterval`. Reject malformed/naive client timestamps rather than guessing a timezone. Responses should be serialized with the `Asia/Kolkata` offset. E3 should persist the normalized venue-local date and times consistently; no component should mix UTC instants and naive local values without an explicit conversion.

The requirement could instead define `booking_date` and local `start_time`/`end_time` as wall-clock fields. That is a valid alternative, but the team must choose one external contract. The design above chooses aware timestamps to make the conversion contract testable.

### 4.2 Cancellation and identity

**PROPOSED:** Cancellation uses the booking ID in the path and no client-supplied user ID or interval:

```text
POST /api/bookings/{booking_id}/cancellation
```

E4 passes the authenticated `user_id` to E3. E3 obtains the court/date/interval from the stored booking and rechecks ownership, status, and start-time eligibility inside its transaction. The exact response schema and HTTP status codes remain proposed in Section 13.

### 4.3 E1 lock contract

**CONFIRMED method:** `await e1.acquire_with_wait(interval, str(court_id), timeout=3.0) -> LockToken`.

The logical identity is court + interval. E1 represents the court as `resource_id` and the date/start/end as the `TimeInterval`; it does not use exact tuple equality. Same-court, same-start-date overlapping intervals conflict; adjacent half-open intervals do not.

Possible errors: `LockWaitTimeoutError`, `LockQueueFullError`; fail-fast `acquire()` may raise `LockConflictError`. `release(token)` may raise `InvalidLockTokenError`. E4 releases only after successful acquisition and must do so in `finally`.

### 4.4 E2/E3 synchronization contract

E2 currently consumes:

- Court: active court UUIDs; `CommittedBooking(booking_id, court_id, interval)`; `EffectiveCourtBlock(block_id, court_id, interval)`; reference date.
- Equipment: `EquipmentInventory(equipment_id, total_quantity)` and `EquipmentReservation(equipment_id, booking_id, interval, quantity)`.

**PROPOSED E3 snapshot:** a consistent, complete snapshot containing active courts; `BOOKED` bookings and effective blocks relevant to E2's court window; every inventory row E2 tracks; and the complete active equipment reservation snapshot for the declared E2 cache scope. Exclude `CANCELLED` bookings and their active claims. Include a snapshot version/read timestamp for diagnostics if useful.

The snapshot scope must be explicit. Because `refresh_equipment_reservations()` replaces the whole equipment reservation cache, E3 must not send a partial list. A safe initial project approach is to refresh the complete set of reservations in E2's defined booking horizon and make that horizon part of the E2 snapshot contract. Alternatively, expose an E2 public full-snapshot replacement API. Existing E2 does not define this horizon/full replacement for all caches.

### 4.5 Contract mismatches to resolve

| Existing | Required/proposed | Impact |
|---|---|---|
| `venue_id` | `court_id` | Update shared request and callers; affects E4 and contract tests. |
| One optional `equipment_id` | A list of equipment UUID/positive-quantity lines | Supports optional, multiple item types and quantities. |
| No user ID in client request | Authenticated UUID supplied internally by E4 | Prevents trusting client identity; requires E4 auth and E3 FK. |
| Unrestricted `status: str` | `BOOKED`/`CANCELLED` enum/literal | Gives API and DB a closed status contract. |
| `ConcurrencyLockInterface` lacks wait method | E4 needs `acquire_with_wait` | Update shared typing or explicitly type E4 dependency as concrete E1 service. |
| Legacy `AllocationInterface` | E2 public sync allocation APIs | E4 must use the E2 APIs listed in Section 5 rather than placeholder semantics. |

## 5. Method-level integration contracts

The E1/E2 methods in this table exist now. E3 methods are explicit proposals because no repository operations currently exist.

| Caller → receiver | Method / signature | Return and failure behavior |
|---|---|---|
| E4 → E2 | `generate_availability(active_court_ids: Iterable[UUID], bookings: Iterable[CommittedBooking], blocks: Iterable[EffectiveCourtBlock], reference_date: date) -> None` | Mutates E2 court cache. Can reject invalid, overlapping, inactive-court or timezone-incompatible input. |
| E4 → E2 | `check_court_availability(court_id: UUID, booking_date: date, interval: TimeInterval, current_datetime: datetime | None = None) -> ValidationResult` | `valid/errors`; does not mutate court cache. Requires preloaded court/date availability. |
| E4 → E2 | `get_equipment_availability(equipment_id: UUID, interval: TimeInterval, requested_quantity: int = 1) -> EquipmentAvailabilityResult` | `valid`, availability segments, shortages/errors; query does not mutate reservations. Call once per requested item for preflight. |
| E4 → E2 | `allocate_combined(court_id: UUID, booking_date: date, interval: TimeInterval, booking_id: UUID, items: tuple[EquipmentRequestLine, ...] = (), current_datetime: datetime | None = None) -> CombinedAllocationResult` | Mutates court/equipment caches only when successful; result includes `succeeded`, `booking_id`, allocation flags/items, shortages/errors. |
| E4 → E2 | `cancel_combined(booking_id: UUID, court_id: UUID | None = None, booking_date: date | None = None) -> CombinedCancellationResult` | Mutates caches; can report `repeated=True`. Do not use this alone to authorize persistent cancellation. |
| E4 → E1 | `await acquire_with_wait(interval: TimeInterval, resource_id: str, timeout: float = 3.0) -> LockToken` | Existing concrete method; may raise wait timeout or queue-full errors. Lock identity uses court ID string plus overlap interval. |
| E4 → E1 | `await release(token: LockToken) -> None` | Existing concrete method; raises `InvalidLockTokenError` for invalid/repeated token. Use in `finally`. |
| E4 → E3 | **PROPOSED** `await load_allocation_snapshot(reference_date: date, horizon_days: int = 7) -> AllocationSnapshot` | Add a consistent database read for active courts, booked intervals, effective blocks, equipment inventory, and complete active equipment reservations in the agreed cache scope. |
| E4 → E3 | **PROPOSED** `await create_booking(command: CreateBookingCommand) -> PersistedBooking` | One transaction performs final checks and inserts booking, slot claims, and allocations. Raises typed conflict/validation/persistence errors; transaction rolls back on failure. |
| E4 → E3 | **PROPOSED** `await cancel_booking(booking_id: UUID, user_id: UUID, now: datetime) -> PersistedBooking` | One transaction locks and rechecks booking, marks it `CANCELLED`, and releases claims; raises not-found, ownership, already-cancelled, started, or persistence errors. |
| E4 → E3 | **PROPOSED** `await get_booking_history(user_id: UUID) -> list[BookingHistoryRecord]` | Owner-filtered history including `CANCELLED` bookings and their equipment lines. |
| E4 → E4 coordinator | Existing `coordinate_booking(request: BookingRequest) -> BookingResponse` | Currently raises `NotImplementedError`; request type itself must be revised as agreed. |

### E2 snapshot replacement needed

`refresh_equipment_reservations()` exists and atomically replaces the whole reservation snapshot, but it does not replace inventory. `generate_availability()` writes generated date/court entries but does not clear entries for removed courts or unrelated dates. Directly mutating `e2.court_cache` and `e2.equipment_cache` is not the documented normal integration API.

**PROPOSED E2 change:** add a public operation that atomically replaces a complete court-and-equipment snapshot, or provide an E4-controlled way to build a fresh `AllocationService` and swap it into use only after successful hydration. A proposed shape is:

```python
def replace_snapshot(
    active_court_ids: Iterable[UUID],
    bookings: Iterable[CommittedBooking],
    blocks: Iterable[EffectiveCourtBlock],
    inventories: Iterable[EquipmentInventory],
    reservations: Iterable[EquipmentReservation],
    reference_date: date,
) -> None:
    ...
```

This signature is illustrative and **not implemented**. It needs E2 owner review, atomic failure semantics, and tests. Do not have E4 call E2 private cache methods.

## 6. Booking sequence

1. E4 authenticates the student, gets `user_id` from the authenticated principal,
   validates the request, and generates a booking UUID.
2. E2 checks court availability and validates every requested equipment line
   before E1 acquisition.
3. If shortages exist and no decision is supplied, E4 returns
   `EQUIPMENT_DECISION_REQUIRED` with all shortage quantities and the two
   permitted choices, `CONTINUE_WITHOUT_EQUIPMENT` and `CANCEL_REQUEST`. It
   does not create a booking or booking status.
4. `CANCEL_REQUEST` returns a typed result stating no booking was created. It
   does not acquire E1, persist in E3, or publish a booking into E2.
5. For `CONTINUE_WITHOUT_EQUIPMENT`, E4 loads a fresh authoritative snapshot
   from E3 and builds a temporary E2 view. It repeats court and all-equipment
   checks before E1. It rejects an unavailable court; otherwise it retains
   available equipment lines at their original quantities and omits only
   unavailable lines.
6. E4 acquires `await e1.acquire_with_wait(interval, str(court_id),
   timeout=...)`. No database transaction is open while waiting.
7. E3 begins one InnoDB transaction, verifies user/court eligibility, locks
   the final equipment inventory rows in stable order, rechecks overlapping
   active allocations, inserts the `BOOKED` row, minute claims, and retained
   allocation rows, then commits. Any failure rolls back the transaction.
8. Only after E3 commits does E4 refresh the shared E2 cache from authoritative
   E3 state. If refresh fails, E4 reports that the booking committed and
   invalidates the stale snapshot for recovery.
9. E4 returns the booking response and releases the E1 token in `finally` on
   every path after acquisition.

```mermaid
sequenceDiagram
    actor Student
    participant UI as React frontend
    participant E4 as FastAPI / coordinator
    participant E2 as AllocationService
    participant E1 as ConcurrencyService
    participant E3 as Repository
    participant DB as MySQL InnoDB

    Student->>UI: Submit court, interval, equipment
    UI->>E4: POST booking request
    E4->>E4: Authenticate; normalize Asia/Kolkata; generate booking UUID
    E4->>E2: Initial court check and all-equipment validation
    E2-->>E4: Court result and complete shortage list
    alt Shortage and no decision
        E4-->>UI: EQUIPMENT_DECISION_REQUIRED, shortages, permitted choices
        break No lock or booking is created
    else CANCEL_REQUEST
        E4-->>UI: Request cancelled; no booking created
        break No lock or booking is created
    else Proceed to booking
        opt CONTINUE_WITHOUT_EQUIPMENT
            E4->>E3: Load fresh authoritative allocation snapshot
            E3->>DB: Consistent read
            DB-->>E3: Courts, bookings, blocks, inventory, allocations
            E3-->>E4: Snapshot
            E4->>E2: Build temporary view; final court/equipment checks
        end
        Note over E4,E2: If no shortage, initial checks are final checks
        E4->>E1: acquire_with_wait(interval, str(court_id))
        E1-->>E4: LockToken
        E4->>E3: create_booking(final equipment list)
        E3->>DB: Lock inventory; check claims/quantities; insert booking + claims + allocations
        DB-->>E3: Commit or rollback
        E3-->>E4: Persisted result or typed failure
        E4->>E3: Load committed snapshot
        E3->>DB: Consistent read
        DB-->>E3: Courts, bookings, blocks, inventory, allocations
        E3-->>E4: Snapshot
        E4->>E2: Publish refreshed derived state after commit
        E4->>E1: release(token) in finally
        E4-->>UI: Booking response
    end
    UI-->>Student: Show persisted booking and refreshed availability
```

E2 business availability checks do not run after E1 acquisition. The fresh
pre-lock view used for the continue choice is temporary; the shared E2 cache
is refreshed only after E3 commits. E3's database constraints and locked
capacity revalidation remain authoritative against cross-worker races.

## 7. Cancellation sequence

1. E4 authenticates the student. It reads booking metadata from E3 to obtain the court ID and interval needed for E1; it must not trust a client-supplied interval or user ID.
2. E4 acquires the E1 lock for that court and stored interval.
3. E3 starts a transaction and locks the booking row. It rechecks owner, `BOOKED` status, and that the interval has not started using the agreed venue-local clock.
4. E3 marks the booking `CANCELLED` and removes all associated `slot_claim` rows in the same transaction. Equipment allocation history is retained; active equipment consumption is derived by joining allocations to `BOOKED` records. Thus the status transition releases inventory atomically without deleting the lines needed for history.
5. E3 commits. If any write fails, it rolls back the status and claim changes together.
6. E4 loads a fresh authoritative snapshot and refreshes/rebuilds E2. E2 no longer treats the booking or its equipment as active.
7. E4 returns the committed cancellation result. A second attempt is rejected based on persistent status, even if E2's in-memory tombstone is absent or says `repeated=True`.
8. E4 releases E1 in `finally`. The temporary lock is not retained as a permanent booking reservation.

```mermaid
sequenceDiagram
    actor Student
    participant UI as React frontend
    participant E4 as FastAPI / coordinator
    participant E1 as ConcurrencyService
    participant E3 as Repository
    participant DB as MySQL InnoDB
    participant E2 as AllocationService

    Student->>UI: Cancel booking
    UI->>E4: POST cancellation for booking ID
    E4->>E4: Authenticate; obtain principal user UUID
    E4->>E3: Read booking metadata
    E3->>DB: Read owner, court, interval
    DB-->>E3: Stored booking
    E3-->>E4: Court and interval
    E4->>E1: acquire_with_wait(interval, str(court_id))
    E1-->>E4: LockToken
    E4->>E3: cancel_booking(booking_id, user_id, now)
    E3->>DB: Begin; lock booking; recheck owner/status/start time
    E3->>DB: Mark CANCELLED; delete slot claims; commit
    DB-->>E3: Commit or rollback
    E3-->>E4: Persisted cancellation or typed failure
    E4->>E3: Load committed allocation snapshot
    E3-->>E4: Current active records
    E4->>E2: Refresh/rebuild cache
    E4-->>UI: Cancellation result
    E4->>E1: release(token) in finally
    UI-->>Student: Refresh history and availability
```

## 8. Database design

**CONFIRMED current state:** no E3 tables exist. The following is a proposed MySQL 8/InnoDB schema, not DDL that has been run. Use Alembic migrations as required by the agreed decision; do not make `Base.metadata.create_all()` the production schema strategy.

### UUID and common conventions

**PROPOSED:** use SQLAlchemy `Uuid(as_uuid=True)` consistently. On MySQL, verify generated migration DDL and FK column types match; SQLAlchemy's non-native UUID representation is typically `CHAR(32)` hexadecimal form. The users table, booking table, court table, and every referencing UUID column must use the same physical representation and collation/length. Store venue-local booking `DATE`/`TIME` after E4 normalization; use aware timestamps only at the API boundary.

All tables should use InnoDB. Use database-generated or application-managed timestamps consistently; do not mix venue-local booking times and UTC audit timestamps without documenting the conversion.

### Proposed tables

| Table | Proposed columns and constraints | Purpose / relationships |
|---|---|---|
| `users` (**E3-owned**) | `user_id UUID PK`; `usn VARCHAR(50) NOT NULL UNIQUE`; `password_hash VARCHAR(255) NOT NULL`; `college_email VARCHAR(254) NOT NULL UNIQUE`; `phone_number VARCHAR(32) NOT NULL`; `year_of_admission SMALLINT NOT NULL`; `gender VARCHAR(32) NOT NULL`; `branch VARCHAR(100) NOT NULL`; `created_at DATETIME(6) NOT NULL`; `updated_at DATETIME(6) NOT NULL`; optionally an agreed `is_active BOOLEAN NOT NULL`. | E3 owns the physical table, SQLAlchemy model, and student persistence. E4 owns password verification, authentication, and student-facing APIs. The exact enum/field validation and whether `is_active` is required need E4 agreement. |
| `sport` | `sport_id UUID PK`; `name VARCHAR(100) NOT NULL UNIQUE`; optional `description VARCHAR(500)`; `is_active BOOLEAN NOT NULL`; `created_at DATETIME(6) NOT NULL`; `updated_at DATETIME(6) NOT NULL`. | Catalog of sports; one sport has many courts. |
| `court` | `court_id UUID PK`; `sport_id UUID NOT NULL FK sport`; `name VARCHAR(100) NOT NULL`; `is_active BOOLEAN NOT NULL`; `created_at DATETIME(6) NOT NULL`; `updated_at DATETIME(6) NOT NULL`; `UNIQUE(sport_id, name)`. | Individually bookable court. Index `(sport_id, is_active)` for listing. |
| `equipment_item` | `equipment_id UUID PK`; `name VARCHAR(100) NOT NULL UNIQUE`; optional `description VARCHAR(500)`; `total_quantity INT NOT NULL CHECK(total_quantity >= 0)`; `is_active BOOLEAN NOT NULL`; `created_at DATETIME(6) NOT NULL`; `updated_at DATETIME(6) NOT NULL`. | Durable total inventory. Do not store mutable available quantity; calculate from active allocations. |
| `booking` | `booking_id UUID PK`; `user_id UUID NOT NULL FK users`; `court_id UUID NOT NULL FK court`; `booking_date DATE NOT NULL`; `start_time TIME NOT NULL`; `end_time TIME NOT NULL`; `status VARCHAR(10) NOT NULL CHECK status IN ('BOOKED','CANCELLED')`; `created_at DATETIME(6) NOT NULL`; nullable `cancelled_at DATETIME(6)`; `CHECK(start_time < end_time)`; operating-hours and minute-alignment checks where supported. Add `UNIQUE(booking_id, court_id, booking_date)` as a candidate key for the slot-claim composite FK. | Durable booking and history. `user_id` is the internal authenticated UUID. Index `(user_id, booking_date, created_at)` for history and `(court_id, booking_date, status)` for availability. `ON DELETE RESTRICT` is appropriate for historical references; cancellation updates, it does not delete the booking. |
| `slot_claim` | `court_id UUID NOT NULL`; `slot_date DATE NOT NULL`; `minute_index SMALLINT NOT NULL CHECK(minute_index BETWEEN 0 AND 1439)`; `booking_id UUID NOT NULL`; `PRIMARY KEY(court_id, slot_date, minute_index)`; composite FK `(booking_id, court_id, slot_date)` → booking `(booking_id, court_id, booking_date)`; index on `booking_id`. | One row per occupied minute. A 10:00–11:00 interval claims 600 through 659; end minute is excluded. The PK prevents two bookings claiming the same court minute. Delete a booking's claims during cancellation, in the same transaction as the status update. |
| `equipment_allocation` | `allocation_id UUID PK` (or agreed composite key); `booking_id UUID NOT NULL FK booking`; `equipment_id UUID NOT NULL FK equipment_item`; `quantity INT NOT NULL CHECK(quantity > 0)`; `created_at DATETIME(6) NOT NULL`; `UNIQUE(booking_id, equipment_id)`; indexes `(equipment_id, booking_id)` and `booking_id`. | Durable equipment lines for history. Retain them after cancellation. Count only allocations whose booking is `BOOKED` when computing active consumption; changing booking status therefore releases inventory atomically. |
| `block_out` | `block_id UUID PK`; `court_id UUID NOT NULL FK court`; `starts_at DATETIME(6) NOT NULL`; `ends_at DATETIME(6) NOT NULL`; nullable `created_by UUID FK users`; optional `reason VARCHAR(500)`; `is_active BOOLEAN NOT NULL`; `created_at DATETIME(6) NOT NULL`; nullable `cancelled_at DATETIME(6)`; `CHECK(starts_at < ends_at)`; index `(court_id, is_active, starts_at, ends_at)`. | Persisted effective court blocks for E2 hydration. Admin creation/override workflows are postponed. Current E2 generation rejects overlapping block/booking records, so define a conflict policy before allowing an overlap. |

E3 owns and migrates the physical `users` table and its model. E4 uses E3 student-persistence operations for registration and lookup but owns the authentication and API behavior. Keep the UUID representation consistent across user and E3 foreign-key columns.

### Slot claim generation

For a same-date interval `[start, end)`, generate one integer minute for each minute boundary in `[start, end)`:

```text
minute_index = hour * 60 + minute
for minute in range(start_minute, end_minute):
    insert (court_id, booking_date, minute, booking_id)
```

The expected E2 rules constrain a student booking to one date and 06:00–20:00, so the current student workflow cannot end at midnight. If those rules change, midnight/date rollover must be designed explicitly. The database key protects against concurrent inserts even when E1 locks are isolated in different processes.

### Equipment quantity consistency

Inside the booking transaction, select each requested `equipment_item` row `FOR UPDATE`, ordered by a stable `equipment_id` order. Confirm each exists and is active, then calculate the maximum concurrent sum of active overlapping allocations for the requested interval. Reject if `existing_active_quantity + requested_quantity > total_quantity`. Multiple request lines must have unique equipment IDs, as E2's request model requires.

This row-lock strategy serializes transactions for the same inventory rows. The booking status and allocation rows must be queried consistently in the transaction. MySQL isolation and lock behavior should be covered by integration tests; do not treat E2's process-local inventory cache as the final check.

## 9. ACID and concurrency guarantees

- **Atomicity:** One InnoDB transaction inserts the booking, all slot claims, and all equipment allocations. Cancellation changes status and releases claims together. Any DB error rolls back all uncommitted changes.
- **Consistency:** PK/FK/unique/check constraints enforce valid identifiers, positive quantities, valid status, and one claim per court minute. E2 validates intervals; E3 independently validates persistent invariants.
- **Isolation:** E1 serializes overlapping same-court work inside one worker. E3 slot-claim uniqueness protects court intervals across workers. `SELECT ... FOR UPDATE` on inventory rows protects shared equipment quantities. Process-local caches are not an isolation boundary.
- **Durability:** A successful InnoDB commit is authoritative. E2 cache and browser state are derived and can be rebuilt.
- **Deadlock reduction:** Lock multiple equipment rows in one deterministic order, keep transactions short, and handle deadlock/serialization errors by rolling back and returning a safe retry/conflict result. Never wait in E1 while holding a DB transaction.
- **Isolation limitation:** E1's resource comparison is by court ID, start date, and interval overlap; it does not coordinate equipment across different courts or multiple workers. Database checks remain mandatory.

## 10. Cache synchronization and recovery

### Startup

**PROPOSED:** E4 lifespan initializes its worker-scoped E1 and E2 services, calls E3 for one consistent allocation snapshot, and populates E2 before marking allocation-dependent endpoints ready. Snapshot contents include active courts, `BOOKED` bookings in the court window, effective non-conflicting blocks, inventory, and complete active equipment allocations in E2's declared scope.

`generate_availability()` covers seven dates but does not clear all stale court entries. `refresh_equipment_reservations()` replaces all reservation state and preserves inventory but does not replace inventory. Therefore startup should either:

1. construct a fresh E2 service/cache, populate all catalog and reservation data, validate it, and publish the service only after success; or
2. add a public atomic full-snapshot E2 API with explicit cache scope.

The second option better preserves one E2 service instance and avoids E4 reaching into private caches. The E2 owner must review the API and failure semantics.

### After a booking/cancellation

After the E3 commit, E4 requests a new consistent E3 snapshot and replaces E2's derived state. Do not send only the changed booking to `refresh_equipment_reservations()`, because its documented behavior replaces the entire equipment reservation set.

### Cache refresh failure after DB commit

The database remains committed and authoritative; do not report that the booking/cancellation was rolled back. E4 should:

1. mark the worker's allocation cache as not ready/degraded;
2. prevent stale E2 data from authorizing new booking/cancellation operations and avoid serving it as current availability;
3. retry a full E3 snapshot and rebuild E2;
4. record a safe diagnostic without logging credentials or sensitive data;
5. return a response that makes the persistence outcome clear and allows the client to refetch the booking.

The exact response policy (for example, successful persisted booking plus a synchronization warning versus a service-unavailable result with a retryable status) must be agreed. A response must never imply “not booked” when MySQL committed the booking.

## 11. Cancellation and rebooking lifecycle

E1's token is temporary synchronization for the duration of a request; it is not a court reservation. After a successful booking, E4 releases the E1 lock. The durable `BOOKED` row and minute claims then prevent another booking. Do not hold an E1 lock for the duration of a future booking.

On cancellation, E3 changes the booking status to `CANCELLED` and deletes its slot claims in one transaction. Equipment history remains in `equipment_allocation`; active inventory queries join allocations to `booking.status = 'BOOKED'`, so the status change releases quantity. E2 refreshes from E3 and shows the interval/quantity as available if otherwise free. E1 releases its temporary cancellation lock, allowing a new request to acquire it. A new booking can claim the same minute PKs after the old claims have been deleted, provided its interval is still in the future and all E2/E3 checks pass.

Repeated cancellation is rejected by E3 using the persisted status, not E2's optional in-memory tombstone. A cancellation after start is rejected after the transaction rechecks the stored interval and current venue-local time.

## 12. Failure and rollback matrix

| Failure point | Database state | E1 lock state | E2 cache state | Required recovery | Student-facing result |
|---|---|---|---|---|---|
| Request/time validation | Unchanged | Not acquired | Unchanged | None | Validation error |
| Initial E2 check | Unchanged | Not acquired | Unchanged | None | Conflict/shortage response |
| E1 timeout or full queue | Unchanged | No token granted | Unchanged | None | Conflict/timeout/service-busy response |
| Post-lock refresh/revalidation | Unchanged | Acquired, then released in `finally` | Rebuilt from latest DB snapshot | Report stale availability as conflict | Updated availability/conflict |
| Court claim duplicate | Transaction rolled back | Acquired, then released | Rebuild if provisional E2 allocation was applied | Treat DB as final conflict boundary | Conflict |
| Equipment shortage/row-lock validation | Transaction rolled back | Acquired, then released | Restore/rebuild from DB | No partial court/equipment booking | Quantity shortage |
| Booking, claim, or allocation insert fails | All transaction writes rolled back | Acquired, then released | Rebuild if E2 had provisional mutation | Preserve original DB error for logs; map safely | Failed booking |
| E3 commits, E2 refresh fails | Booking committed | Keep lock until degraded state is recorded/rebuild attempted; then release | Possibly stale; mark not ready and fail closed | Retry full snapshot; prevent stale cache authorization | Clearly report booking is committed; require refetch/retry synchronization |
| Response/browser update fails | Booking committed | Already released | E2 may be current | Client refetches history/availability | No database rollback |
| Cancellation ownership/status/start check fails | Unchanged | Acquired, then released | Rebuild only if necessary | No status/claim change | Forbidden/not found/already cancelled/started |
| Cancellation claim release or status write fails | Transaction rolled back; original booking stays booked | Acquired, then released | Rebuild if necessary | Keep original state; no partial release | Cancellation failed |
| Cancellation commits, E2 refresh fails | Booking remains cancelled; claims released | Release after degraded state recorded | Stale; mark not ready | Retry full snapshot; block stale-cache writes | Clearly report cancellation committed; refetch |
| Unexpected exception | Roll back any open DB transaction | Release acquired token in `finally` | Reconcile from DB if state may have changed | Log diagnostic, do not swallow original failure | Generic safe server error |

Cache and browser state cannot be rolled back by a MySQL transaction. Recovery is reconciliation from committed database data.

## 13. API and frontend integration

All endpoints below are **PROPOSED**; only `GET /api/health` currently exists.

| Capability | Proposed endpoint | Notes |
|---|---|---|
| Register | `POST /api/auth/register` | USN, password, confirmation, college email, phone, admission year, gender, branch. Store only a password hash. No OTP. |
| Login/logout/current student | `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` | Authentication/session mechanism remains an implementation decision; never accept a trusted user UUID from the client. |
| Sports/courts | `GET /api/sports`, `GET /api/sports/{sport_id}/courts`, `GET /api/courts/{court_id}` | E3 reads catalog; only active/bookable courts offered. |
| Availability | `GET /api/courts/{court_id}/availability?date=...` | E3 snapshot feeds E2; response is derived and can become stale before confirmation. |
| Equipment availability | `POST /api/equipment/availability` | Proposed body can contain interval plus equipment lines so E2 can return per-item quantities/shortages. |
| Create booking | `POST /api/bookings` | Authenticated identity from E4; E4 generates booking UUID; E1/E2/E3 sequence in Section 6. |
| Booking details/history | `GET /api/bookings/{booking_id}`, `GET /api/me/bookings` | Always enforce ownership. Include cancelled records and retained equipment lines in history. |
| Cancel booking | `POST /api/bookings/{booking_id}/cancellation` | Persistent ownership/status/start checks inside E3 transaction. |
| Readiness | `GET /api/ready` | Proposed operational endpoint; indicate whether required DB and E2 snapshot are ready without exposing credentials. |

Use separate Pydantic API schemas and SQLAlchemy models. Return consistent validation, unauthorized, forbidden, not-found, conflict, unavailable, and unexpected-error responses. Do not expose password hashes or stack traces.

The frontend should submit requests only to E4, show loading/error states, prevent accidental duplicate submissions, and display a successful confirmation only when E4 reports the persisted booking. After booking/cancellation, refresh history and availability from E4. A browser error must not undo a committed database operation.

## 14. Implementation roadmap

No phase below is implemented by this design document.

| Phase | Files/areas | Required work | Dependencies and tests | Outcome |
|---|---|---|---|---|
| 1. Approve contracts | `backend/app/contracts/booking.py`, `interfaces.py`, `backend/app/e2_allocation/INTEGRATION_GUIDE.md`, `backend/app/e1_concurrency/INTEGRATION.md`, shared docs | Confirm request/response, timezone normalization, user identity, booking ID, lock API, E2 snapshot scope and error mapping. Update interfaces only with owner agreement. | E1/E2 method tests plus contract tests. | Stable interfaces before persistence/orchestration. |
| 2. E3 models/migrations | `backend/app/e3_persistence/models.py`; E3-owned `User` model; Alembic configuration/environment and migration files | Maintain approved models, constraints, indexes, relationships, and forward revisions; keep E3 user persistence separate from E4 authentication behavior. | Migration generation/review; MySQL schema smoke test on dedicated test DB. | Versioned schema with agreed FK types. |
| 3. E3 repositories | `repository.py`, `session.py`, new E3 input/result/error modules | Implement consistent snapshot read, booking transaction, cancellation transaction, history/details, typed errors, engine lifecycle. | Unit mapping tests and MySQL tests for insert, FKs, duplicate slot claims, rollback, equipment row locks, cancellation/history. | Durable operations and authoritative E2 inputs. |
| 4. E2 snapshot integration | `service.py`, cache modules, public interface tests | Add/approve atomic full-snapshot replacement or a controlled fresh-instance swap. Define court/equipment cache horizon and refresh failure behavior. Preserve current E2 validation/allocation behavior. | Tests for full refresh, removed courts/inventory, complete equipment snapshot, failed refresh preserving prior state. | Safe startup and post-commit hydration. |
| 5. E4 authentication and API | `e4_communication/` new auth/security/schema/service modules; `coordinator.py`, `routes.py`, `main.py`, `config.py` | Add registration/login/session, protected endpoints, coordinator, dependency wiring, lifespan hydration, exception mapping. | Route tests, auth/ownership tests, E1/E2/E3 orchestration tests; no real user secrets. | Student-facing backend API. |
| 6. Frontend | `frontend/src/` | Implement registration/login, sport/court discovery, availability, equipment selection, booking, history, cancellation through E4. | Component/API tests if tooling is approved; Vite production build. | Working student journey. |
| 7. End-to-end verification/docs | `backend/tests/integration/`, new MySQL tests, project docs | Validate simultaneous bookings, rollback, cancellation/rebooking, restarts, cache failures, access control; document setup and APIs. | Dedicated MySQL test database; never production DB. | Demonstrable, persistent, tested application. |

Keep admin UI/workflows, OTP, and payment out of the student implementation. Preserve E2 block compatibility without exposing admin operations.

## 15. Unresolved questions and technical conflicts

1. **E2 cache scope/full replacement:** What exact date horizon does E2 retain? `refresh_equipment_reservations()` replaces the entire reservation cache, while E2 has no public full inventory/court snapshot replacement. Decide whether to add a public atomic snapshot API or use fresh E2 service instances and atomic swaps.
2. **E2 provisional mutation ordering:** E2's integration guide says allocate combined and then persist; the agreed workflow requires E3 commit followed by E2 synchronization from committed state. Decide whether to stage E2 allocation pre-commit and rebuild on DB failure, or perform E2's cache mutation only after DB commit. In either case, final persistent truth is E3 and cache failure must fail closed.
3. **E1/E2 order in existing documentation:** E1 guide says E2 validation before E1 acquisition; E2 guide begins with E1 acquisition then availability checks. The agreed flow includes initial validation and post-lock revalidation; update both guides to match.
4. **Shared type for bounded wait:** E1 implements `acquire_with_wait`, but `ConcurrencyLockInterface` does not. Decide whether to add it to the shared ABC (and tests) or type E4 against the concrete E1 service.
5. **Current E2 lacks catalog validation:** E2 can report missing court/date cache and missing inventory, but does not query whether a court/equipment item exists or is active. E4/E3 must perform catalog eligibility checks; determine whether E2's requirements should be expanded.
6. **UUID SQL representation:** No current E3/E4 models establish the physical format. Confirm the Alembic-generated users and E3 FK types match exactly (for example, SQLAlchemy UUID mapped consistently to `CHAR(32)`).
7. **Database test environment:** No MySQL test URL or integration tests exist. Agree on a dedicated test database and safe cleanup strategy before adding real DB tests.
8. **Equipment history vs release semantics:** This design retains allocation rows and defines active consumption through `booking.status = 'BOOKED'`, preserving cancelled booking history. Confirm this matches the team's meaning of “release equipment allocations.”
9. **Block overlap policy:** E2 block application overwrites booked cache intervals, but generation rejects overlapping effective blocks/bookings. Admin block-out is postponed; define whether blocks can ever cancel/override a booking and how claims/history behave before implementing admin persistence.
10. **Auth/session choice:** Password hashing is required, but the repository has no auth dependencies or session mechanism. Select a minimal secure approach during E4 design; do not add OTP.
11. **Cache refresh failure response:** The database commit cannot be undone if E2 refresh fails. Decide the exact HTTP response while preserving the fact that the booking/cancellation committed and preventing stale cache use.
12. **Operating hours and checks:** E2 enforces 06:00–20:00. Confirm whether MySQL constraints should duplicate those time limits or whether database checks should enforce only structural invariants while E2/E3 services enforce business hours.
13. **Availability response shape:** Existing E2 returns `AvailabilityInterval` models. Final API responses should define how dates, status, interval references, shortages, and non-active/cancelled records are represented without exposing internal cache state.

## Testing strategy

The existing suite covers E1/E2 in-memory logic and health/shared-contract smoke tests. It has no MySQL persistence tests. The required implementation should separate:

- **Unit tests:** timezone normalization and rejection of missing offsets; request/model validation; equipment-line validation; minute-index calculation for half-open intervals; mapping of E3 snapshots into E2 input models; typed error mapping; cancellation eligibility rules.
- **MySQL integration tests:** successful booking persistence; duplicate slot-claim rejection; rollback after booking, equipment-allocation, and slot-claim insert failures; FK/type compatibility; equipment overlap quantity validation with row locks; cancellation status and claim release; equipment release while retaining historical lines; restart hydration.
- **Concurrency tests:** exact and overlapping same-court requests; different-court requests; bounded-wait timeout/queue behavior; E2 precheck succeeding while the DB rejects; equipment availability changing between precheck and persistence; lock cleanup on every acquired-lock failure path.
- **API/frontend tests:** registration/login and duplicate rejection; authenticated ownership; history including cancelled bookings; cancellation after start, repeated cancellation, and other-owner rejection; frontend refresh after successful persisted operations.

The following scenarios are the explicit minimum end-to-end/integration checklist:

1. Two students attempt the same court and exact interval.
2. Two students attempt overlapping intervals on the same court.
3. Two students book different courts at the same time.
4. E1 lock acquisition times out.
5. E2 validation passes, but the database reports a court conflict.
6. Equipment becomes unavailable between initial validation and database persistence.
7. Database booking insertion fails.
8. Equipment allocation insertion fails.
9. Slot-claim insertion fails.
10. E2 cache synchronization fails after a successful database commit.
11. Backend restart rebuilds E2 from E3.
12. A student cancels their own booking.
13. A student attempts to cancel another student's booking.
14. A student attempts to cancel an already-cancelled booking.
15. A student attempts to cancel after the booking starts.
16. Cancellation releases all court claims.
17. Cancellation releases all equipment allocations from active inventory.
18. Another student books the exact same interval after cancellation.
19. A new booking is rejected after its interval start time passes.
20. A failed booking leaves neither stale E2 allocations nor partial E3 records.
21. A failed cancellation leaves the original booking intact.
22. E1 releases its lock after every failure path following successful acquisition.

Use only a dedicated test database for database tests; no destructive test should target a development or production database. Existing E1/E2 tests do not substitute for these DB and end-to-end cases.
