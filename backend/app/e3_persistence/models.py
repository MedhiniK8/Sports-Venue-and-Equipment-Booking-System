from datetime import date, datetime, time, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Index,
    MetaData,
    String,
    Time,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .inputs import BookingStatus


NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("usn", name="uq_users_usn"),
        UniqueConstraint("college_email", name="uq_users_college_email"),
        CheckConstraint(
            "year_of_admission > 0", name="year_of_admission_positive"
        ),
        {"mysql_engine": "InnoDB"},
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    usn: Mapped[str] = mapped_column(String(50), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    college_email: Mapped[str] = mapped_column(String(254), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
    year_of_admission: Mapped[int] = mapped_column(Integer, nullable=False)
    gender: Mapped[str] = mapped_column(String(32), nullable=False)
    branch: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, default=_utcnow, server_default=func.current_timestamp()
    )

    bookings: Mapped[list["Booking"]] = relationship(back_populates="user")
    created_block_outs: Mapped[list["BlockOut"]] = relationship(back_populates="creator")


class Sport(Base):
    __tablename__ = "sport"
    __table_args__ = (
        UniqueConstraint("name", name="uq_sport_name"),
        {"mysql_engine": "InnoDB"},
    )

    sport_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )

    courts: Mapped[list["Court"]] = relationship(back_populates="sport")


class Court(Base):
    __tablename__ = "court"
    __table_args__ = (
        UniqueConstraint("sport_id", "name", name="uq_court_sport_name"),
        Index("ix_court_sport_id", "sport_id"),
        {"mysql_engine": "InnoDB"},
    )

    court_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    sport_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sport.sport_id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )

    sport: Mapped[Sport] = relationship(back_populates="courts")
    bookings: Mapped[list["Booking"]] = relationship(back_populates="court")
    block_outs: Mapped[list["BlockOut"]] = relationship(back_populates="court")
    slot_claims: Mapped[list["SlotClaim"]] = relationship(
        back_populates="court", viewonly=True
    )


class EquipmentItem(Base):
    __tablename__ = "equipment_item"
    __table_args__ = (
        UniqueConstraint("name", name="uq_equipment_item_name"),
        CheckConstraint("total_quantity >= 0", name="total_quantity_nonnegative"),
        {"mysql_engine": "InnoDB"},
    )

    equipment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    total_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )

    allocations: Mapped[list["EquipmentAllocation"]] = relationship(
        back_populates="equipment"
    )


class Booking(Base):
    __tablename__ = "booking"
    __table_args__ = (
        UniqueConstraint(
            "booking_id", "court_id", "booking_date", name="uq_booking_id_court_date"
        ),
        CheckConstraint("start_time < end_time", name="time_interval"),
        CheckConstraint(
            "SECOND(start_time) = 0 AND SECOND(end_time) = 0",
            name="minute_precision",
        ),
        CheckConstraint(
            "HEX(status) IN ('424F4F4B4544', '43414E43454C4C4544')",
            name="status_allowed",
        ),
        CheckConstraint(
            "status != 'CANCELLED' OR cancelled_at IS NOT NULL",
            name="cancelled_timestamp",
        ),
        Index("ix_booking_court_date_status", "court_id", "booking_date", "status"),
        Index("ix_booking_date_status", "booking_date", "status"),
        Index("ix_booking_user_id", "user_id"),
        {"mysql_engine": "InnoDB"},
    )

    booking_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    court_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("court.court_id", ondelete="RESTRICT"), nullable=False
    )
    booking_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    status: Mapped[BookingStatus] = mapped_column(
        String(10), nullable=False, default="BOOKED", server_default=text("'BOOKED'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, default=_utcnow, server_default=func.current_timestamp()
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)

    user: Mapped[User] = relationship(back_populates="bookings")
    court: Mapped[Court] = relationship(back_populates="bookings")
    equipment_allocations: Mapped[list["EquipmentAllocation"]] = relationship(
        back_populates="booking"
    )
    slot_claims: Mapped[list["SlotClaim"]] = relationship(
        back_populates="booking", viewonly=True
    )


class BlockOut(Base):
    __tablename__ = "block_out"
    __table_args__ = (
        UniqueConstraint("block_out_id", "court_id", name="uq_block_out_id_court"),
        CheckConstraint("starts_at < ends_at", name="time_interval"),
        Index("ix_block_out_court_active_start", "court_id", "is_active", "starts_at"),
        {"mysql_engine": "InnoDB"},
    )

    block_out_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    court_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("court.court_id", ondelete="RESTRICT"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, default=_utcnow, server_default=func.current_timestamp()
    )

    court: Mapped[Court] = relationship(back_populates="block_outs")
    creator: Mapped[User | None] = relationship(back_populates="created_block_outs")
    slot_claims: Mapped[list["SlotClaim"]] = relationship(
        back_populates="block_out", viewonly=True
    )


class EquipmentAllocation(Base):
    __tablename__ = "equipment_allocation"
    __table_args__ = (
        UniqueConstraint(
            "booking_id", "equipment_id", name="uq_equipment_allocation_booking_item"
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        Index("ix_equipment_allocation_equipment_id", "equipment_id"),
        {"mysql_engine": "InnoDB"},
    )

    allocation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    booking_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("booking.booking_id", ondelete="RESTRICT"),
        nullable=False,
    )
    equipment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("equipment_item.equipment_id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    booking: Mapped[Booking] = relationship(back_populates="equipment_allocations")
    equipment: Mapped[EquipmentItem] = relationship(back_populates="allocations")


class SlotClaim(Base):
    __tablename__ = "slot_claim"
    __table_args__ = (
        ForeignKeyConstraint(
            ["booking_id", "court_id", "slot_date"],
            ["booking.booking_id", "booking.court_id", "booking.booking_date"],
            name="fk_slot_claim_booking_court_date",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["block_out_id", "court_id"],
            ["block_out.block_out_id", "block_out.court_id"],
            name="fk_slot_claim_block_out_court",
            ondelete="RESTRICT",
        ),
        CheckConstraint("minute_index >= 0 AND minute_index <= 1439", name="minute_range"),
        CheckConstraint(
            "(booking_id IS NOT NULL AND block_out_id IS NULL) OR "
            "(booking_id IS NULL AND block_out_id IS NOT NULL)",
            name="exactly_one_owner",
        ),
        {"mysql_engine": "InnoDB"},
    )

    court_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("court.court_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    slot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    minute_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    booking_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    block_out_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    court: Mapped[Court] = relationship(back_populates="slot_claims", viewonly=True)
    booking: Mapped[Booking | None] = relationship(
        back_populates="slot_claims", viewonly=True
    )
    block_out: Mapped[BlockOut | None] = relationship(
        back_populates="slot_claims", viewonly=True
    )
