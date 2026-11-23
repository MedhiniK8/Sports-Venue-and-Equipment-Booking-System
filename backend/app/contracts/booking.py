from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TimeInterval(BaseModel):
    """A half-open interval: [start, end)."""

    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_interval(self) -> "TimeInterval":
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if self.start.second != 0 or self.start.microsecond != 0:
            raise ValueError("start must use one-minute precision")
        if self.end.second != 0 or self.end.microsecond != 0:
            raise ValueError("end must use one-minute precision")
        return self


class BookingRequest(BaseModel):
    """Client request; user identity is intentionally not accepted."""

    model_config = ConfigDict(extra="forbid")

    venue_id: UUID
    equipment_id: Optional[UUID] = None
    interval: TimeInterval


class BookingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    booking_id: UUID
    status: str
    interval: TimeInterval


class LockToken(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: UUID
    interval: TimeInterval


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: list[str] = Field(default_factory=list)


class TransactionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    succeeded: bool
    transaction_id: Optional[UUID] = None
    error_code: Optional[str] = None


class ErrorCode(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_INTERVAL = "INVALID_INTERVAL"
    LOCK_NOT_AVAILABLE = "LOCK_NOT_AVAILABLE"
    TRANSACTION_FAILED = "TRANSACTION_FAILED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
