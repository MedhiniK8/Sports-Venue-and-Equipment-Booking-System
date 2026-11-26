import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa


VERSIONS_PATH = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _load_migration(filename: str, module_name: str):
    spec = importlib.util.spec_from_file_location(
        module_name,
        VERSIONS_PATH / filename,
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


previous_migration = _load_migration(
    "0002_booking_status_values.py",
    "booking_status_migration_for_account_chain",
)
migration = _load_migration(
    "0003_account_roles_names_and_revocation.py",
    "account_roles_migration",
)


class _FakeConnection:
    def __init__(self, results: tuple[object, ...]) -> None:
        self.results = list(results)
        self.statements: list[str] = []

    def execute(self, statement: sa.TextClause):
        self.statements.append(str(statement))
        value = self.results.pop(0)
        return SimpleNamespace(scalar_one_or_none=lambda: value)


def _install_operations(monkeypatch, connection=None, as_sql=False):
    operations: list[tuple[str, tuple, dict]] = []

    def record(name):
        def operation(*args, **kwargs):
            operations.append((name, args, kwargs))

        return operation

    fake_op = SimpleNamespace(
        get_context=lambda: SimpleNamespace(as_sql=as_sql),
        get_bind=lambda: connection,
        alter_column=record("alter_column"),
        add_column=record("add_column"),
        create_check_constraint=record("create_check_constraint"),
        create_table=record("create_table"),
        create_index=record("create_index"),
        drop_index=record("drop_index"),
        drop_table=record("drop_table"),
        drop_constraint=record("drop_constraint"),
        drop_column=record("drop_column"),
    )
    monkeypatch.setattr(migration, "op", fake_op)
    return operations


def test_account_migration_revision_chain_is_linear():
    first_migration = _load_migration(
        "0001_e3_schema.py",
        "e3_schema_migration_for_account_chain",
    )

    assert first_migration.down_revision is None
    assert previous_migration.down_revision == first_migration.revision
    assert migration.down_revision == previous_migration.revision
    assert migration.revision == "0003_account_roles_revocation"


def test_upgrade_keeps_legacy_demographics_nullable_and_adds_defaults(monkeypatch):
    operations = _install_operations(monkeypatch)

    migration.upgrade()

    nullable_columns = {
        args[1]: kwargs["nullable"]
        for name, args, kwargs in operations
        if name == "alter_column"
    }
    assert nullable_columns == {
        "year_of_admission": True,
        "gender": True,
    }

    added_columns = {
        args[1].name: args[1]
        for name, args, _ in operations
        if name == "add_column"
    }
    assert added_columns["student_name"].nullable is False
    assert added_columns["student_name"].server_default.arg == ""
    assert added_columns["role"].nullable is False
    assert str(added_columns["role"].server_default.arg) == "'STUDENT'"

    assert any(
        name == "create_check_constraint"
        and args == ("role_allowed", "users", "role IN ('STUDENT', 'ADMIN')")
        for name, args, _ in operations
    )
    revoked_table = next(
        args
        for name, args, _ in operations
        if name == "create_table" and args[0] == "revoked_token"
    )
    assert {column.name for column in revoked_table[1:3]} == {
        "jti",
        "expires_at",
    }


@pytest.mark.parametrize(
    ("user_result", "token_result", "error"),
    [
        (1, None, "nullable admission data"),
        (None, 1, "revoked tokens exist"),
    ],
)
def test_downgrade_refuses_data_loss_before_schema_changes(
    monkeypatch,
    user_result,
    token_result,
    error,
):
    connection = _FakeConnection((user_result, token_result))
    operations = _install_operations(monkeypatch, connection)

    with pytest.raises(RuntimeError, match=error):
        migration.downgrade()

    assert len(connection.statements) == 1 if user_result is not None else 2
    assert operations == []


def test_downgrade_refuses_offline_generation(monkeypatch):
    operations = _install_operations(monkeypatch, as_sql=True)

    with pytest.raises(RuntimeError, match="Cannot safely render"):
        migration.downgrade()

    assert operations == []


def test_downgrade_with_compatible_data_removes_added_schema(monkeypatch):
    connection = _FakeConnection((None, None))
    operations = _install_operations(monkeypatch, connection)

    migration.downgrade()

    assert [name for name, _, _ in operations] == [
        "drop_index",
        "drop_table",
        "drop_constraint",
        "drop_column",
        "drop_column",
        "alter_column",
        "alter_column",
    ]
    nullable_columns = {
        args[1]: kwargs["nullable"]
        for name, args, kwargs in operations
        if name == "alter_column"
    }
    assert nullable_columns == {
        "year_of_admission": False,
        "gender": False,
    }
