
import logging
from typing import Protocol
from collections.abc import Callable
from typing import Any

from ..contracts.booking import (
    BookingRequest,
    BookingResponse,
    LockToken,
    TransactionResult,
)
from ..contracts.interfaces import (
    AllocationInterface,
    ConcurrencyLockInterface,
)


logger = logging.getLogger(__name__)


class PersistencePort(Protocol):

    async def create_booking(
        self,
        request: BookingRequest,
    ) -> TransactionResult:
        ...


class BookingRejectedError(Exception):
    pass


class BookingBusyError(Exception):
    pass


class BookingPersistenceError(Exception):
    pass


class BookingDependencyError(ValueError):
    pass


def _require_callable(dependency: Any, method_name: str) -> Callable[..., Any]:
    method = getattr(dependency, method_name, None)
    if not callable(method):
        raise BookingDependencyError(
            f"Required booking dependency method '{method_name}' is not configured."
        )
    return method


class BookingCoordinator:
    """Coordinates booking operations across E1, E2 and E3."""

    def __init__(
        self,
        allocation: AllocationInterface,
        concurrency: ConcurrencyLockInterface,
        persistence: PersistencePort,
    ) -> None:
        self.allocation = allocation
        self.concurrency = concurrency
        self.persistence = persistence
        _require_callable(allocation, "validate_time_slot")
        _require_callable(allocation, "process_post_commit_split_merge")
        _require_callable(concurrency, "acquire")
        _require_callable(concurrency, "release")
        _require_callable(persistence, "create_booking")

    async def coordinate_booking(
        self,
        request: BookingRequest,
    ) -> BookingResponse:

        interval = request.interval

        # Step 1: Ask E2 to validate the court, equipment and interval.
        try:
            validation = await self.allocation.validate_time_slot(
                court_id=request.court_id,
                equipment_id=request.equipment_id,
                interval=interval,
            )
        except NotImplementedError as exc:
            raise BookingDependencyError(
                "The allocation engine is not configured."
            ) from exc
        except Exception as exc:
            logger.exception("Allocation engine validation failed.")
            raise BookingDependencyError(
                "The allocation engine is unavailable."
            ) from exc

        if not validation.valid:
            details = "; ".join(validation.errors)

            raise BookingRejectedError(
                details or "The requested booking is invalid."
            )

        # Step 2: Ask E1 to acquire the court interval lock.
        try:
            lock_token: LockToken = await self.concurrency.acquire(
                interval=interval,
                resource_id=str(request.court_id),
            )
        except NotImplementedError as exc:
            raise BookingDependencyError(
                "The concurrency engine is not configured."
            ) from exc
        except Exception as exc:
            raise BookingBusyError(
                "The requested court interval is currently busy."
            ) from exc

        try:
            # Step 3: Ask E3 to persist the booking.
            try:
                transaction: TransactionResult = (
                    await self.persistence.create_booking(request)
                )
            except NotImplementedError as exc:
                raise BookingDependencyError(
                    "The persistence engine is not configured."
                ) from exc
            except Exception as exc:
                logger.exception("E3 persistence call failed.")
                raise BookingPersistenceError(
                    "The booking transaction failed."
                ) from exc

            if not transaction.succeeded:
                raise BookingPersistenceError(
                    transaction.error_code
                    or "The booking transaction failed."
                )

            # E3 must return the actual persisted booking ID.
            if transaction.booking_id is None:
                raise BookingPersistenceError(
                    "E3 did not return the persisted booking ID."
                )

            # Step 4: Ask E2 to process post-commit split/merge.
            try:
                await self.allocation.process_post_commit_split_merge(
                    transaction
                )
            except Exception:
                logger.exception(
                    "Booking committed, but post-commit processing failed."
                )

            # Step 5: Return the actual booking ID supplied by E3.
            return BookingResponse(
                booking_id=transaction.booking_id,
                status="CONFIRMED",
                court_id=request.court_id,
                equipment_id=request.equipment_id,
                interval=interval,
            )

        finally:
            # Step 6: Always attempt to release the acquired lock.
            try:
                await self.concurrency.release(lock_token)
            except Exception:
                logger.exception(
                    "Failed to release the court interval lock."
                )
