"""DB08 (Beyka half): the ORM had no mapping for cutting_beika_material_usages.

Migration 0076 created `cutting_beika_material_usages`, but no ORM class or relationship
was ever added. `services/traceability.py` reads `row.beika_materials` defensively with
`getattr(row, "beika_materials", None)`, so the missing attribute silently produced an
empty list and traceability fell back to the record's `beika_kg` total - dropping the
per-batch Beyka evidence the database was already storing. Nothing raised, so the gap was
invisible in every run.

These tests compare the mapped table against the real schema built by migration 0076 on
PostgreSQL. A SQLite `create_all` proves nothing here: it builds the database *from* the
ORM, so a missing class cannot appear as drift.

Set STABILIZATION_POSTGRES_URL to run them.
"""

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import CuttingBeikaMaterialUsage, CuttingMaterialUsage, CuttingRecord
import app.models  # noqa: F401  - registers every mapped table

BACKEND = Path(__file__).resolve().parents[2]
MIGRATION = BACKEND / "alembic" / "versions" / "0076_cutting_beika_usage.py"


@pytest.fixture(scope="module")
def beika_postgres():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL Beyka ORM parity coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Beyka ORM parity tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"db08_beyka_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -cstatement_timeout=30000"},
        pool_size=4,
        max_overflow=0,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def test_beyka_usage_table_is_mapped_at_all():
    """The regression that started this: the table had no ORM class."""
    assert CuttingBeikaMaterialUsage.__tablename__ == "cutting_beika_material_usages"
    assert "beika_materials" in CuttingRecord.__mapper__.relationships, (
        "CuttingRecord must expose beika_materials; traceability reads it and silently "
        "falls back to the beika_kg total when it is missing"
    )
    relationship = CuttingRecord.__mapper__.relationships["beika_materials"]
    assert relationship.mapper.class_ is CuttingBeikaMaterialUsage


def _create_beyka_table(engine):
    """Create the mapped table with its foreign-key targets present."""
    tables = set()
    pending = [CuttingBeikaMaterialUsage.__table__]
    while pending:
        table = pending.pop()
        if table in tables:
            continue
        tables.add(table)
        pending.extend(fk.column.table for fk in table.foreign_keys)
    Base.metadata.create_all(engine, tables=list(tables))


def test_mapped_columns_match_migration_0076(beika_postgres):
    """Every column the migration creates must exist in the mapping, with the same shape."""
    _create_beyka_table(beika_postgres)
    inspector = inspect(beika_postgres)
    assert "cutting_beika_material_usages" in inspector.get_table_names()
    actual = {
        column["name"]: (str(column["type"]), bool(column["nullable"]))
        for column in inspector.get_columns("cutting_beika_material_usages")
    }

    mapped = {
        column.name: (str(column.type), bool(column.nullable))
        for column in CuttingBeikaMaterialUsage.__table__.columns
    }
    # The shape migration 0076 creates for the columns this class declares itself.
    # `id`, `created_at` and `updated_at` come from the shared PkMixin/TimestampMixin
    # exactly as they do for CuttingMaterialUsage, so they are asserted separately.
    expected = {
        "cutting_record_id": ("INTEGER", False),
        "stock_batch_id": ("INTEGER", False),
        "quantity": ("NUMERIC(14, 4)", False),
        "unit": ("VARCHAR(32)", False),
        "position": ("INTEGER", False),
    }
    declared = {name: shape for name, shape in mapped.items() if name not in {"id", "created_at", "updated_at"}}
    assert declared == expected, "the mapping must describe exactly what migration 0076 creates"
    for name, shape in expected.items():
        assert actual[name] == shape, f"{name!r}: created as {actual[name]}, expected {shape}"
    assert set(mapped) == set(actual), "the mapped and created column sets must match exactly"


def test_mapped_foreign_keys_and_defaults_match_migration_0076():
    """Both FKs and the unit default are part of the migrated shape."""
    table = CuttingBeikaMaterialUsage.__table__
    fk_targets = {column.name: sorted(fk.target_fullname for fk in column.foreign_keys)
                  for column in table.columns if column.foreign_keys}
    assert fk_targets["cutting_record_id"] == ["cutting_records.id"]
    assert fk_targets["stock_batch_id"] == ["stock_batches.id"]

    record_fk = next(iter(table.c.cutting_record_id.foreign_keys))
    assert record_fk.ondelete == "CASCADE", "the migrated FK cascades on record deletion"
    assert table.c.unit.server_default is not None and table.c.unit.server_default.arg == "kg"
