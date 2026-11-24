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

No additional package is required.

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

For equipment shortages:

```python
equipment_result = e2.get_equipment_availability(
    equipment_id=equipment_id,
    interval=interval,
    requested_quantity=quantity,
)
if not equipment_result.valid:
    for shortage in equipment_result.shortages:
        # equipment_id, requested_quantity, available_quantity
        pass
```

E4 may offer court-only continuation, but E4—not E2—must decide whether to
continue or reject.

Allocation failures preserve E2's existing court/equipment cache state.
Combined allocation and cancellation stage both caches before commit.

No result should be interpreted as successful unless the relevant `valid` or
`succeeded` field is true.

## H. Integration flow

A typical E4 workflow should be:

1. E1 acquires the required court and equipment interval protection.
2. E4 creates an interval and equipment request models.
3. E4 calls court availability and equipment availability.
4. E4 decides whether to reject or continue court-only.
5. E4 calls `allocate_combined` or independent court/equipment operations.
6. E3 persists the successful result and equipment claims transactionally.
7. E4 returns the response.
8. E1 releases the lock.

Cancellation:

1. E1 protects the relevant court/equipment interval.
2. E4 identifies the booking and court/date metadata.
3. E4 calls `cancel_combined`.
4. E3 persists the cancellation and equipment restoration.
5. E1 releases the lock.

E4 must not call E2 internal cache methods for normal integration.

## I. Interval rules

All intervals use `[start, end)` half-open semantics.

Datetimes must be:

- Minute-aligned.
- Naive venue-local values.
- Positive duration.
- Within court/equipment hours for operations that enforce operating hours.

An interval ending at 11:00 does not overlap a reservation beginning at 11:00.

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
- Generate or refresh court availability using E3-derived committed records.
- Refresh equipment inventory and reservations from E3.
- Construct naive minute-aligned `TimeInterval` objects.
- Acquire E1 locks before protected allocation/cancellation operations.
- Call E2 availability first.
- Call one combined allocation method for court and equipment.
- Persist only after `succeeded == True`.
- Surface `shortages` and `errors` to E4.
- Use court-only mode only with explicit application decision.
- Call `cancel_combined` for complete booking cancellation.
- Release E1 locks after protected processing.

