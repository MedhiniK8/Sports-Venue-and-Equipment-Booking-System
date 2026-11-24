from datetime import datetime

from pydantic import ValidationError

from .equipment_cache import EquipmentCache
from .equipment_models import (
    EquipmentAllocationRequest,
    EquipmentAllocationResult,
    EquipmentReservation,
)
from .equipment_validation import validate_equipment_request


def allocate_equipment(
    request: EquipmentAllocationRequest,
    equipment_cache: EquipmentCache,
    current_datetime: datetime | None = None,
) -> EquipmentAllocationResult:
    try:
        validated_request = EquipmentAllocationRequest.model_validate(request)
    except ValidationError as error:
        reason = error.errors()[0]["msg"]
        return EquipmentAllocationResult(
            succeeded=False,
            booking_id=getattr(request, "booking_id", None)
            or getattr(request, "booking_id", None),
            errors=[f"Equipment request is invalid: {reason}"],
        )

    validation = validate_equipment_request(
        validated_request,
        equipment_cache,
        current_datetime=current_datetime,
    )
    if not validation.valid:
        return EquipmentAllocationResult(
            succeeded=False,
            booking_id=validated_request.booking_id,
            shortages=validation.shortages,
            errors=validation.errors,
        )

    existing = equipment_cache.get_reservations_for_booking(
        validated_request.booking_id
    )
    if existing:
        if _is_exact_retry(validated_request, existing):
            return EquipmentAllocationResult(
                succeeded=True,
                booking_id=validated_request.booking_id,
                allocated_items=validated_request.items,
                reservations=tuple(existing),
            )
        return EquipmentAllocationResult(
            succeeded=False,
            booking_id=validated_request.booking_id,
            errors=[
                "A reservation already exists for this booking reference "
                "and is inconsistent with the retry request."
            ],
        )

    if not validated_request.items:
        return EquipmentAllocationResult(
            succeeded=True,
            booking_id=validated_request.booking_id,
            allocated_items=(),
            reservations=(),
        )

    booking_date = validated_request.interval.start.date()
    replacements: dict[
        tuple,
        list[EquipmentReservation],
    ] = {}
    reservations: list[EquipmentReservation] = []

    for item in validated_request.items:
        key = (item.equipment_id, booking_date)
        existing_for_item = replacements.get(key)
        if existing_for_item is None:
            existing_for_item = equipment_cache.get_reservations(
                item.equipment_id,
                booking_date,
            ) or []

        reservation = EquipmentReservation(
            equipment_id=item.equipment_id,
            booking_id=validated_request.booking_id,
            interval=validated_request.interval,
            quantity=item.quantity,
        )
        staged = list(existing_for_item)
        staged.append(reservation)
        replacements[key] = staged
        reservations.append(reservation)

    try:
        equipment_cache.batch_replace_reservations(replacements)
    except (TypeError, ValueError) as error:
        return EquipmentAllocationResult(
            succeeded=False,
            booking_id=validated_request.booking_id,
            errors=[f"Could not stage equipment allocation: {error}"],
        )

    return EquipmentAllocationResult(
        succeeded=True,
        booking_id=validated_request.booking_id,
        allocated_items=validated_request.items,
        reservations=tuple(
            sorted(
                reservations,
                key=lambda reservation: (
                    str(reservation.equipment_id),
                    reservation.interval.start,
                ),
            )
        ),
    )


def _is_exact_retry(
    request: EquipmentAllocationRequest,
    existing: list[EquipmentReservation],
) -> bool:
    if len(existing) != len(request.items):
        return False

    requested = {
        item.equipment_id: item.quantity
        for item in request.items
    }
    existing_quantities: dict = {}
    for reservation in existing:
        if reservation.booking_id != request.booking_id:
            return False
        if reservation.interval != request.interval:
            return False
        if reservation.equipment_id in existing_quantities:
            return False
        existing_quantities[reservation.equipment_id] = reservation.quantity

    return existing_quantities == requested
