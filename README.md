# Sports Venue and Equipment Booking System

A college mini-project foundation for a sports venue and equipment booking system.

## Stack

- React and Vite
- Python FastAPI
- Python `asyncio`
- MySQL 8 with InnoDB
- SQLAlchemy Async with `asyncmy`
- Pytest and pytest-asyncio
- Git and GitHub Actions

The project uses a **layered modular monolith**. It keeps four engines independently implementable while avoiding the deployment complexity of microservices. E4 is the only browser-facing backend entry point. E3 is the only module allowed to access MySQL.

## Engine responsibilities

- **E1 — Concurrency Engine:** asynchronous interval-lock interfaces, implemented later by Medhini.
- **E2 — Allocation & Conflict Engine:** time-slot validation, calendar generation, and split/merge interfaces, implemented later by Sahana.
- **E3 — Data Persistence Engine:** SQLAlchemy models, repository placeholders, and lazy async session setup, implemented later by Tejashwini.
- **E4 — Communication Engine:** FastAPI application and route structure, implemented later by Pavitra.

No core booking operations are implemented in this foundation.

## Planned workflow

`User → E2 validate → E1 acquire → E3 transaction/commit → E2 split/merge → E4 calendar update → E1 release → confirmation`

There is no E2 revalidation between E1 and E3. Intervals use `[start, end)`, minute precision, example operating hours of 06:00–20:00, and optional equipment. Authentication supplies user identity.

See [Shared Interfaces](docs/SHARED_INTERFACES.md) for the contract summary.

## Setup

Prerequisites:

- Python 3.11 or newer
- Node.js 20 or newer
- npm
- Optional MySQL 8 instance

The backend and frontend start without an active MySQL connection.

### Backend

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
Copy-Item .env.example .env
uvicorn app.main:app --reload --app-dir backend
```

FastAPI will be available at `http://localhost:8000`; the health endpoint is `http://localhost:8000/api/health`.

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Vite is available at `http://localhost:5173` and proxies `/api` to FastAPI.

## Tests

From the repository root:

```powershell
pytest
```

Frontend build check:

```powershell
cd frontend
npm install
npm run build
```

## Git workflow

Prepare feature branches from `main`:

- `feat/e1-concurrency`
- `feat/e2-allocation`
- `feat/e3-persistence`
- `feat/e4-communication`

Members should primarily edit their assigned engine directory and matching test directory. Shared contracts in `backend/app/contracts` require team agreement. Open a pull request with foundation tests passing; GitHub Actions runs the test suite for pull requests.
