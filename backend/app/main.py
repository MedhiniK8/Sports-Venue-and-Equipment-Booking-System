import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from .config import get_settings
from .e1_concurrency.service import ConcurrencyService
from .e2_allocation import AllocationService
from .e3_persistence.session import dispose_engine
from .e3_persistence.repository import SqlAlchemyPersistenceRepository
from .e4_communication.coordinator import BookingCoordinator
from .e4_communication.routes import router


settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    application.state.booking_coordinator = BookingCoordinator(
        allocation=AllocationService(),
        concurrency=ConcurrencyService(),
        persistence=SqlAlchemyPersistenceRepository(),
    )
    try:
        yield
    finally:
        await dispose_engine()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(router)


@app.exception_handler(RequestValidationError)
async def request_validation_error(
    _: Request, exception: RequestValidationError
) -> JSONResponse:
    errors = [
        {
            "loc": error.get("loc"),
            "msg": error.get("msg"),
            "type": error.get("type"),
        }
        for error in exception.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.exception_handler(SQLAlchemyError)
async def database_error(_: Request, exception: SQLAlchemyError) -> JSONResponse:
    logger.exception(
        "Database request failed with %s",
        type(exception).__name__,
    )
    return JSONResponse(
        status_code=503,
        content={"detail": "Persistence service is unavailable"},
    )
