from sqlalchemy.schema import CreateTable
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import configure_mappers

from app.e3_persistence.models import Base


def test_e3_metadata_contains_expected_mysql_tables_and_constraints():
    configure_mappers()
    expected_tables = {
        "users",
        "sport",
        "court",
        "booking",
        "slot_claim",
        "equipment_item",
        "equipment_allocation",
        "block_out",
        "revoked_token",
    }

    assert set(Base.metadata.tables) == expected_tables
    assert all(
        table.dialect_options["mysql"]["engine"] == "InnoDB"
        for table in Base.metadata.tables.values()
    )

    users = Base.metadata.tables["users"]
    assert {
        constraint.name
        for constraint in users.constraints
        if isinstance(constraint, UniqueConstraint)
    } == {"uq_users_college_email", "uq_users_usn"}
    assert str(users.c.user_id.type.compile(dialect=mysql.dialect())) == "CHAR(32)"

    slot_claim = Base.metadata.tables["slot_claim"]
    assert [column.name for column in slot_claim.primary_key.columns] == [
        "court_id",
        "slot_date",
        "minute_index",
    ]
    assert str(slot_claim.c.minute_index.type.compile(dialect=mysql.dialect())) == "INTEGER"
    assert {
        constraint.name for constraint in slot_claim.constraints
    } >= {
        "ck_slot_claim_minute_range",
        "ck_slot_claim_exactly_one_owner",
        "fk_slot_claim_booking_court_date",
        "fk_slot_claim_block_out_court",
    }
    assert {
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    } == {
        "ck_users_year_of_admission_positive",
        "ck_users_role_allowed",
        "ck_equipment_item_total_quantity_nonnegative",
        "ck_booking_time_interval",
        "ck_booking_minute_precision",
        "ck_booking_status_allowed",
        "ck_booking_cancelled_timestamp",
        "ck_equipment_allocation_quantity_positive",
        "ck_slot_claim_minute_range",
        "ck_slot_claim_exactly_one_owner",
        "ck_block_out_time_interval",
    }
    for table in Base.metadata.sorted_tables:
        assert "CREATE TABLE" in str(CreateTable(table).compile(dialect=mysql.dialect()))
