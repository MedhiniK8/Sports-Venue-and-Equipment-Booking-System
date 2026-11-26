from collections.abc import Iterable
from datetime import date, datetime
from typing import Optional
from uuid import UUID

from ..contracts.booking import TimeInterval, TransactionResult, ValidationResult
from ..contracts.interfaces import AllocationInterface
from .availability_generation import (
    CommittedBooking,
    EffectiveCourtBlock,
    populate_seven_day_availability,
)
from .block_update import apply_block_to_cache
from .booking_update import apply_booking_to_cache
from .cache import AvailabilityCache
from .cancellation import cancel_booking_from_cache
from .combined_booking import CombinedAllocationCache
from .equipment_allocation import allocate_equipment
from .equipment_availability import get_equipment_availability
from .equipment_cache import EquipmentCache
from .equipment_cancellation import cancel_equipment_booking
from .equipment_models import (
    CombinedAllocationResult,
    CombinedCancellationResult,
    EquipmentAllocationRequest,
    EquipmentAllocationResult,
    EquipmentAvailabilityResult,
    EquipmentCancellationResult,
    EquipmentInventory,
    EquipmentRequestLine,
    EquipmentReservation,
    EquipmentValidationResult,
)
from .equipment_validation import (
    validate_equipment_request as validate_equipment_allocation_request,
)
from .models import AvailabilityInterval
from .validation import (
    validate_block_availability,
    validate_booking_availability,
)


class AllocationService(AllocationInterface):
    """Stable, cache-owning public entry point for E2 allocation operations."""

    def __init__(
        self,
        court_cache: AvailabilityCache | None = None,
        equipment_cache: EquipmentCache | None = None,
    ) -> None:
        self.court_cache = court_cache or AvailabilityCache()
        self.equipment_cache = equipment_cache or EquipmentCache()
        self.combined = CombinedAllocationCache(
            self.court_cache,
            self.equipment_cache,
        )

    def generate_availability(
        self,
        active_court_ids: Iterable[UUID],
        bookings: Iterable[CommittedBooking],
        blocks: Iterable[EffectiveCourtBlock],
        reference_date: date,
    ) -> None:
        """Generate and replace the seven-day court availability window."""
        populate_seven_day_availability(
            self.court_cache,
            active_court_ids,
            bookings,
            blocks,
            reference_date,
        )

    def get_court_availability(
        self,
        court_id: UUID,
        booking_date: date,
    ) -> list[AvailabilityInterval] | None:
        """Get a defensive copy of derived court availability."""
        return self.court_cache.get_intervals(court_id, booking_date)

    def check_court_availability(
        self,
        court_id: UUID,
        booking_date: date,
        interval: TimeInterval,
        current_datetime: datetime | None = None,
    ) -> ValidationResult:
        return validate_booking_availability(
            court_id,
            booking_date,
            interval,
            self.court_cache,
            current_datetime=current_datetime,
        )

    def allocate_court(
        self,
        court_id: UUID,
        booking_date: date,
        interval: TimeInterval,
        booking_id: UUID,
        current_datetime: datetime | None = None,
    ) -> ValidationResult:
        return apply_booking_to_cache(
            court_id,
            booking_date,
            interval,
            booking_id,
            self.court_cache,
            current_datetime=current_datetime,
        )

    def cancel_court(
        self,
        court_id: UUID,
        booking_date: date,
        booking_id: UUID,
    ) -> ValidationResult:
        return cancel_booking_from_cache(
            court_id,
            booking_date,
            booking_id,
            self.court_cache,
        )

    def apply_court_block(
        self,
        court_id: UUID,
        booking_date: date,
        interval: TimeInterval,
        block_id: UUID,
        current_datetime: datetime | None = None,
    ) -> ValidationResult:
        return apply_block_to_cache(
            court_id,
            booking_date,
            interval,
            block_id,
            self.court_cache,
            current_datetime=current_datetime,
        )

    def set_equipment_inventory(
        self,
        inventory: EquipmentInventory,
    ) -> EquipmentValidationResult:
        return self.equipment_cache.replace_inventory(inventory)

    def refresh_equipment_reservations(
        self,
        reservations: Iterable[EquipmentReservation],
    ) -> EquipmentValidationResult:
        """Replace the complete in-memory equipment reservation snapshot.

        Reservations are an authoritative E3-derived full snapshot. Inventory
        entries are preserved. On failure, the existing reservation snapshot
        remains unchanged.
        """
        return self.equipment_cache.replace_reservation_snapshot(reservations)

    def get_equipment_availability(
        self,
        equipment_id: UUID,
        interval: TimeInterval,
        requested_quantity: int = 1,
    ) -> EquipmentAvailabilityResult:
        return get_equipment_availability(
            equipment_id,
            interval,
            self.equipment_cache,
            requested_quantity=requested_quantity,
        )

    def validate_equipment_request(
        self,
        request: EquipmentAllocationRequest,
        current_datetime: datetime | None = None,
    ) -> EquipmentValidationResult:
        return validate_equipment_allocation_request(
            request,
            self.equipment_cache,
            current_datetime=current_datetime,
        )

    def allocate_equipment(
        self,
        request: EquipmentAllocationRequest,
        current_datetime: datetime | None = None,
    ) -> EquipmentAllocationResult:
        return allocate_equipment(
            request,
            self.equipment_cache,
            current_datetime=current_datetime,
        )

    def cancel_equipment(
        self,
        booking_id: UUID,
        equipment_id: UUID | None = None,
    ) -> EquipmentCancellationResult:
        return cancel_equipment_booking(
            booking_id,
            self.equipment_cache,
            equipment_id=equipment_id,
        )

    def allocate_combined(
        self,
        court_id: UUID,
        booking_date: date,
        interval: TimeInterval,
        booking_id: UUID,
        items: tuple[EquipmentRequestLine, ...] = (),
        current_datetime: datetime | None = None,
    ) -> CombinedAllocationResult:
        return self.combined.allocate(
            court_id=court_id,
            booking_date=booking_date,
            interval=interval,
            booking_id=booking_id,
            items=items,
            current_datetime=current_datetime,
        )

    def cancel_combined(
        self,
        booking_id: UUID,
        court_id: UUID | None = None,
        booking_date: date | None = None,
    ) -> CombinedCancellationResult:
        return self.combined.cancel(
            booking_id,
            court_id=court_id,
            booking_date=booking_date,
        )

    async def validate_time_slot(
        self,
        interval: TimeInterval,
    ) -> ValidationResult:
        """Compatibility method for interval-contract users.

        Full availability validation requires court_id and booking_date;
        use check_court_availability for the complete check.
        """
        try:
            validated = TimeInterval.model_validate(interval)
        except Exception as error:
            return ValidationResult(valid=False, errors=[str(error)])
        if validated.start.utcoffset() is not None or validated.end.utcoffset() is not None:
            return ValidationResult(
                valid=False,
                errors=["Requested datetimes must be naive venue-local values."],
            )
        start_minute = validated.start.hour * 60 + validated.start.minute
        end_minute = validated.end.hour * 60 + validated.end.minute
        if start_minute < 6 * 60 or end_minute > 20 * 60:
            return ValidationResult(
                valid=False,
                errors=["Requested interval must be within court hours (06:00-20:00)."],
            )
        return ValidationResult(valid=True)

    async def generate_calendar(
        self,
        interval: TimeInterval,
    ) -> list[TimeInterval]:
        """Compatibility placeholder; use generate_availability with explicit inputs."""
        try:
            validated = TimeInterval.model_validate(interval)
        except Exception:
            return []
        return [validated]

    async def process_post_commit_split_merge(
        self,
        transaction: TransactionResult,
    ) -> list[TimeInterval]:
        """E2 standalone post-commit handling is not an integration API."""
        if not transaction.succeeded:
            return []
        return []
