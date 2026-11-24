from uuid import UUID

from pydantic import ValidationError

from .equipment_cache import EquipmentCache
from .equipment_models import (
    EquipmentCancellationRequest,
    EquipmentCancellationResult,
)


def cancel_equipment_booking(
    booking_id: UUID,
    equipment_cache: EquipmentCache,
    equipment_id: UUID | None = None,
) -> EquipmentCancellationResult:
    try:
        request = EquipmentCancellationRequest(
            booking_id=booking_id,
            equipment_id=equipment_id,
        )
    except ValidationError as error:
        reason = error.errors()[0]["msg"]
        return EquipmentCancellationResult(
            succeeded=False,
            booking_id=booking_id,
            equipment_id=equipment_id,
            errors=[f"Equipment cancellation request is invalid: {reason}"],
        )

    locations = equipment_cache.find_reservation_locations(
        request.booking_id,
        request.equipment_id,
    )
    if not locations:
        return EquipmentCancellationResult(
            succeeded=False,
            booking_id=request.booking_id,
            equipment_id=request.equipment_id,
            errors=["No equipment reservations were found for the booking reference."],
        )

    replacements: dict[tuple, list] = {}
    cancelled_count = 0

    for key, matches in locations.items():
        if len(matches) > 1:
            return EquipmentCancellationResult(
                succeeded=False,
                booking_id=request.booking_id,
                equipment_id=request.equipment_id,
                errors=[
                    "Equipment booking reference is ambiguous for one "
                    "equipment/date cache entry."
                ],
            )
        equipment_id_for_key, booking_date = key
        existing = equipment_cache.get_reservations(
            equipment_id_for_key,
            booking_date,
        ) or []
        replacements[key] = [
            reservation
            for reservation in existing
            if not (
                reservation.booking_id == request.booking_id
                and (
                    request.equipment_id is None
                    or reservation.equipment_id == request.equipment_id
                )
            )
        ]
        cancelled_count += len(matches)

    try:
        equipment_cache.batch_replace_reservations(replacements)
    except (TypeError, ValueError) as error:
        return EquipmentCancellationResult(
            succeeded=False,
            booking_id=request.booking_id,
            equipment_id=request.equipment_id,
            errors=[f"Could not stage equipment cancellation: {error}"],
        )

    return EquipmentCancellationResult(
        succeeded=True,
        booking_id=request.booking_id,
        equipment_id=request.equipment_id,
        cancelled_reservation_count=cancelled_count,
    )
