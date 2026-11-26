"""Use the canonical booking status values.

Revision ID: 0002_booking_status_values
Revises: 0001_e3_schema
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_booking_status_values"
down_revision: str | None = "0001_e3_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


STATUS_CHECK_EXPRESSION = (
    "CAST(status AS BINARY) IN "
    "(CAST('BOOKED' AS BINARY), CAST('CANCELLED' AS BINARY))"
)

_UPGRADE_ALLOWED_HEX_VALUES = (
    "636F6E6669726D6564",
    "63616E63656C6C6564",
    "424F4F4B4544",
    "43414E43454C4C4544",
)
_UPGRADE_ALLOWED_STATUSES = (
    "confirmed",
    "cancelled",
    "BOOKED",
    "CANCELLED",
)
_DOWNGRADE_ALLOWED_HEX_VALUES = (
    "424F4F4B4544",
    "43414E43454C4C4544",
    "636F6E6669726D6564",
    "63616E63656C6C6564",
)
_DOWNGRADE_ALLOWED_STATUSES = (
    "BOOKED",
    "CANCELLED",
    "confirmed",
    "cancelled",
)


def _validate_booking_statuses(
    allowed_hex_values: tuple[str, ...],
    operation: str,
    allowed_statuses: tuple[str, ...],
) -> None:
    context = op.get_context()
    if context.as_sql:
        context.impl.static_output(
            "-- WARNING: Offline SQL cannot validate booking statuses. "
            "Verify them before applying this script.\n"
        )
        return

    allowed_hex = ", ".join(
        f"CAST('{value}' AS BINARY)" for value in allowed_hex_values
    )
    unexpected_status = op.get_bind().execute(
        sa.text(
            "SELECT COALESCE(HEX(status), 'NULL') "
            "FROM booking "
            "WHERE status IS NULL "
            f"OR CAST(HEX(status) AS BINARY) NOT IN ({allowed_hex}) "
            "LIMIT 1"
        )
    ).scalar_one_or_none()
    if unexpected_status is not None:
        raise RuntimeError(
            f"Cannot {operation} booking status migration: found unexpected "
            f"status bytes {unexpected_status!r}; expected exactly "
            f"one of {', '.join(repr(status) for status in allowed_statuses)}."
        )


def _check_constraint_exists(logical_name: str) -> bool | None:
    if op.get_context().as_sql:
        return None

    physical_name = f"ck_booking_{logical_name}"
    constraints = sa.inspect(op.get_bind()).get_check_constraints("booking")
    return any(constraint.get("name") == physical_name for constraint in constraints)


def _drop_check_constraint_if_present(logical_name: str) -> None:
    if _check_constraint_exists(logical_name) is not False:
        op.drop_constraint(logical_name, "booking", type_="check")


def _create_check_constraint_if_missing(
    logical_name: str,
    condition: str,
) -> None:
    if _check_constraint_exists(logical_name) is not True:
        op.create_check_constraint(logical_name, "booking", condition)


def upgrade() -> None:
    _validate_booking_statuses(
        _UPGRADE_ALLOWED_HEX_VALUES,
        "upgrade",
        _UPGRADE_ALLOWED_STATUSES,
    )

    _drop_check_constraint_if_present("status_allowed")
    _drop_check_constraint_if_present("cancelled_timestamp")

    op.execute(
        sa.text(
            "UPDATE booking SET status = 'BOOKED' "
            "WHERE CAST(status AS BINARY) = CAST('confirmed' AS BINARY)"
        )
    )
    op.execute(
        sa.text(
            "UPDATE booking SET status = 'CANCELLED' "
            "WHERE CAST(status AS BINARY) = CAST('cancelled' AS BINARY)"
        )
    )
    op.alter_column(
        "booking",
        "status",
        existing_type=sa.String(length=10),
        existing_nullable=False,
        existing_server_default=sa.text("'confirmed'"),
        server_default=sa.text("'BOOKED'"),
    )

    _create_check_constraint_if_missing(
        "status_allowed",
        STATUS_CHECK_EXPRESSION,
    )
    _create_check_constraint_if_missing(
        "cancelled_timestamp",
        "status != 'CANCELLED' OR cancelled_at IS NOT NULL",
    )


def downgrade() -> None:
    _validate_booking_statuses(
        _DOWNGRADE_ALLOWED_HEX_VALUES,
        "downgrade",
        _DOWNGRADE_ALLOWED_STATUSES,
    )

    _drop_check_constraint_if_present("status_allowed")
    _drop_check_constraint_if_present("cancelled_timestamp")

    op.execute(
        sa.text(
            "UPDATE booking SET status = 'confirmed' "
            "WHERE CAST(status AS BINARY) = CAST('BOOKED' AS BINARY)"
        )
    )
    op.execute(
        sa.text(
            "UPDATE booking SET status = 'cancelled' "
            "WHERE CAST(status AS BINARY) = CAST('CANCELLED' AS BINARY)"
        )
    )
    op.alter_column(
        "booking",
        "status",
        existing_type=sa.String(length=10),
        existing_nullable=False,
        existing_server_default=sa.text("'BOOKED'"),
        server_default=sa.text("'confirmed'"),
    )

    _create_check_constraint_if_missing(
        "status_allowed",
        "status IN ('confirmed', 'cancelled')",
    )
    _create_check_constraint_if_missing(
        "cancelled_timestamp",
        "status != 'cancelled' OR cancelled_at IS NOT NULL",
    )
