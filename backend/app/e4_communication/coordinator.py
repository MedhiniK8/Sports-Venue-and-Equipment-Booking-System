from ..contracts.booking import BookingRequest, BookingResponse
from ..contracts.interfaces import AllocationInterface, ConcurrencyLockInterface
from ..e3_persistence.repository import PersistenceRepository


class BookingCoordinator:
    """Empty coordination boundary for E4."""

    def __init__(
        self,
        allocation: AllocationInterface | None = None,
        concurrency: ConcurrencyLockInterface | None = None,
        persistence: PersistenceRepository | None = None,
    ) -> None:
        self.allocation = allocation
        self.concurrency = concurrency
        self.persistence = persistence

    async def coordinate_booking(self, request: BookingRequest) -> BookingResponse:
        raise NotImplementedError("Booking orchestration is not implemented")
