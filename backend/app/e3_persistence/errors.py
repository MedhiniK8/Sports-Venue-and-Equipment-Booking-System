from uuid import UUID


class DuplicateStudentError(Exception):
    def __init__(self, field: str | None = None) -> None:
        self.field = field
        message = f"A student with this {field} already exists" if field else (
            "A student account with these identifiers already exists"
        )
        super().__init__(message)


class BookingConflictError(Exception):
    """A requested court minute has already been claimed."""


class BookingStartTimeExpiredError(Exception):
    """The booking interval has already started or passed."""


class BookingResourceUnavailableError(Exception):
    """A court or equipment item is missing or inactive."""


class BookingNotFoundError(Exception):
    """The booking is not available to the authenticated student."""


class BookingAlreadyCancelledError(Exception):
    """The booking has already been cancelled."""


class BookingCancellationExpiredError(Exception):
    """The booking has already started and can no longer be cancelled."""


class EquipmentUnavailableError(Exception):
    def __init__(
        self,
        equipment_id: UUID,
        requested_quantity: int,
        available_quantity: int,
    ) -> None:
        self.equipment_id = equipment_id
        self.requested_quantity = requested_quantity
        self.available_quantity = available_quantity
        super().__init__("Requested equipment quantity is no longer available")
