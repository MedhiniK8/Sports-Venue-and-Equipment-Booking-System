# Shared Interfaces

The application is a layered modular monolith. E4 is the only browser-facing entry point, and E3 is the only module permitted to access MySQL.

## Engine responsibilities

- **E1 — Concurrency:** owns interval-lock acquisition and release interfaces.
- **E2 — Allocation:** owns time-slot validation, calendar generation, and post-commit split/merge interfaces.
- **E3 — Persistence:** owns SQLAlchemy configuration, models, repositories, and async transaction management.
- **E4 — Communication:** owns FastAPI routes and the booking coordinator boundary.

## Planned workflow

`User → E2 validate → E1 acquire → E3 transaction/commit → E2 split/merge → E4 calendar update → E1 release → confirmation`

This is an interface plan only. E2 must not revalidate after E1 has acquired the interval.

## Shared rules

- Intervals are half-open: `[start, end)`.
- Time precision is one minute.
- Example operating hours are 06:00–20:00.
- Equipment is optional.
- User identity comes from authentication and is not accepted as a client input field.
- Engine implementations must raise `NotImplementedError` until they are deliberately implemented in later work.
