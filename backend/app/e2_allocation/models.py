from datetime import date
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from ..contracts.booking import TimeInterval


class AvailabilityStatus(str, Enum):
    FREE = "FREE"
    BOOKED = "BOOKED"
    BLOCKED = "BLOCKED"


class AvailabilityInterval(BaseModel):
    """An interval with its derived availability status."""

    model_config = ConfigDict(extra="forbid")

    interval: TimeInterval
    status: AvailabilityStatus
    reference_id: Optional[UUID] = None

    @model_validator(mode="after")
    def validate_reference(self) -> "AvailabilityInterval":
        if self.status == AvailabilityStatus.FREE and self.reference_id is not None:
            raise ValueError("FREE intervals cannot have a reference ID")
        return self


CourtAvailabilityKey = tuple[UUID, date]
AvailabilityCache = dict[CourtAvailabilityKey, list[AvailabilityInterval]]
