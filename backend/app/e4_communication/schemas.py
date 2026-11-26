from datetime import date, time
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

    usn: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)
    college_email: EmailStr
    phone_number: str = Field(min_length=1, max_length=32)
    year_of_admission: int = Field(gt=0)
    gender: str = Field(min_length=1, max_length=32)
    branch: str = Field(min_length=1, max_length=100)

    @field_validator("usn", "phone_number", "gender", "branch", mode="before")
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

    usn: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("usn", mode="before")
    @classmethod
    def strip_usn(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class StudentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    usn: str
    college_email: EmailStr
    phone_number: str
    year_of_admission: int
    gender: str
    branch: str


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
