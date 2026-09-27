from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0132_department_soft_delete.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0132_department_soft_delete", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_department_soft_delete_migration_is_additive_and_reversible():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE departments (id INTEGER PRIMARY KEY, name VARCHAR(128) NOT NULL, code VARCHAR(32) NOT NULL)"
        ))
        connection.execute(text("INSERT INTO departments (id, name, code) VALUES (1, 'Cutting', 'CUT')"))
        migration = _load_migration()
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()

        columns = {column["name"] for column in inspect(connection).get_columns("departments")}
        assert columns == {"id", "name", "code", "is_active"}
        assert connection.execute(text("SELECT id, name, code, is_active FROM departments")).one() == (
            1, "Cutting", "CUT", 1
        )

        connection.execute(text("UPDATE departments SET is_active = 0 WHERE id = 1"))
        migration.downgrade()

        columns = {column["name"] for column in inspect(connection).get_columns("departments")}
        assert columns == {"id", "name", "code"}
        assert connection.execute(text("SELECT id, name, code FROM departments")).one() == (1, "Cutting", "CUT")
