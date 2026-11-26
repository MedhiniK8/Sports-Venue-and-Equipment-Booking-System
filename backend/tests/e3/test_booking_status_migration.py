import importlib.util
from io import StringIO
from pathlib import Path
import re
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import mysql

from app.e3_persistence.models import Base


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0002_booking_status_values.py"
)
SPEC = importlib.util.spec_from_file_location(
    "booking_status_migration",
    MIGRATION_PATH,
)
assert SPEC is not None and SPEC.loader is not None
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


class _FakeResult:
    def __init__(self, value: str | None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> str | None:
        return self.value


class _FakeConnection:
    def __init__(
        self,
        statuses: tuple[str | None, ...],
        events: list[str],
        constraints: set[str],
    ) -> None:
        self.statuses = statuses
        self.events = events
        self.constraints = constraints

    def execute(self, statement: sa.TextClause) -> _FakeResult:
        sql = str(statement)
        assert "CAST(HEX(status) AS BINARY)" in sql
        allowed_hex = set(
            re.findall(r"CAST\('([0-9A-F]+)' AS BINARY\)", sql)
        )
        assert allowed_hex == set(migration._UPGRADE_ALLOWED_HEX_VALUES)
        self.events.append("preflight")
        unexpected = next(
            (
                "NULL" if status is None else status
                for status in self.statuses
                if status is None or status not in allowed_hex
            ),
            None,
        )
        return _FakeResult(unexpected)


class _FakeInspector:
    def __init__(self, constraints: set[str]) -> None:
        self.constraints = constraints

    def get_check_constraints(self, table_name: str) -> list[dict[str, str]]:
        assert table_name == "booking"
        return [{"name": name, "sqltext": ""} for name in self.constraints]


def _install_fake_operations(
    monkeypatch: pytest.MonkeyPatch,
    statuses: tuple[str | None, ...],
    constraints: set[str] | None = None,
) -> list[str]:
    events: list[str] = []
    if constraints is None:
        constraints = {
            "ck_booking_status_allowed",
            "ck_booking_cancelled_timestamp",
            "ck_booking_time_interval",
            "ck_booking_minute_precision",
        }
    connection = _FakeConnection(statuses, events, constraints)

    def drop_constraint(name: str, table_name: str, type_: str) -> None:
        assert type_ == "check"
        connection.constraints.discard(f"ck_{table_name}_{name}")
        events.append("schema_or_data_change")

    def create_check_constraint(
        name: str,
        table_name: str,
        condition: str,
    ) -> None:
        connection.constraints.add(f"ck_{table_name}_{name}")
        events.append("schema_or_data_change")

    def record_operation(*args, **kwargs) -> None:
        events.append("schema_or_data_change")

    fake_op = SimpleNamespace(
        get_context=lambda: SimpleNamespace(as_sql=False),
        get_bind=lambda: connection,
        drop_constraint=drop_constraint,
        execute=record_operation,
        alter_column=record_operation,
        create_check_constraint=create_check_constraint,
        constraints=connection.constraints,
    )
    monkeypatch.setattr(
        migration.sa,
        "inspect",
        lambda bind: _FakeInspector(bind.constraints),
    )
    monkeypatch.setattr(migration, "op", fake_op)
    return events


def test_upgrade_validates_legacy_values_before_changes(monkeypatch):
    events = _install_fake_operations(
        monkeypatch,
        ("636F6E6669726D6564", "63616E63656C6C6564"),
    )

    migration.upgrade()

    assert events[0] == "preflight"
    assert "schema_or_data_change" in events[1:]


def test_upgrade_retries_after_legacy_constraints_were_dropped(monkeypatch):
    events = _install_fake_operations(
        monkeypatch,
        ("424F4F4B4544", "43414E43454C4C4544"),
        {
            "ck_booking_minute_precision",
            "ck_booking_time_interval",
        },
    )

    migration.upgrade()

    assert events[0] == "preflight"
    assert migration.op.constraints == {
        "ck_booking_minute_precision",
        "ck_booking_time_interval",
        "ck_booking_status_allowed",
        "ck_booking_cancelled_timestamp",
    }

    migration.upgrade()

    assert migration.op.constraints == {
        "ck_booking_minute_precision",
        "ck_booking_time_interval",
        "ck_booking_status_allowed",
        "ck_booking_cancelled_timestamp",
    }


@pytest.mark.parametrize(
    "unexpected_status",
    [
        "41444D494E",  # ADMIN
        "434F4E4649524D4544",  # CONFIRMED, wrong case
        "436F6E6669726D6564",  # Confirmed, wrong case
    ],
)
def test_upgrade_rejects_unexpected_or_case_variant_status_before_changes(
    monkeypatch,
    unexpected_status,
):
    events = _install_fake_operations(monkeypatch, (unexpected_status,))

    with pytest.raises(RuntimeError, match="unexpected status bytes"):
        migration.upgrade()

    assert events == ["preflight"]


def test_downgrade_rejects_unexpected_status_before_changes(monkeypatch):
    events = _install_fake_operations(monkeypatch, ("626F6F6B6564",))  # booked

    with pytest.raises(RuntimeError, match="Cannot downgrade"):
        migration.downgrade()

    assert events == ["preflight"]


def test_offline_upgrade_and_downgrade_sql_render():
    for migration_function in (migration.upgrade, migration.downgrade):
        output = StringIO()
        context = MigrationContext.configure(
            dialect=mysql.dialect(),
            opts={
                "as_sql": True,
                "output_buffer": output,
                "literal_binds": True,
                "target_metadata": Base.metadata,
            },
        )

        with Operations.context(context):
            migration_function()

        rendered_sql = output.getvalue()
        assert "Offline SQL cannot validate booking statuses" in rendered_sql
        assert "ALTER TABLE booking" in rendered_sql
        assert "UPDATE booking SET status" in rendered_sql
        assert "ck_booking_status_allowed" in rendered_sql
        assert "ck_booking_cancelled_timestamp" in rendered_sql
        if migration_function is migration.upgrade:
            assert migration.STATUS_CHECK_EXPRESSION in rendered_sql
