from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ..contracts.booking import TimeInterval


class EquipmentInventory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equipment_id: UUID
    total_quantity: StrictInt = Field(ge=0)


class EquipmentRequestLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equipment_id: UUID
    quantity: StrictInt = Field(gt=0)


class EquipmentReservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equipment_id: UUID
    booking_id: UUID
    interval: TimeInterval
    quantity: StrictInt = Field(gt=0)

    @model_validator(mode="after")
    def validate_same_day(self) -> "EquipmentReservation":
        if self.interval.start.date() != self.interval.end.date():
            raise ValueError("equipment reservation must be contained within one date")
        if self.interval.start.utcoffset() is not None or self.interval.end.utcoffset() is not None:
            raise ValueError("equipment reservation datetimes must be naive venue-local values")
        return self


class EquipmentAllocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    booking_id: UUID
    court_id: Optional[UUID] = None
    interval: TimeInterval
    items: tuple[EquipmentRequestLine, ...] = ()

    @model_validator(mode="after")
    def validate_unique_items(self) -> "EquipmentAllocationRequest":
        equipment_ids = [item.equipment_id for item in self.items]
        if len(set(equipment_ids)) != len(equipment_ids):
            raise ValueError("equipment request must not contain duplicate equipment IDs")
        return self


class EquipmentCancellationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    booking_id: UUID
    equipment_id: Optional[UUID] = None


class EquipmentShortage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equipment_id: UUID
    requested_quantity: StrictInt = Field(gt=0)
    available_quantity: StrictInt = Field(ge=0)


class EquipmentAvailabilitySegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interval: TimeInterval
    reserved_quantity: StrictInt = Field(ge=0)
    available_quantity: StrictInt = Field(ge=0)


class EquipmentValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: list[str] = Field(default_factory=list)
    shortages: list[EquipmentShortage] = Field(default_factory=list)


class EquipmentAllocationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    succeeded: bool
    booking_id: Optional[UUID] = None
    allocated_items: tuple[EquipmentRequestLine, ...] = ()
    shortages: list[EquipmentShortage] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    reservations: tuple[EquipmentReservation, ...] = ()


class EquipmentCancellationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    succeeded: bool
    booking_id: UUID
    equipment_id: Optional[UUID] = None
    cancelled_reservation_count: int = Field(default=0, ge=0)
    errors: list[str] = Field(default_factory=list)


class EquipmentAvailabilityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equipment_id: UUID
    interval: Optional[TimeInterval] = None
    total_inventory: StrictInt = Field(ge=0)
    segments: list[EquipmentAvailabilitySegment] = Field(default_factory=list)
    available_quantity: StrictInt = Field(ge=0)
    valid: bool = True
    shortages: list[EquipmentShortage] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class CombinedCancellationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    booking_id: UUID
    court_id: Optional[UUID] = None
    booking_date: Optional[date] = None


class CombinedAllocationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    succeeded: bool
    booking_id: UUID
    court_allocated: bool = False
    equipment_allocated: bool = False
    allocated_items: tuple[EquipmentRequestLine, ...] = ()
    shortages: list[EquipmentShortage] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class CombinedCancellationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    succeeded: bool
    booking_id: Optional[UUID] = None
    court_cancelled: bool = False
    equipment_cancelled: bool = False
    cancelled_equipment_reservation_count: int = Field(default=0, ge=0)
    repeated: bool = False
    errors: list[str] = Field(default_factory=list)


EquipmentAvailabilityKey = tuple[UUID, date]
