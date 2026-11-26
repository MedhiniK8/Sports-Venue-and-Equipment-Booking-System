# Shared Interfaces

The current student booking workflow is implemented by E4 coordinating E1, E2,
and E3. The detailed operation order and MySQL setup are documented in the
[E2-to-E4 Integration Guide](../backend/app/e2_allocation/INTEGRATION_GUIDE.md).

## Engine responsibilities

- **E1 — Concurrency:** provides wait-aware interval-lock acquisition and token
  release. Lock state is process-local.
- **E2 — Allocation:** validates court and equipment availability and builds
  derived in-memory availability from E3 snapshots.
- **E3 — Persistence:** owns SQLAlchemy models, the physical `users` table,
  repositories, MySQL migrations, and transaction boundaries.
- **E4 — Communication:** owns authentication, student-facing HTTP APIs, and
  orchestration across the other engines.

## Student booking contracts

- Student identity is taken from the authenticated E4 context; the booking
  request does not accept a user UUID.
- Request times and E2 interval datetimes are naive `Asia/Kolkata` wall times.
  Venue-local current-time decisions use the IANA `Asia/Kolkata` timezone.
- Intervals are positive, minute-aligned, same-date, half-open intervals:
  `[start, end)`. Court operating hours are 06:00–20:00.
- Booking statuses are exactly `BOOKED` and `CANCELLED`. A decision-required
  response is not a booking and has no status.
- E2 checks availability before E1. E1 is released in `finally` after
  acquisition. E3 commits before E2's authoritative snapshot is refreshed.
- Cancellation uses the stored booking interval, performs owner/status/start
  checks in E3, and keeps the booking and equipment allocation history.

The generic `AllocationInterface` methods in
`backend/app/contracts/interfaces.py` remain compatibility contracts; the
student workflow uses `AllocationService`'s explicit availability and snapshot
operations instead.

## Verification boundary

SQLite and fake-based tests do not establish MySQL/InnoDB row-locking,
constraint-enforcement, or production migration behavior. Apply migrations
only to an explicitly approved database after reviewing its current revision
and backing it up. No live database migration is implied by this document.
