"""Waste cost provenance cannot be discarded by a downgrade."""

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


BACKEND = Path(__file__).resolve().parents[2]


def _migration():
    config = Config(str(BACKEND / "alembic.ini"))
    return ScriptDirectory.from_config(config).get_revision("0136_waste_cost_provenance").module


def _run(connection, operation):
    with Operations.context(MigrationContext.configure(connection)):
        getattr(_migration(), operation)()


def _predecessor_tables(connection):
    metadata = sa.MetaData()
    sa.Table("stock_batches", metadata, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table(
        "waste_records", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("estimated_value", sa.Numeric(12, 2), nullable=False),
    )
    metadata.create_all(connection)


@pytest.mark.parametrize("provenance", [
    {"cost_currency_at_recording": "USD"},
    {"cost_source_batch_id": 7},
    {"cost_currency_at_recording": "USD", "cost_source_batch_id": 7},
])
def test_0136_downgrade_refuses_before_ddl_when_provenance_exists(provenance):
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        _predecessor_tables(connection)
        connection.execute(sa.text("INSERT INTO stock_batches (id) VALUES (7)"))
        _run(connection, "upgrade")
        waste = sa.Table("waste_records", sa.MetaData(), autoload_with=connection)
        connection.execute(waste.insert(), {"id": 1, "estimated_value": 2, **provenance})
        before_columns = {column["name"] for column in sa.inspect(connection).get_columns("waste_records")}
        before_fks = sa.inspect(connection).get_foreign_keys("waste_records")

        with pytest.raises(RuntimeError, match="Refusing to downgrade 0136"):
            _run(connection, "downgrade")

        assert {column["name"] for column in sa.inspect(connection).get_columns("waste_records")} == before_columns
        assert sa.inspect(connection).get_foreign_keys("waste_records") == before_fks
        assert connection.execute(sa.select(waste)).mappings().one()["id"] == 1
        for column, value in provenance.items():
            assert connection.execute(sa.select(waste.c[column])).scalar_one() == value
    engine.dispose()


def test_0136_downgrade_succeeds_without_recorded_provenance():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        _predecessor_tables(connection)
        _run(connection, "upgrade")
        waste = sa.Table("waste_records", sa.MetaData(), autoload_with=connection)
        connection.execute(waste.insert(), {"id": 1, "estimated_value": 0})
        _run(connection, "downgrade")

        assert {column["name"] for column in sa.inspect(connection).get_columns("waste_records")} == {
            "id", "estimated_value",
        }
        assert sa.inspect(connection).get_foreign_keys("waste_records") == []
        assert connection.execute(sa.text("SELECT id, estimated_value FROM waste_records")).one() == (1, 0)
    engine.dispose()
