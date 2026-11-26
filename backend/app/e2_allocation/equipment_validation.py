from datetime import datetime
from uuid import UUID

from pydantic import ValidationError

from ..contracts.booking import TimeInterval
from ..venue_time import current_venue_local_naive
from .equipment_cache import EquipmentCache
from .equipment_interval_utils import (
    calculate_equipment_availability_segments,
    get_minimum_available_quantity,
)
from .equipment_models import (
    EquipmentAllocationRequest,
    EquipmentShortage,
    EquipmentValidationResult,
)


_OPENING_MINUTE = 6 * 60
_CLOSING_MINUTE = 20 * 60


def validate_equipment_interval(
    requested_interval: TimeInterval,
    booking_date,
    current_datetime: datetime | None = None,
) -> EquipmentValidationResult:
    try:
        interval = TimeInterval.model_validate(
            {
                "start": requested_interval.start,
                "end": requested_interval.end,
            }
        )
    except ValidationError as error:
        reason = error.errors()[0]["msg"]
        return EquipmentValidationResult(
            valid=False,
            errors=[f"Requested equipment interval is invalid: {reason}"],
        )

    if interval.start.utcoffset() is not None or interval.end.utcoffset() is not None:
        return EquipmentValidationResult(
            valid=False,
            errors=["Requested equipment datetimes must be naive venue-local values."],
        )

    if interval.start.date() != booking_date or interval.end.date() != booking_date:
        return EquipmentValidationResult(
            valid=False,
            errors=["Requested equipment interval must be on the selected booking date."],
        )

    start_minute = interval.start.hour * 60 + interval.start.minute
    end_minute = interval.end.hour * 60 + interval.end.minute
    if start_minute < _OPENING_MINUTE or end_minute > _CLOSING_MINUTE:
        return EquipmentValidationResult(
            valid=False,
            errors=[
                "Requested equipment interval must be within equipment operating "
                "hours (06:00-20:00)."
            ],
        )

    now = (
        current_datetime
        if current_datetime is not None
        else current_venue_local_naive()
    )
    if now.utcoffset() is not None:
        return EquipmentValidationResult(
            valid=False,
            errors=["Current datetime must be a naive venue-local value."],
        )
    if booking_date < now.date():
        return EquipmentValidationResult(
            valid=False,
            errors=["Requested equipment booking date is in the past."],
        )
    if interval.start <= now:
        return EquipmentValidationResult(
            valid=False,
            errors=["Requested equipment interval has already started or passed."],
        )

    return EquipmentValidationResult(valid=True)


def validate_equipment_request(
    request: EquipmentAllocationRequest,
    equipment_cache: EquipmentCache,
    current_datetime: datetime | None = None,
) -> EquipmentValidationResult:
    try:
        validated_request = EquipmentAllocationRequest.model_validate(request)
    except ValidationError as error:
        reason = error.errors()[0]["msg"]
        return EquipmentValidationResult(
            valid=False,
            errors=[f"Equipment request is invalid: {reason}"],
        )

    interval_validation = validate_equipment_interval(
        validated_request.interval,
        validated_request.interval.start.date(),
        current_datetime=current_datetime,
    )
    if not interval_validation.valid:
        return interval_validation

    if not validated_request.items:
        return EquipmentValidationResult(valid=True)

    shortages: list[EquipmentShortage] = []
    errors: list[str] = []
    booking_date = validated_request.interval.start.date()

    for item in validated_request.items:
        inventory = equipment_cache.get_inventory(item.equipment_id)
        if inventory is None:
            shortages.append(
                EquipmentShortage(
                    equipment_id=item.equipment_id,
                    requested_quantity=item.quantity,
                    available_quantity=0,
                )
            )
            errors.append(
                f"Inventory is missing for equipment {item.equipment_id}."
            )
            continue

        reservations = equipment_cache.get_reservations(
            item.equipment_id,
            booking_date,
        ) or []
        segments = calculate_equipment_availability_segments(
            inventory.total_quantity,
            reservations,
            validated_request.interval,
        )
        minimum_available = get_minimum_available_quantity(segments)

        if minimum_available < item.quantity:
            shortages.append(
                EquipmentShortage(
                    equipment_id=item.equipment_id,
                    requested_quantity=item.quantity,
                    available_quantity=minimum_available,
                )
            )
            errors.append(
                f"Insufficient equipment {item.equipment_id}: requested "
                f"{item.quantity}, available {minimum_available}."
            )

    if errors:
        return EquipmentValidationResult(
            valid=False,
            errors=errors,
            shortages=shortages,
        )
    return EquipmentValidationResult(valid=True)
