from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from ..e3_persistence.inputs import BookingStatus


EquipmentDecision = Literal[
    "CONTINUE_WITHOUT_EQUIPMENT",
    "CANCEL_REQUEST",
]


class StudentRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_name: str = Field(min_length=1, max_length=100)
    college_email: EmailStr
    usn: str = Field(min_length=1, max_length=50)
    phone_number: str = Field(min_length=1, max_length=32)
    branch: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)

    @field_validator("student_name", "usn", "phone_number", "branch", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("college_email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @model_validator(mode="after")
    def passwords_match(self) -> "StudentRegistrationRequest":
        if self.password != self.confirm_password:
            raise ValueError("password and confirm_password must match")
        return self


class StudentLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("identifier", mode="before")
    @classmethod
    def strip_identifier(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class StudentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    student_name: str
    usn: str
    college_email: EmailStr
    phone_number: str
    year_of_admission: int | None = None
    gender: str | None = None
    branch: str
    role: Literal["STUDENT", "ADMIN"] = "STUDENT"


class StudentProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_name: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("student_name", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def reject_empty_update(self) -> "StudentProfileUpdateRequest":
        if self.student_name is None:
            raise ValueError("student_name must be provided")
        return self


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def passwords_match(self) -> "ChangePasswordRequest":
        if self.new_password != self.confirm_password:
            raise ValueError("new_password and confirm_password must match")
        return self


class SportCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sport_id: UUID
    name: str


class CourtCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    court_id: UUID
    name: str


class EquipmentCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equipment_id: UUID
    name: str


CourtAvailabilityStatus = Literal["FREE", "BOOKED", "BLOCKED"]


class CourtAvailabilityIntervalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_time: time
    end_time: time
    status: CourtAvailabilityStatus
    is_mine: bool = False


class CourtAvailabilityDayResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    intervals: tuple[CourtAvailabilityIntervalResponse, ...]


class CourtAvailabilityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    court_id: UUID
    reference_date: date
    timezone: Literal["Asia/Kolkata"] = "Asia/Kolkata"
    opening_time: time
    closing_time: time
    days: tuple[CourtAvailabilityDayResponse, ...]


class EquipmentAvailabilityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equipment_id: UUID
    name: str
    total_quantity: int
    allocated_quantity: int
    remaining_quantity: int


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class StudentEquipmentLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equipment_id: UUID
    quantity: StrictInt = Field(gt=0)


class StudentBookingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    court_id: UUID
    booking_date: date
    start_time: time
    end_time: time
    equipment: tuple[StudentEquipmentLine, ...] = ()
    equipment_decision: EquipmentDecision | None = None

    @model_validator(mode="after")
    def validate_booking_interval(self) -> "StudentBookingRequest":
        if self.start_time.tzinfo is not None or self.end_time.tzinfo is not None:
            raise ValueError("Booking times must be venue-local and timezone-naive")
        if self.start_time.second or self.end_time.second:
            raise ValueError("Booking times must use one-minute precision")
        if self.start_time.microsecond or self.end_time.microsecond:
            raise ValueError("Booking times must use one-minute precision")
        if self.start_time >= self.end_time:
            raise ValueError("end_time must be after start_time on the same date")
        equipment_ids = [item.equipment_id for item in self.equipment]
        if len(set(equipment_ids)) != len(equipment_ids):
            raise ValueError("Equipment IDs must not be repeated")
        return self


class StudentBookingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    booking_id: UUID
    court_id: UUID
    booking_date: date
    start_time: time
    end_time: time
    status: BookingStatus
    equipment: tuple[StudentEquipmentLine, ...]


class EquipmentShortageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equipment_id: UUID
    requested_quantity: StrictInt = Field(gt=0)
    available_quantity: StrictInt = Field(ge=0)


class EquipmentDecisionRequiredResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Literal["EQUIPMENT_DECISION_REQUIRED"] = "EQUIPMENT_DECISION_REQUIRED"
    message: str = "Choose whether to continue without unavailable equipment or cancel."
    shortages: tuple[EquipmentShortageResponse, ...]
    permitted_decisions: tuple[EquipmentDecision, EquipmentDecision] = (
        "CONTINUE_WITHOUT_EQUIPMENT",
        "CANCEL_REQUEST",
    )


class BookingRequestCancelledResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Literal["BOOKING_NOT_CREATED"] = "BOOKING_NOT_CREATED"
    request_cancelled: Literal[True] = True
    booking_created: Literal[False] = False
    message: str = "Request cancelled; no booking was created."


class BlockOutCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    court_id: UUID
    starts_at: datetime
    ends_at: datetime
    reason: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_interval(self) -> "BlockOutCreateRequest":
        if self.starts_at.tzinfo is not None or self.ends_at.tzinfo is not None:
            raise ValueError("Block-out times must be timezone-naive")
        if self.starts_at >= self.ends_at:
            raise ValueError("ends_at must be after starts_at")
        if self.starts_at.date() != self.ends_at.date():
            raise ValueError("Block-outs must remain within one date")
        if self.starts_at.second or self.ends_at.second:
            raise ValueError("Block-outs must use minute precision")
        return self


class BlockOutUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starts_at: datetime
    ends_at: datetime
    reason: str | None = Field(default=None, max_length=255)
    is_active: bool = True


class BlockOutResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_out_id: UUID
    court_id: UUID
    starts_at: datetime
    ends_at: datetime
    reason: str | None
    is_active: bool
