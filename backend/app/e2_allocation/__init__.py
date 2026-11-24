"""E2 allocation and conflict engine package."""

from ..contracts.booking import (
    BookingRequest,
    BookingResponse,
    ErrorCode,
    LockToken,
    TimeInterval,
    TransactionResult,
    ValidationResult,
)
from .availability_generation import (
    CommittedBooking,
    EffectiveCourtBlock,
    populate_seven_day_availability,
)
from .block_update import apply_block_to_cache
from .booking_update import apply_booking_to_cache
from .cache import AvailabilityCache
from .cancellation import cancel_booking_from_cache
from .equipment_allocation import allocate_equipment
from .equipment_availability import get_equipment_availability
from .equipment_cache import EquipmentCache
from .equipment_cancellation import cancel_equipment_booking
from .equipment_models import (
    CombinedAllocationResult,
    CombinedCancellationRequest,
    CombinedCancellationResult,
    EquipmentAllocationRequest,
    EquipmentAllocationResult,
    EquipmentAvailabilityResult,
    EquipmentAvailabilitySegment,
    EquipmentCancellationRequest,
    EquipmentCancellationResult,
    EquipmentInventory,
    EquipmentRequestLine,
    EquipmentReservation,
    EquipmentShortage,
    EquipmentValidationResult,
)
from .equipment_validation import (
    validate_equipment_interval,
    validate_equipment_request,
)
from .combined_booking import CombinedAllocationCache
from .interval_utils import (
    find_interval_containing,
    sort_availability_intervals,
)
from .models import (
    AvailabilityInterval,
    AvailabilityStatus,
    CourtAvailabilityKey,
)
from .service import AllocationService
from .validation import (
    validate_block_availability,
    validate_booking_availability,
)

__all__ = [
    "AllocationService",
    "AvailabilityCache",
    "AvailabilityInterval",
    "AvailabilityStatus",
    "BookingRequest",
    "BookingResponse",
    "CombinedAllocationCache",
    "CombinedAllocationResult",
    "CombinedCancellationRequest",
    "CombinedCancellationResult",
    "EquipmentAllocationRequest",
    "EquipmentAllocationResult",
    "EquipmentAvailabilityResult",
    "EquipmentAvailabilitySegment",
    "EquipmentCancellationRequest",
    "EquipmentCancellationResult",
    "EquipmentCache",
    "EquipmentInventory",
    "EquipmentRequestLine",
    "EquipmentReservation",
    "EquipmentShortage",
    "EquipmentValidationResult",
    "CommittedBooking",
    "EffectiveCourtBlock",
    "ErrorCode",
    "LockToken",
    "TimeInterval",
    "TransactionResult",
    "ValidationResult",
    "CourtAvailabilityKey",
    "allocate_equipment",
    "apply_block_to_cache",
    "apply_booking_to_cache",
    "cancel_booking_from_cache",
    "cancel_equipment_booking",
    "find_interval_containing",
    "get_equipment_availability",
    "populate_seven_day_availability",
    "sort_availability_intervals",
    "validate_block_availability",
    "validate_booking_availability",
    "validate_equipment_interval",
    "validate_equipment_request",
]
