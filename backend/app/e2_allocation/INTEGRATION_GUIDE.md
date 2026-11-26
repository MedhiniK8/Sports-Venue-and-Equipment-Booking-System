# E2 to E4 Integration Guide

## A. Architecture overview

E2 owns court availability, court and equipment allocation, cancellation, block
application, and in-memory derived allocation state. E2 does not provide HTTP
routes, authentication, database persistence, SQL transactions, or E1 locks.

E4 is responsible for API and UI behavior, authentication, orchestration, and
coordination with E1 and E3. E1 owns locking. E3 owns persistence and
database transactions.

E2 is process-local. A cache does not survive process restart and is not shared
between processes. E1 must provide the concurrency boundary for E4 workflows.
E3 must supply inventory and committed reservation state and persist successful
allocations and cancellations.

## B. Public entry point

Use `app.e2_allocation.AllocationService`. Do not import internal cache and
interval modules from E4 for normal integration.

```python
from app.e2_allocation import AllocationService

e2 = AllocationService()
```

The constructor accepts optional isolated caches:

```python
from app.e2_allocation import AllocationService, AvailabilityCache, EquipmentCache

e2 = AllocationService(
    court_cache=AvailabilityCache(),
    equipment_cache=EquipmentCache(),
)
```

Ordinary callers should not pass or modify these caches. They are exposed on
the service only for initialization and testing.

## C. Exact public imports

```python
from app.e2_allocation import (
    AllocationService,
    AvailabilityStatus,
    CombinedAllocationCache,
    EquipmentAllocationRequest,
    EquipmentInventory,
    EquipmentRequestLine,
    EquipmentReservation,
    EquipmentValidationResult,
    TimeInterval,
)
```

`TimeInterval` is exported from the existing shared contract module.

## D. Initialization

Create one service instance per logical E2 cache scope. E4 should retain that
instance for its process lifetime and should not recreate it between sequential
operations.

Before court operations, court availability must be generated or populated:

```python
e2.generate_availability(
    active_court_ids=[court_id],
    bookings=[],
    blocks=[],
    reference_date=booking_date,
)
```

The service does not load courts or inventory itself. E4/E3 must supply:

- Active court UUIDs.
- Committed court bookings.
- Effective court blocks.
- Current equipment inventory.
- Existing committed equipment reservations.

Set inventory from the integration layer:

```python
e2.set_equipment_inventory(
    EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=inventory_quantity,
    )
)
```

This is a cache inventory update, not an equipment allocation.

## E. Dependencies

E2 uses existing project dependencies:

- Python 3.11 or newer.
- Pydantic 2.
- Existing UUID, datetime and date standard-library types.
- The `tzdata` package supplies IANA timezone data on platforms such as Windows
  where the operating system does not provide it to `zoneinfo`.

`Asia/Kolkata` is the canonical venue timezone. E2 interval and optional
`current_datetime` inputs remain naive venue-local datetimes. If the optional
clock value is omitted, E2 derives the current time using
`ZoneInfo("Asia/Kolkata")` and converts it to the naive venue-local contract.

## F. Public operations

### Court availability

```python
result = e2.check_court_availability(
    court_id=court_id,
    booking_date=booking_date,
    interval=interval,
    current_datetime=now,
)
```

Parameters:

- `court_id: UUID`
- `booking_date: date`
- `interval: TimeInterval`
- `current_datetime: datetime | None`

When supplied, `current_datetime` must be naive and represent venue-local time.
Do not pass a machine-local or UTC datetime. The default uses the canonical
`Asia/Kolkata` clock.

Returns `contracts.booking.ValidationResult`.

Fields:

- `valid: bool`
- `errors: list[str]`

### Court availability snapshot

```python
court_intervals = e2.get_court_availability(court_id, booking_date)
```

Returns `list[AvailabilityInterval] | None`. The returned list and its
`AvailabilityInterval` objects are deep defensive copies. Mutating a returned
interval or interval endpoint does not alter the underlying court cache.

### Court allocation

```python
result = e2.allocate_court(
    court_id=court_id,
    booking_date=booking_date,
    interval=interval,
    booking_id=booking_id,
    current_datetime=now,
)
```

Returns `ValidationResult`.

Only FREE availability is allocated. BOOKED or BLOCKED overlap is rejected.

### Court cancellation

```python
result = e2.cancel_court(
    court_id=court_id,
    booking_date=booking_date,
    booking_id=booking_id,
)
```

Returns `ValidationResult`. It converts exactly one matching court BOOKED
interval to FREE and merges adjacent FREE intervals.

### Court block

```python
result = e2.apply_court_block(
    court_id=court_id,
    booking_date=booking_date,
    interval=interval,
    block_id=block_id,
    current_datetime=now,
)
```

Returns `ValidationResult`. Existing BLOCKED intervals cannot be overwritten.
BOOKED intervals may be overridden by the E2 block operation.

### Court availability generation

```python
e2.generate_availability(
    active_court_ids=[court_id],
    bookings=[committed_booking],
    blocks=[effective_block],
    reference_date=booking_date,
)
```

Returns `None`.

Inputs use:

- `CommittedBooking`
- `EffectiveCourtBlock`
- `date`

It generates the requested date and following six dates.

### Equipment availability

```python
result = e2.get_equipment_availability(
    equipment_id=equipment_id,
    interval=interval,
    requested_quantity=2,
)
```

Returns `EquipmentAvailabilityResult`.

Important fields:

- `valid`
- `errors`
- `total_inventory`
- `available_quantity`
- `segments`
- `shortages`

The `available_quantity` is the minimum remaining quantity across the complete
requested interval.

Availability queries enforce:

- Valid positive, minute-aligned `TimeInterval` values.
- Naive venue-local datetimes.
- One calendar date.
- Court/equipment operating hours 06:00–20:00.

Availability queries do not apply booking-allocation-only past-time or
"interval has already started" restrictions. They may therefore be used to
inspect historical or already-started intervals. Allocation remains responsible
for rejecting past and elapsed requests.

### Equipment inventory refresh

```python
inventory_result = e2.set_equipment_inventory(
    EquipmentInventory(
        equipment_id=equipment_id,
        total_quantity=inventory_quantity,
    )
)
```

Returns `EquipmentValidationResult`.

An inventory reduction is rejected if existing reservations would exceed the new
total quantity. Existing reservations are preserved when an inventory change is
safe.

### Equipment reservation snapshot refresh

Hydrate or refresh committed equipment reservations through the public service:

```python
refresh_result = e2.refresh_equipment_reservations(
    [
        EquipmentReservation(
            equipment_id=equipment_id,
            booking_id=booking_id,
            interval=interval,
            quantity=2,
        ),
    ]
)
```

Signature:

```python
def refresh_equipment_reservations(
    reservations: Iterable[EquipmentReservation],
) -> EquipmentValidationResult
```

The supplied iterable is an authoritative full reservation snapshot. Successful
refresh replaces the existing equipment reservation state atomically. Inventory
entries are preserved. The cache is not changed if the snapshot is invalid,
contains a missing inventory entry, exceeds inventory, uses a cross-date
interval, or contains ambiguous duplicate booking references.

Use this only with a complete E3-derived reservation snapshot. Supplying a
partial snapshot may remove valid claims that were not included.

### Equipment allocation

```python
result = e2.allocate_equipment(
    EquipmentAllocationRequest(
        booking_id=booking_id,
        court_id=court_id,
        interval=interval,
        items=(
            EquipmentRequestLine(
                equipment_id=football_id,
                quantity=2,
            ),
            EquipmentRequestLine(
                equipment_id=racket_id,
                quantity=1,
            ),
        ),
    ),
    current_datetime=now,
)
```

Returns `EquipmentAllocationResult`.

Important fields:

- `succeeded`
- `booking_id`
- `allocated_items`
- `reservations`
- `shortages`
- `errors`

Allocation is all-or-nothing across all requested equipment items.

### Equipment cancellation

```python
result = e2.cancel_equipment(
    booking_id=booking_id,
    equipment_id=None,
)
```

If `equipment_id` is supplied, only that item's reservations are cancelled.
Without it, every equipment reservation for the booking is cancelled.

Returns `EquipmentCancellationResult`.

### Combined allocation

```python
result = e2.allocate_combined(
    court_id=court_id,
    booking_date=booking_date,
    interval=interval,
    booking_id=booking_id,
    items=(
        EquipmentRequestLine(
            equipment_id=football_id,
            quantity=2,
        ),
    ),
    current_datetime=now,
)
```

Returns `CombinedAllocationResult`.

Important fields:

- `succeeded`
- `booking_id`
- `court_allocated`
- `equipment_allocated`
- `allocated_items`
- `shortages`
- `errors`

An empty `items` tuple represents a court-only combined booking.

### Combined cancellation

```python
result = e2.cancel_combined(
    booking_id=booking_id,
    court_id=court_id,
    booking_date=booking_date,
)
```

Returns `CombinedCancellationResult`.

Important fields:

- `succeeded`
- `booking_id`
- `court_cancelled`
- `equipment_cancelled`
- `cancelled_equipment_reservation_count`
- `repeated`
- `errors`

## G. Failure handling

E4 should branch on the result field rather than exceptions:

```python
court_result = e2.check_court_availability(...)
if not court_result.valid:
    # Reject or surface court_result.errors.
    pass
```

For a booking request with multiple equipment lines, use the read-only
request-level validator so E2 evaluates every requested type and returns all
shortages together:

```python
equipment_result = e2.validate_equipment_request(equipment_request)
if not equipment_result.valid:
    for shortage in equipment_result.shortages:
        # equipment_id, requested_quantity, available_quantity
        pass
```

The validator does not mutate E2 caches. E4 must present the student's choice;
it must not reduce quantities silently. On continue, the final check determines
which complete equipment lines are retained.

Allocation failures preserve E2's existing court/equipment cache state.
Combined allocation and cancellation stage both caches before commit.

No result should be interpreted as successful unless the relevant `valid` or
`succeeded` field is true.

## H. Integration flow

A student booking workflow should be:

1. E4 authenticates the student and obtains `user_id` from the authenticated
   context.
2. E2 checks court availability and validates all requested equipment before
   E1 lock acquisition.
3. If equipment shortages exist without a decision, E4 returns the structured
   decision-required response with `CONTINUE_WITHOUT_EQUIPMENT` and
   `CANCEL_REQUEST` as the only choices. `CANCEL_REQUEST` returns without
   acquiring E1, persisting in E3, or publishing a booking into E2.
4. For `CONTINUE_WITHOUT_EQUIPMENT`, E4 obtains a fresh authoritative E3
   snapshot, builds a temporary E2 view, and repeats court and equipment checks
   before acquiring E1. Keep available equipment lines at their requested
   quantities and omit only unavailable lines.
5. E1 acquires the court interval lock only after the final E2 checks pass.
6. E3 revalidates equipment capacity under deterministic inventory row locks,
   rejects a start time that has passed at the persistence boundary, then
   atomically persists the booking, slot claims, and retained allocations.
7. Only after E3 commits does E4 refresh the shared E2 cache from E3.
8. E4 returns the booking response and releases any acquired E1 token in
   `finally`.

The current E4 boundary uses E1's `acquire_with_wait(interval, resource_id, timeout)`
and `release(token)`, E2's `check_court_availability`,
`validate_equipment_request`, and availability snapshot operations, and E3's
`PersistenceRepository` methods `load_allocation_snapshot`,
`create_booking`, `get_booking_for_student`, `cancel_booking`, and
`list_student_bookings`. Booking writes use `CreateBookingInput`; repository
results are typed `BookingRecord` values. User identity is a separate
authenticated `UUID` argument and is not part of the public booking request.

Cancellation:

1. E4 obtains the authenticated student UUID and asks E3 for that student's
   persisted booking metadata. A missing or non-owned booking is rejected
   before acquiring E1.
2. E4 acquires E1 for the persisted court and half-open interval.
3. E3 rechecks ownership, `BOOKED` status, and the cancellation start-time
   boundary from persisted data inside one transaction. It changes the booking
   to `CANCELLED` and deletes its slot claims atomically. Equipment-allocation
   rows remain as booking history; snapshot queries count only `BOOKED`
   reservations.
4. After E3 commits, E4 reloads the authoritative allocation snapshot from E3
   and refreshes E2. A refresh failure invalidates E4's cache revision and
   returns an explicit committed-but-refresh-failed result; it does not undo
   the committed cancellation.
5. E4 releases E1 in `finally` on every path after acquisition.

The normal student workflow does not call E2's in-memory `cancel_combined` as a
substitute for E3 persistence.

Do not use E2's in-memory combined allocation as a substitute for E3
persistence. E4 must not call E2 internal cache methods for normal integration.

## I. Interval rules

All intervals use `[start, end)` half-open semantics.

Datetimes must be:

- Minute-aligned.
- Naive venue-local values.
- Positive duration.
- Within court/equipment hours for operations that enforce operating hours.

An interval ending at 11:00 does not overlap a reservation beginning at 11:00.
Student API time fields are wall-clock venue times: timezone-aware values are
rejected instead of being silently reinterpreted. E4 combines the request date
and times into naive venue-local datetimes. E3 accepts an aware cancellation
clock only by converting it to `Asia/Kolkata`; naive values at that boundary
are interpreted as venue-local.

## J. Limitations

- E2 caches are process-local.
- E2 does not implement E1 locking.
- E2 does not implement E3 persistence or transactions.
- E2 does not implement API authentication or routes.
- E2 local rollback is not database rollback.
- E4 must validate user identity and authorization.
- The combined operation maintains in-process booking metadata and tombstones;
  E3/E4 must supply durable metadata in a real deployment.

### Compatibility methods

`AllocationService.validate_time_slot`,
`AllocationService.generate_calendar`, and
`AllocationService.process_post_commit_split_merge` implement the legacy shared
`AllocationInterface`. They are compatibility methods, not the normal E4
allocation workflow.

Use `check_court_availability`, `generate_availability`,
`allocate_combined` and the dedicated cancellation methods for integration.

## K. Integration checklist

- Create and retain one `AllocationService` instance in the E4 process scope.
- Obtain E3's authoritative snapshot and check court availability before any
  equipment decision response.
- Validate all equipment lines and return every shortage before acquiring E1.
- For continue-without-equipment, reload E3 state and repeat final court and
  equipment checks before E1; retain available lines at their original
  quantities and omit only unavailable lines.
- Acquire E1 only after the required E2 checks succeed.
- Let E3 revalidate equipment under inventory row locks and commit the booking
  and related rows atomically.
- Surface a persistence-boundary start-time rejection as a conflict; do not
  treat it as a committed booking.
- Refresh E2 only after successful E3 commit, using a complete E3 snapshot.
- For cancellation, obtain persisted interval metadata, acquire E1, call E3's
  transactional cancellation, and refresh E2 only after commit.
- Release E1 in `finally` on every path after acquisition.
- Surface E3 capacity/conflict failures distinctly from post-commit E2 refresh
  failures; the latter mean the booking/cancellation committed and the cache
  needs recovery.

## L. MySQL configuration and migrations

E3 uses SQLAlchemy's async engine with the `asyncmy` driver. Configure
`DATABASE_URL` in the deployment environment using the form
`mysql+asyncmy://<user>:<password>@<host>:3306/<database>?charset=utf8mb4`.
URL-encode special characters in credentials. Do not put credentials in
committed files. Application settings reject a URL that does not use the
`mysql+asyncmy` driver or lacks a host/database. Use MySQL 8.0.16 or newer so
`CHECK` constraints are enforced; all E3 tables are declared as InnoDB.

The Alembic environment reads `DATABASE_URL` through application settings.
Each E3 repository operation owns and closes its `AsyncSession`; write
operations use `session.begin()` so successful context exit commits and an
exception rolls back. The FastAPI lifespan disposes the async engine at
shutdown. The engine is created lazily with connection pre-ping enabled.
From the repository root, future deployment operators should first inspect the
revision chain and render SQL without connecting:

```powershell
python -m alembic -c backend\alembic.ini history
python -m alembic -c backend\alembic.ini upgrade head --sql
```

Offline rendering cannot run the booking-status data preflight. The rendered
output includes a warning to verify existing status bytes. Before any online
upgrade, back up the target schema, inspect its current Alembic revision, and
confirm that the target is the intended MySQL 8 database. Then, only with
deployment approval, set `DATABASE_URL` outside the repository and run:

```powershell
python -m alembic -c backend\alembic.ini current
python -m alembic -c backend\alembic.ini upgrade head
python -m alembic -c backend\alembic.ini check
```

Revision `0002_booking_status_values` validates exact legacy status bytes
before its first data or schema change. It aborts on unexpected values. Never
assume the database is empty or that a revision is unapplied. No migration has
been run against a live database as part of this guide update. The current test
suite uses SQLite and fakes; a dedicated MySQL integration suite must be run
against a disposable MySQL 8 database to establish InnoDB locking, constraint,
rollback, and migration behavior.

## M. Student catalog endpoints

E4 exposes the following read-only catalog routes. Each requires the same
Bearer access token as student booking and history routes. Registration,
login, and health remain public. E4 validates authentication and response
schemas, then calls the E3 `PersistenceRepository`; E4 does not query models.
E3 owns the active-record filters and runs the queries with its normal async
session lifecycle. These routes do not change E2 allocation state or E1 locks.

### `GET /api/catalog/sports`

Returns active sports as a JSON array:

```json
[
  {
    "sport_id": "5c925a96-5031-4f66-87df-73fbcc503130",
    "name": "Badminton"
  }
]
```

### `GET /api/catalog/sports/{sport_id}/courts`

Returns active courts for the selected active sport:

```json
[
  {
    "court_id": "59d5db51-7624-4bfc-a81c-608d289836e6",
    "name": "Court 1"
  }
]
```

An active sport with no active courts returns `200 []`. A valid UUID for an
unknown or inactive sport returns `404`:

```json
{
  "detail": {
    "code": "sport_not_found",
    "message": "Sport was not found or is inactive"
  }
}
```

Malformed UUID path values receive FastAPI's standard `422` validation
response. All UUIDs in JSON responses are serialized as strings.

### `GET /api/catalog/equipment`

Returns active equipment types as a JSON array:

```json
[
  {
    "equipment_id": "0df5100b-9da7-4a43-906f-41a6c85f5b22",
    "name": "Racket"
  }
]
```

The catalog intentionally does not expose a date-specific available quantity:
availability is evaluated for the requested interval by E2 and is revalidated
by E3 when a booking is persisted. All three endpoints return `200 []` when
their catalog query has no active results. Missing or invalid bearer
credentials receive the standard `401` response; persistence errors use the
application's standard `503` response.

