"""Add student names, roles and revoked JWT tokens.

Revision ID: 0003_account_roles_revocation
Revises: 0002_booking_status_values
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003_account_roles_revocation"
down_revision: str | None = "0002_booking_status_values"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "year_of_admission",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.alter_column(
        "users",
        "gender",
        existing_type=sa.String(length=32),
        nullable=True,
    )
    op.add_column(
        "users",
        sa.Column("student_name", sa.String(length=100), nullable=False, server_default=""),
    )
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'STUDENT'"),
        ),
    )
    op.create_check_constraint(
        "role_allowed",
        "users",
        "role IN ('STUDENT', 'ADMIN')",
    )
    op.create_table(
        "revoked_token",
        sa.Column("jti", sa.String(length=36), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("jti", name="pk_revoked_token"),
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_revoked_token_expires_at",
        "revoked_token",
        ["expires_at"],
        unique=False,
    )


def _require_safe_downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Cannot safely render this downgrade offline; verify account data "
            "and revoked tokens against a live database first."
        )

    connection = op.get_bind()
    incompatible_user = connection.execute(
        sa.text(
            "SELECT 1 FROM users "
            "WHERE year_of_admission IS NULL "
            "OR gender IS NULL "
            "OR student_name <> '' "
            "OR role <> 'STUDENT' "
            "LIMIT 1"
        )
    ).scalar_one_or_none()
    if incompatible_user is not None:
        raise RuntimeError(
            "Cannot downgrade account migration: nullable admission data, "
            "student names, or non-default roles would be lost or altered."
        )

    revoked_tokens = connection.execute(
        sa.text("SELECT 1 FROM revoked_token LIMIT 1")
    ).scalar_one_or_none()
    if revoked_tokens is not None:
        raise RuntimeError(
            "Cannot downgrade account migration while revoked tokens exist."
        )


def downgrade() -> None:
    _require_safe_downgrade()
    op.drop_index(
        "ix_revoked_token_expires_at",
        table_name="revoked_token",
    )
    op.drop_table("revoked_token")
    op.drop_constraint("role_allowed", "users", type_="check")
    op.drop_column("users", "role")
    op.drop_column("users", "student_name")
    op.alter_column(
        "users",
        "year_of_admission",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "users",
        "gender",
        existing_type=sa.String(length=32),
        nullable=False,
    )
