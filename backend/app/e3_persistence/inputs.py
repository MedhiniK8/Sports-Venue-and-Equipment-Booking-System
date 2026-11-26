from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Literal
from uuid import UUID


BookingStatus = Literal["BOOKED", "CANCELLED"]


@dataclass(frozen=True)
class CreateStudentInput:
    usn: str
    password_hash: str
    college_email: str
    phone_number: str
    year_of_admission: int
    gender: str
    branch: str


@dataclass(frozen=True)
class StudentAccountRecord:
    user_id: UUID
    usn: str
    password_hash: str
    college_email: str
    phone_number: str
    year_of_admission: int
    gender: str
    branch: str


@dataclass(frozen=True)
class SportCatalogRecord:
    sport_id: UUID
    name: str


@dataclass(frozen=True)
class CourtCatalogRecord:
    court_id: UUID
    name: str


@dataclass(frozen=True)
class EquipmentCatalogRecord:
    equipment_id: UUID
    name: str


@dataclass(frozen=True)
class BookingEquipmentLine:
    equipment_id: UUID
    quantity: int


@dataclass(frozen=True)
class CreateBookingInput:
    booking_id: UUID
    user_id: UUID
    court_id: UUID
    booking_date: date
    start_time: time
    end_time: time
    items: tuple[BookingEquipmentLine, ...] = ()


@dataclass(frozen=True)
class BookingRecord:
    booking_id: UUID
    user_id: UUID
    court_id: UUID
    booking_date: date
    start_time: time
    end_time: time
    status: BookingStatus
    items: tuple[BookingEquipmentLine, ...] = ()


@dataclass(frozen=True)
class BookingSnapshotRecord:
    booking_id: UUID
    court_id: UUID
    booking_date: date
    start_time: time
    end_time: time


@dataclass(frozen=True)
class BlockOutSnapshotRecord:
    block_out_id: UUID
    court_id: UUID
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True)
class EquipmentInventorySnapshotRecord:
    equipment_id: UUID
    total_quantity: int


@dataclass(frozen=True)
class EquipmentReservationSnapshotRecord:
    equipment_id: UUID
    booking_id: UUID
    booking_date: date
    start_time: time
    end_time: time
    quantity: int


@dataclass(frozen=True)
class AllocationSnapshot:
    active_court_ids: tuple[UUID, ...]
    bookings: tuple[BookingSnapshotRecord, ...]
    blocks: tuple[BlockOutSnapshotRecord, ...]
    equipment_inventory: tuple[EquipmentInventorySnapshotRecord, ...]
    equipment_reservations: tuple[EquipmentReservationSnapshotRecord, ...]
