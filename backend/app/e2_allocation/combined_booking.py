from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import ValidationError

from ..contracts.booking import TimeInterval
from .booking_update import apply_booking_to_cache
from .cache import AvailabilityCache
from .cancellation import cancel_booking_from_cache
from .equipment_allocation import allocate_equipment
from .equipment_cache import EquipmentCache
from .equipment_cancellation import cancel_equipment_booking
from .equipment_models import (
    CombinedAllocationResult,
    CombinedCancellationRequest,
    CombinedCancellationResult,
    EquipmentAllocationRequest,
    EquipmentRequestLine,
)
from .models import AvailabilityStatus


@dataclass(frozen=True)
class CombinedBookingRecord:
    booking_id: UUID
    court_id: UUID
    booking_date: date
    interval: TimeInterval
    items: tuple[EquipmentRequestLine, ...]


class CombinedAllocationCache:
    """Stage and coordinate court/equipment state for standalone E2 operations."""

    def __init__(
        self,
        court_cache: AvailabilityCache,
        equipment_cache: EquipmentCache,
    ) -> None:
        self.court_cache = court_cache
        self.equipment_cache = equipment_cache
        self._bookings: dict[UUID, CombinedBookingRecord] = {}
        self._cancelled: dict[UUID, CombinedBookingRecord] = {}

    def allocate(
        self,
        court_id: UUID,
        booking_date: date,
        interval: TimeInterval,
        booking_id: UUID,
        items: tuple[EquipmentRequestLine, ...] = (),
        current_datetime: datetime | None = None,
    ) -> CombinedAllocationResult:
        try:
            equipment_request = EquipmentAllocationRequest(
                booking_id=booking_id,
                court_id=court_id,
                interval=interval,
                items=tuple(items),
            )
        except (ValidationError, TypeError, ValueError) as error:
            return CombinedAllocationResult(
                succeeded=False,
                booking_id=booking_id,
                errors=[f"Combined booking request is invalid: {error}"],
            )

        if validated_booking_id := equipment_request.booking_id:
            if validated_booking_id in self._cancelled:
                return CombinedAllocationResult(
                    succeeded=False,
                    booking_id=validated_booking_id,
                    errors=[
                        "A booking ID marked cancelled cannot be reused for "
                        "a new combined allocation."
                    ],
                )

        existing_record = self._bookings.get(booking_id)
        if existing_record is not None:
            if (
                existing_record.court_id == court_id
                and existing_record.booking_date == booking_date
                and existing_record.interval == equipment_request.interval
                and existing_record.items == tuple(items)
            ):
                if self._booking_claims_exist(existing_record):
                    return CombinedAllocationResult(
                        succeeded=True,
                        booking_id=booking_id,
                        court_allocated=True,
                        equipment_allocated=bool(items),
                        allocated_items=tuple(items),
                    )
                return CombinedAllocationResult(
                    succeeded=False,
                    booking_id=booking_id,
                    errors=[
                        "A booking record exists, but its court or equipment "
                        "claims are missing or inconsistent."
                    ],
                )
            return CombinedAllocationResult(
                succeeded=False,
                booking_id=booking_id,
                errors=[
                    "A booking already exists for this reference with different data."
                ],
            )

        court_original = self.court_cache.snapshot()
        court_staged = self.court_cache.copy()
        try:
            court_result = apply_booking_to_cache(
                court_id,
                booking_date,
                interval,
                booking_id,
                court_staged,
                current_datetime=current_datetime,
            )
        except Exception as error:
            return CombinedAllocationResult(
                succeeded=False,
                booking_id=booking_id,
                errors=[f"Court staging raised an unexpected error: {error}"],
            )
        if not court_result.valid:
            return CombinedAllocationResult(
                succeeded=False,
                booking_id=booking_id,
                errors=[
                    f"Court allocation failed: {error}"
                    for error in court_result.errors
                ],
            )

        equipment_staged = self.equipment_cache.copy()
        try:
            equipment_result = allocate_equipment(
                equipment_request,
                equipment_staged,
                current_datetime=current_datetime,
            )
        except Exception as error:
            return CombinedAllocationResult(
                succeeded=False,
                booking_id=booking_id,
                errors=[f"Equipment staging raised an unexpected error: {error}"],
            )
        if not equipment_result.succeeded:
            return CombinedAllocationResult(
                succeeded=False,
                booking_id=booking_id,
                shortages=equipment_result.shortages,
                errors=[
                    f"Equipment allocation failed: {error}"
                    for error in equipment_result.errors
                ],
            )

        court_before = court_staged.snapshot()
        equipment_before = self.equipment_cache.snapshot()

        try:
            staged_reservations = equipment_staged.snapshot()
            self.equipment_cache.batch_replace_reservations(staged_reservations)
            self.court_cache.restore_snapshot(court_before)
        except Exception as error:
            self.equipment_cache.restore_reservation_snapshot(equipment_before)
            self.court_cache.restore_snapshot_for_rollback(court_original)
            return CombinedAllocationResult(
                succeeded=False,
                booking_id=booking_id,
                errors=[f"Could not atomically commit combined allocation: {error}"],
            )

        self._bookings[booking_id] = CombinedBookingRecord(
            booking_id=booking_id,
            court_id=court_id,
            booking_date=booking_date,
            interval=equipment_request.interval,
            items=tuple(items),
        )
        self._cancelled.pop(booking_id, None)
        return CombinedAllocationResult(
            succeeded=True,
            booking_id=booking_id,
            court_allocated=True,
            equipment_allocated=bool(items),
            allocated_items=tuple(items),
        )

    def cancel(
        self,
        booking_id: UUID,
        court_id: Optional[UUID] = None,
        booking_date: Optional[date] = None,
    ) -> CombinedCancellationResult:
        try:
            request = CombinedCancellationRequest(
                booking_id=booking_id,
                court_id=court_id,
                booking_date=booking_date,
            )
        except (ValidationError, TypeError, ValueError) as error:
            return CombinedCancellationResult(
                succeeded=False,
                booking_id=booking_id,
                errors=[f"Combined cancellation request is invalid: {error}"],
            )

        cancelled_record = self._cancelled.get(request.booking_id)
        if cancelled_record is not None:
            court_intervals = self.court_cache.get_intervals(
                cancelled_record.court_id,
                cancelled_record.booking_date,
            )
            court_claims = (
                []
                if court_intervals is None
                else [
                    interval
                    for interval in court_intervals
                    if interval.status is AvailabilityStatus.BOOKED
                    and interval.reference_id == request.booking_id
                ]
            )
            equipment_claims = self.equipment_cache.find_reservation_locations(
                request.booking_id
            )
            if court_claims or equipment_claims:
                return CombinedCancellationResult(
                    succeeded=False,
                    booking_id=request.booking_id,
                    errors=[
                        "A cancelled booking reference has been reintroduced "
                        "into court or equipment cache state."
                    ],
                )
            return CombinedCancellationResult(
                succeeded=True,
                booking_id=request.booking_id,
                repeated=True,
            )

        record = self._bookings.get(request.booking_id)
        effective_court_id = record.court_id if record is not None else request.court_id
        effective_date = record.booking_date if record is not None else request.booking_date

        if effective_court_id is None or effective_date is None:
            return CombinedCancellationResult(
                succeeded=False,
                booking_id=request.booking_id,
                errors=[
                    "Court ID and booking date are required when combined "
                    "booking metadata is unavailable."
                ],
            )

        court_intervals = self.court_cache.get_intervals(
            effective_court_id,
            effective_date,
        )
        court_matches = (
            []
            if court_intervals is None
            else [
                interval
                for interval in court_intervals
                if interval.status is AvailabilityStatus.BOOKED
                and interval.reference_id == request.booking_id
            ]
        )
        if len(court_matches) > 1:
            return CombinedCancellationResult(
                succeeded=False,
                booking_id=request.booking_id,
                errors=["Duplicate or ambiguous court booking references detected."],
            )

        equipment_locations = self.equipment_cache.find_reservation_locations(
            request.booking_id
        )
        for locations in equipment_locations.values():
            if len(locations) > 1:
                return CombinedCancellationResult(
                    succeeded=False,
                    booking_id=request.booking_id,
                    errors=[
                        "Duplicate or ambiguous equipment booking references detected."
                    ],
                )

        expected_items = record.items if record is not None else ()
        if record is not None:
            if record.court_id != effective_court_id:
                return CombinedCancellationResult(
                    succeeded=False,
                    booking_id=request.booking_id,
                    errors=["Court allocation does not match combined booking metadata."],
                )
            if record.booking_date != effective_date:
                return CombinedCancellationResult(
                    succeeded=False,
                    booking_id=request.booking_id,
                    errors=["Booking date does not match combined booking metadata."],
                )

        if record is not None and bool(record.items) and not equipment_locations:
            return CombinedCancellationResult(
                succeeded=False,
                booking_id=request.booking_id,
                errors=[
                    "Court allocation exists but associated equipment "
                    "reservations are missing."
                ],
            )
        if record is not None and not record.items and equipment_locations:
            return CombinedCancellationResult(
                succeeded=False,
                booking_id=request.booking_id,
                errors=[
                    "Court-only booking metadata conflicts with existing "
                    "equipment reservations."
                ],
            )

        if not court_matches and equipment_locations:
            return CombinedCancellationResult(
                succeeded=False,
                booking_id=request.booking_id,
                errors=[
                    "Equipment reservations exist but the corresponding "
                    "court allocation is missing."
                ],
            )
        if not court_matches and not equipment_locations:
            return CombinedCancellationResult(
                succeeded=False,
                booking_id=request.booking_id,
                errors=["Booking ID was not found in court or equipment state."],
            )

        if record is not None and record.items:
            actual_items: dict[UUID, tuple[TimeInterval, int]] = {}
            for key, matches in equipment_locations.items():
                reservation = matches[0]
                if reservation.equipment_id in actual_items:
                    return CombinedCancellationResult(
                        succeeded=False,
                        booking_id=request.booking_id,
                        errors=["Duplicate equipment IDs found for booking reference."],
                    )
                actual_items[reservation.equipment_id] = (
                    reservation.interval,
                    reservation.quantity,
                )
            expected_items_by_id = {
                item.equipment_id: (record.interval, item.quantity)
                for item in expected_items
            }
            if actual_items != expected_items_by_id:
                return CombinedCancellationResult(
                    succeeded=False,
                    booking_id=request.booking_id,
                    errors=[
                        "Equipment reservations are inconsistent with combined "
                        "booking metadata."
                    ],
                )

        court_original = self.court_cache.snapshot()
        court_staged = self.court_cache.copy()
        if court_matches:
            try:
                court_result = cancel_booking_from_cache(
                    effective_court_id,
                    effective_date,
                    request.booking_id,
                    court_staged,
                )
            except Exception as error:
                return CombinedCancellationResult(
                    succeeded=False,
                    booking_id=request.booking_id,
                    errors=[f"Court cancellation staging raised an error: {error}"],
                )
            if not court_result.valid:
                return CombinedCancellationResult(
                    succeeded=False,
                    booking_id=request.booking_id,
                    errors=[
                        f"Court cancellation failed: {error}"
                        for error in court_result.errors
                    ],
                )

        equipment_staged = self.equipment_cache.copy()
        try:
            equipment_result = cancel_equipment_booking(
                request.booking_id,
                equipment_staged,
            )
        except Exception as error:
            return CombinedCancellationResult(
                succeeded=False,
                booking_id=request.booking_id,
                errors=[f"Equipment cancellation staging raised an error: {error}"],
            )
        if equipment_locations and not equipment_result.succeeded:
            return CombinedCancellationResult(
                succeeded=False,
                booking_id=request.booking_id,
                errors=[
                    f"Equipment cancellation failed: {error}"
                    for error in equipment_result.errors
                ],
            )

        court_snapshot = court_staged.snapshot()
        equipment_original = self.equipment_cache.snapshot()

        try:
            staged_equipment = equipment_staged.snapshot()
            self.equipment_cache.batch_replace_reservations(staged_equipment)
            if court_matches:
                self.court_cache.restore_snapshot(court_snapshot)
        except Exception as error:
            self.equipment_cache.restore_reservation_snapshot(equipment_original)
            self.court_cache.restore_snapshot_for_rollback(court_original)
            return CombinedCancellationResult(
                succeeded=False,
                booking_id=request.booking_id,
                errors=[
                    f"Could not atomically commit combined cancellation: {error}"
                ],
            )

        tombstone_items = (
            tuple(
                EquipmentRequestLine(
                    equipment_id=reservation.equipment_id,
                    quantity=reservation.quantity,
                )
                for key_matches in equipment_locations.values()
                for reservation in key_matches
            )
            if equipment_locations
            else ()
        )
        tombstone_interval = (
            record.interval
            if record is not None
            else (
                court_matches[0].interval
                if court_matches
                else next(
                    iter(equipment_locations.values())
                )[0].interval
            )
        )
        self._cancelled[request.booking_id] = CombinedBookingRecord(
            booking_id=request.booking_id,
            court_id=effective_court_id,
            booking_date=effective_date,
            interval=tombstone_interval,
            items=tombstone_items,
        )
        self._bookings.pop(request.booking_id, None)
        return CombinedCancellationResult(
            succeeded=True,
            booking_id=request.booking_id,
            court_cancelled=bool(court_matches),
            equipment_cancelled=bool(equipment_locations),
            cancelled_equipment_reservation_count=(
                equipment_result.cancelled_reservation_count
                if equipment_locations
                else 0
            ),
        )

    def _booking_claims_exist(self, record: CombinedBookingRecord) -> bool:
        court_intervals = self.court_cache.get_intervals(
            record.court_id,
            record.booking_date,
        )
        if court_intervals is None:
            return False
        court_matches = [
            interval
            for interval in court_intervals
            if interval.status is AvailabilityStatus.BOOKED
            and interval.reference_id == record.booking_id
        ]
        if len(court_matches) != 1:
            return False
        if court_matches[0].interval != record.interval:
            return False

        if not record.items:
            return not self.equipment_cache.find_reservation_locations(
                record.booking_id
            )

        locations = self.equipment_cache.find_reservation_locations(
            record.booking_id
        )
        if len(locations) != len(record.items):
            return False
        for item in record.items:
            matches = [
                reservation
                for key_matches in locations.values()
                for reservation in key_matches
                if reservation.equipment_id == item.equipment_id
            ]
            if len(matches) != 1:
                return False
            if matches[0].quantity != item.quantity:
                return False
            if matches[0].interval != record.interval:
                return False
        return True
