from uuid import UUID

from pydantic import ValidationError

from ..contracts.booking import TimeInterval
from .equipment_cache import EquipmentCache
from .equipment_interval_utils import (
    calculate_equipment_availability_segments,
    get_minimum_available_quantity,
)
from .equipment_models import (
    EquipmentAvailabilityResult,
    EquipmentShortage,
)


def get_equipment_availability(
    equipment_id: UUID,
    requested_interval: TimeInterval,
    equipment_cache: EquipmentCache,
    requested_quantity: int = 1,
) -> EquipmentAvailabilityResult:
    try:
        interval = TimeInterval.model_validate(requested_interval)
    except ValidationError as error:
        reason = error.errors()[0]["msg"]
        return EquipmentAvailabilityResult(
            equipment_id=equipment_id,
            interval=None,
            total_inventory=0,
            valid=False,
            errors=[f"Requested equipment interval is invalid: {reason}"],
        )

    if interval.start.utcoffset() is not None or interval.end.utcoffset() is not None:
        return EquipmentAvailabilityResult(
            equipment_id=equipment_id,
            interval=None,
            total_inventory=0,
            available_quantity=0,
            valid=False,
            errors=["Requested equipment datetimes must be naive venue-local values."],
        )

    if interval.start.date() != interval.end.date():
        return EquipmentAvailabilityResult(
            equipment_id=equipment_id,
            interval=None,
            total_inventory=0,
            available_quantity=0,
            valid=False,
            errors=["Requested equipment interval must be contained within one date."],
        )

    start_minute = interval.start.hour * 60 + interval.start.minute
    end_minute = interval.end.hour * 60 + interval.end.minute
    if start_minute < 6 * 60 or end_minute > 20 * 60:
        return EquipmentAvailabilityResult(
            equipment_id=equipment_id,
            interval=None,
            total_inventory=0,
            available_quantity=0,
            valid=False,
            errors=[
                "Requested equipment interval must be within equipment "
                "operating hours (06:00-20:00)."
            ],
        )

    if isinstance(requested_quantity, bool) or not isinstance(requested_quantity, int):
        return EquipmentAvailabilityResult(
            equipment_id=equipment_id,
            interval=interval,
            total_inventory=0,
            valid=False,
            errors=["Requested quantity must be a positive integer."],
        )
    if requested_quantity <= 0:
        return EquipmentAvailabilityResult(
            equipment_id=equipment_id,
            interval=interval,
            total_inventory=0,
            valid=False,
            errors=["Requested quantity must be a positive integer."],
        )

    inventory = equipment_cache.get_inventory(equipment_id)
    if inventory is None:
        return EquipmentAvailabilityResult(
            equipment_id=equipment_id,
            interval=interval,
            total_inventory=0,
            available_quantity=0,
            valid=False,
            errors=["Inventory is missing for the equipment."],
            shortages=[
                EquipmentShortage(
                    equipment_id=equipment_id,
                    requested_quantity=requested_quantity,
                    available_quantity=0,
                )
            ],
        )

    reservations = equipment_cache.get_reservations(
        equipment_id,
        interval.start.date(),
    ) or []
    segments = calculate_equipment_availability_segments(
        inventory.total_quantity,
        reservations,
        interval,
    )
    minimum_available = get_minimum_available_quantity(segments)
    shortages = []
    if minimum_available < requested_quantity:
        shortages.append(
            EquipmentShortage(
                equipment_id=equipment_id,
                requested_quantity=requested_quantity,
                available_quantity=minimum_available,
            )
        )

    return EquipmentAvailabilityResult(
        equipment_id=equipment_id,
        interval=interval,
        total_inventory=inventory.total_quantity,
        segments=segments,
        available_quantity=minimum_available,
        valid=minimum_available >= requested_quantity,
        shortages=shortages,
        errors=[] if minimum_available >= requested_quantity else [
            f"Insufficient equipment {equipment_id}: requested "
            f"{requested_quantity}, available {minimum_available}."
        ],
    )
