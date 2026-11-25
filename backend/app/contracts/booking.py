
from datetime import date, datetime, time
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
    """Booking details received from the frontend."""

    model_config = ConfigDict(extra="forbid")

    court_id: UUID
    equipment_id: Optional[UUID] = None
    date: date
    starting_time: time
    ending_time: time

    @model_validator(mode="after")
    def validate_booking_time(self) -> "BookingRequest":
        if self.starting_time.second != 0 or self.starting_time.microsecond != 0:
            raise ValueError("starting_time must use one-minute precision")

        if self.ending_time.second != 0 or self.ending_time.microsecond != 0:
            raise ValueError("ending_time must use one-minute precision")

        if self.ending_time <= self.starting_time:
            raise ValueError("ending_time must be after starting_time")

        return self

    @property
    def interval(self) -> TimeInterval:
        """Convert the frontend date and times into a datetime interval."""

        start = datetime.combine(self.date, self.starting_time)
        end = datetime.combine(self.date, self.ending_time)

        return TimeInterval(start=start, end=end)


class BookingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    booking_id: UUID
    status: str
    court_id: UUID
    equipment_id: Optional[UUID] = None
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
    booking_id: Optional[UUID] = None
    transaction_id: Optional[UUID] = None
    error_code: Optional[str] = None


class ErrorCode(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_INTERVAL = "INVALID_INTERVAL"
    LOCK_NOT_AVAILABLE = "LOCK_NOT_AVAILABLE"
    TRANSACTION_FAILED = "TRANSACTION_FAILED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
