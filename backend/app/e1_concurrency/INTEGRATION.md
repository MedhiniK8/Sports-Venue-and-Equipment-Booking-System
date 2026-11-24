# E1 Integration Guide

## A. E1 Purpose

E1 performs in-process asynchronous interval-lock synchronization for booking requests.

E1:

- Detects court/date interval conflicts.
- Maintains active interval reservations.
- Generates public `LockToken` values.
- Supports bounded FIFO waiting.
- Applies a queue-wait timeout.
- Safely releases reservations.
- Cleans cancelled or timed-out waiters.

E1 does not:

- Execute MySQL queries.
- Create booking records.
- Validate sports or court availability.
- Allocate equipment.
- Perform E2 interval splitting or merging.
- Decide the final booking result.
- Contact the frontend or send notifications.

## B. Architecture

E4 owns FastAPI routes and booking orchestration. E4 should call one shared `ConcurrencyService` instance in the same Python process. After E1 grants a token, E4 should run the protected E3 transaction and release the token in `finally`.

No HTTP call is needed between E1 and E4 within the same backend process.

## C. Public Interface

Import the recommended API from `app.e1_concurrency`:

```python
from app.e1_concurrency import (
    ConcurrencyService,
    LockConflictError,
    LockQueueFullError,
    LockWaitTimeoutError,
    InvalidLockTokenError,
)
from app.contracts.booking import TimeInterval, LockToken
```

### `acquire(interval, resource_id)`

```python
async def acquire(
    interval: TimeInterval,
    resource_id: str,
) -> LockToken
```

- `interval`: E4-supplied half-open `[start, end)` interval.
- `resource_id`: E4-supplied court/resource identifier.
- Returns: unique public `LockToken`.
- Conflict: raises `LockConflictError`.
- Unknown behavior does not create a reservation.
- This is fail-fast and does not enter the waiting queue.

### `acquire_with_wait(interval, resource_id, timeout=3.0)`

```python
async def acquire_with_wait(
    interval: TimeInterval,
    resource_id: str,
    timeout: float = 3.0,
) -> LockToken
```

- `timeout`: queue-wait limit in seconds; it is not a booking-duration limit.
- Returns: unique public `LockToken`.
- Raises:
  - `LockConflictError` only through fail-fast `acquire()`, not wait-aware acquisition.
  - `LockWaitTimeoutError` when the queue deadline expires.
  - `LockQueueFullError` when the bounded waiting queue is full.
  - `InvalidLockTokenError` is not an acquisition outcome.

### `release(token)`

```python
async def release(self, token: LockToken) -> None
```

- Removes only the reservation associated with the supplied UUID and interval.
- Raises `InvalidLockTokenError` for unknown, repeated or mismatched tokens.
- E4 should call it only after successful acquisition.

## Lower-Level M2 Methods

These methods are useful for M2 tests and internal maintenance, but are not the recommended booking API:

- `register_reservation(interval, resource_id) -> RegistrationResult`
- `remove_reservation(reservation_id) -> bool`
- `get_active_reservations() -> tuple[ActiveReservation, ...]`
- `get_waiting_snapshot() -> tuple[WaitingSnapshot, ...]`

E4 should not modify `_active_reservations`, `_token_reservations`, `_waiting_requests`, `_registry_mutex` or `_WaitingRequest` objects.

## D. Inputs

E4 must supply:

- `resource_id`: the actual court or resource identifier.
- `interval.start`: the runtime booking start datetime.
- `interval.end`: the runtime booking end datetime.
- Optional waiting timeout when using `acquire_with_wait()`.
- The issued `LockToken` when releasing.

Court IDs and dates must not be copied from tests or hardcoded into E1.

## E. Outputs

Success produces a shared `LockToken`:

```python
LockToken(token=UUID, interval=TimeInterval)
```

Failure produces an exception. E1 does not return HTTP status codes or booking-confirmation statuses.

## F. Exception Mapping for E4

Suggested initial HTTP mapping:

- `LockConflictError`: HTTP 409 Conflict.
- `LockWaitTimeoutError`: HTTP 408 or 409, according to the agreed API contract.
- `LockQueueFullError`: HTTP 503 or 429, according to the agreed API contract.
- `InvalidLockTokenError`: HTTP 409 or 400, according to the agreed API contract.
- Unexpected database exceptions: E4 should propagate or map safely; E1 does not own E3 rollback.

These mappings are proposals for E4, not currently implemented E1 or FastAPI behavior.

## G. Runtime Booking Example

```python
from datetime import datetime

from app.contracts.booking import TimeInterval
from app.e1_concurrency import (
    ConcurrencyService,
    LockConflictError,
    LockQueueFullError,
    LockWaitTimeoutError,
)

e1 = ConcurrencyService()

async def protect_booking(
    runtime_court_id: str,
    start_datetime: datetime,
    end_datetime: datetime,
    run_e3_transaction,
):
    interval = TimeInterval(
        start=start_datetime,
        end=end_datetime,
    )

    token = None
    try:
        token = await e1.acquire_with_wait(
            interval,
            runtime_court_id,
            timeout=3.0,
        )

        return await run_e3_transaction(
            court_id=runtime_court_id,
            interval=interval,
            lock_token=token,
        )
    except LockConflictError:
        raise
    except LockWaitTimeoutError:
        raise
    except LockQueueFullError:
        raise
    finally:
        if token is not None:
            await e1.release(token)
```

The `run_e3_transaction` callable is an E4-provided dependency. E1 does not import E3 or call it.

If the calling task is cancelled, `finally` still runs while the coroutine can execute cleanup. E4 should use async task-cancellation-safe application practices and must not swallow `CancelledError`.

## H. Integration Workflow

```text
E4 receives runtime request
    -> E4 validates API/authentication
    -> E4 calls E2 validation
    -> E4 calls E1 acquire_with_wait(...)
    -> E1 returns LockToken
    -> E4 calls E3 protected transaction
    -> E4 calls E1 release(token) in finally
    -> E4 processes E2 synchronization/calendar/email as approved
    -> E4 returns HTTP response
```

The lock remains held from successful acquisition until E4 calls release after E3 processing completes or fails.

E1 does not release the token automatically after an E3 call. E4 must include release in `finally`.

## I. Service Lifecycle

Create one E1 service instance per backend worker process:

```python
e1_service = ConcurrencyService(
    max_waiting_requests=100,
)
```

Inject that same instance into E4's coordinator or dependency provider:

```python
coordinator = BookingCoordinator(concurrency=e1_service)
```

Do not create a new `ConcurrencyService()` inside each request or route call.

In-memory E1 state is process-local. Multiple backend workers have separate registries. E3 MySQL constraints and InnoDB transactions remain necessary for database-wide integrity.

There is currently no watchdog implementation or watchdog lifecycle API.

## J. State Ownership

- E1 owns active reservations, waiting requests and token mappings.
- E2 owns preliminary availability and derived interval operations.
- E3 owns MySQL state and ACID transactions.
- E4 owns authentication, routing, orchestration and HTTP response mapping.

## K. Integration Restrictions

- Do not create a per-request E1 instance.
- Do not copy or rewrite E1's registry.
- Do not modify `_active_reservations`, `_token_reservations`, `_waiting_requests`, `_registry_mutex` or waiter objects.
- Do not release a token before protected E3 work is complete.
- Do not share one token across multiple independent operations.
- Do not expose arbitrary token acquisition/release endpoints without separate authorization design.

## L. E4 Handoff Checklist

E4 should:

1. Import `ConcurrencyService` and E1 exceptions from `app.e1_concurrency`.
2. Construct exactly one service instance for its worker/process.
3. Inject it into `BookingCoordinator` or another approved E4 service.
4. Convert validated runtime court/date/time inputs into `TimeInterval`.
5. Call `acquire_with_wait()` for the booking wait-aware flow.
6. Keep `acquire()` as fail-fast behavior only if E4 has a separate use case.
7. Store the returned token locally for the duration of the protected E3 operation.
8. Call `release()` in `finally`.
9. Map exceptions at the E4 HTTP boundary.
10. Verify merge compatibility with independently developed E4 imports.

## M. Known Limitations

- E1 is single-process and in-memory.
- Multiple server processes do not share registry or queue state.
- E3 database constraints are required across workers.
- E1 does not provide watchdog monitoring.
- E1 is ready for direct E4 Python integration, but E4 startup wiring is not yet implemented.
