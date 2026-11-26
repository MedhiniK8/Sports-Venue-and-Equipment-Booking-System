"""Create E3 persistence and student account tables.

Revision ID: 0001_e3_schema
Revises:
Create Date: 2025-01-01
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001_e3_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", sa.CHAR(length=32), nullable=False),
        sa.Column("usn", sa.String(length=50), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("college_email", sa.String(length=254), nullable=False),
        sa.Column("phone_number", sa.String(length=32), nullable=False),
        sa.Column("year_of_admission", sa.Integer(), nullable=False),
        sa.Column("gender", sa.String(length=32), nullable=False),
        sa.Column("branch", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "year_of_admission > 0",
            name="year_of_admission_positive",
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_users"),
        sa.UniqueConstraint("college_email", name="uq_users_college_email"),
        sa.UniqueConstraint("usn", name="uq_users_usn"),
        mysql_engine="InnoDB",
    )
    op.create_table(
        "sport",
        sa.Column("sport_id", sa.CHAR(length=32), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.PrimaryKeyConstraint("sport_id", name="pk_sport"),
        sa.UniqueConstraint("name", name="uq_sport_name"),
        mysql_engine="InnoDB",
    )
    op.create_table(
        "court",
        sa.Column("court_id", sa.CHAR(length=32), nullable=False),
        sa.Column("sport_id", sa.CHAR(length=32), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.ForeignKeyConstraint(
            ["sport_id"], ["sport.sport_id"], name="fk_court_sport_id_sport", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("court_id", name="pk_court"),
        sa.UniqueConstraint("sport_id", "name", name="uq_court_sport_name"),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_court_sport_id", "court", ["sport_id"], unique=False)
    op.create_table(
        "equipment_item",
        sa.Column("equipment_id", sa.CHAR(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("total_quantity", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "total_quantity >= 0", name="total_quantity_nonnegative"
        ),
        sa.PrimaryKeyConstraint("equipment_id", name="pk_equipment_item"),
        sa.UniqueConstraint("name", name="uq_equipment_item_name"),
        mysql_engine="InnoDB",
    )
    op.create_table(
        "booking",
        sa.Column("booking_id", sa.CHAR(length=32), nullable=False),
        sa.Column("user_id", sa.CHAR(length=32), nullable=False),
        sa.Column("court_id", sa.CHAR(length=32), nullable=False),
        sa.Column("booking_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("status", sa.String(length=10), server_default=sa.text("'confirmed'"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status != 'cancelled' OR cancelled_at IS NOT NULL",
            name="cancelled_timestamp",
        ),
        sa.CheckConstraint("start_time < end_time", name="time_interval"),
        sa.CheckConstraint(
            "SECOND(start_time) = 0 AND SECOND(end_time) = 0",
            name="minute_precision",
        ),
        sa.CheckConstraint(
            "status IN ('confirmed', 'cancelled')", name="status_allowed"
        ),
        sa.ForeignKeyConstraint(
            ["court_id"], ["court.court_id"], name="fk_booking_court_id_court", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.user_id"], name="fk_booking_user_id_users", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("booking_id", name="pk_booking"),
        sa.UniqueConstraint(
            "booking_id", "court_id", "booking_date", name="uq_booking_id_court_date"
        ),
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_booking_court_date_status",
        "booking",
        ["court_id", "booking_date", "status"],
        unique=False,
    )
    op.create_index(
        "ix_booking_date_status",
        "booking",
        ["booking_date", "status"],
        unique=False,
    )
    op.create_index("ix_booking_user_id", "booking", ["user_id"], unique=False)
    op.create_table(
        "block_out",
        sa.Column("block_out_id", sa.CHAR(length=32), nullable=False),
        sa.Column("court_id", sa.CHAR(length=32), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.CHAR(length=32), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("starts_at < ends_at", name="time_interval"),
        sa.ForeignKeyConstraint(
            ["court_id"], ["court.court_id"], name="fk_block_out_court_id_court", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.user_id"], name="fk_block_out_created_by_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("block_out_id", name="pk_block_out"),
        sa.UniqueConstraint("block_out_id", "court_id", name="uq_block_out_id_court"),
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_block_out_court_active_start",
        "block_out",
        ["court_id", "is_active", "starts_at"],
        unique=False,
    )
    op.create_table(
        "equipment_allocation",
        sa.Column("allocation_id", sa.CHAR(length=32), nullable=False),
        sa.Column("booking_id", sa.CHAR(length=32), nullable=False),
        sa.Column("equipment_id", sa.CHAR(length=32), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="quantity_positive"),
        sa.ForeignKeyConstraint(
            ["booking_id"],
            ["booking.booking_id"],
            name="fk_equipment_allocation_booking_id_booking",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["equipment_id"],
            ["equipment_item.equipment_id"],
            name="fk_equipment_allocation_equipment_id_equipment_item",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("allocation_id", name="pk_equipment_allocation"),
        sa.UniqueConstraint(
            "booking_id", "equipment_id", name="uq_equipment_allocation_booking_item"
        ),
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_equipment_allocation_equipment_id",
        "equipment_allocation",
        ["equipment_id"],
        unique=False,
    )
    op.create_table(
        "slot_claim",
        sa.Column("court_id", sa.CHAR(length=32), nullable=False),
        sa.Column("slot_date", sa.Date(), nullable=False),
        sa.Column("minute_index", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.CHAR(length=32), nullable=True),
        sa.Column("block_out_id", sa.CHAR(length=32), nullable=True),
        sa.CheckConstraint(
            "minute_index >= 0 AND minute_index <= 1439",
            name="minute_range",
        ),
        sa.CheckConstraint(
            "(booking_id IS NOT NULL AND block_out_id IS NULL) OR "
            "(booking_id IS NULL AND block_out_id IS NOT NULL)",
            name="exactly_one_owner",
        ),
        sa.ForeignKeyConstraint(
            ["booking_id", "court_id", "slot_date"],
            ["booking.booking_id", "booking.court_id", "booking.booking_date"],
            name="fk_slot_claim_booking_court_date",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["block_out_id", "court_id"],
            ["block_out.block_out_id", "block_out.court_id"],
            name="fk_slot_claim_block_out_court",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["court_id"],
            ["court.court_id"],
            name="fk_slot_claim_court_id_court",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "court_id", "slot_date", "minute_index", name="pk_slot_claim"
        ),
        mysql_engine="InnoDB",
    )


def downgrade() -> None:
    op.drop_table("slot_claim")
    op.drop_index(
        "ix_equipment_allocation_equipment_id", table_name="equipment_allocation"
    )
    op.drop_table("equipment_allocation")
    op.drop_index("ix_block_out_court_active_start", table_name="block_out")
    op.drop_table("block_out")
    op.drop_index("ix_booking_user_id", table_name="booking")
    op.drop_index("ix_booking_date_status", table_name="booking")
    op.drop_index("ix_booking_court_date_status", table_name="booking")
    op.drop_table("booking")
    op.drop_table("equipment_item")
    op.drop_index("ix_court_sport_id", table_name="court")
    op.drop_table("court")
    op.drop_table("sport")
    op.drop_table("users")
