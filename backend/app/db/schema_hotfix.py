"""Idempotent schema patches that run automatically on backend startup.

Render's free tier doesn't expose a Shell, so we can't run ad-hoc ALTER TABLE
commands by hand. This module performs those changes via SQLAlchemy on every
boot. Each statement is `ADD COLUMN IF NOT EXISTS`, so it's a no-op once the
column exists — safe to run on every deploy.

Postgres-only (uses `IF NOT EXISTS` on `ADD COLUMN`). SQLite/test runs are
skipped because the test setup uses `Base.metadata.create_all` which already
includes the latest columns.
"""
from __future__ import annotations
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger("schema_hotfix")

# (table, column-DDL fragment) pairs.
# Order matters when one column references another table; new tables created
# by Base.metadata.create_all (called from `app.main` at startup) must exist
# first. The schema_hotfix runs AFTER create_all.
_PATCHES: list[tuple[str, str]] = [
    ("work_orders", "ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN NOT NULL DEFAULT FALSE"),
    ("work_orders", "ADD COLUMN IF NOT EXISTS block_reason TEXT"),
    ("work_orders", "ADD COLUMN IF NOT EXISTS deadline TIMESTAMPTZ"),
    ("work_orders", "ADD COLUMN IF NOT EXISTS sewing_flow_id INTEGER REFERENCES sewing_flows(id)"),
    ("models",      "ADD COLUMN IF NOT EXISTS sam_minutes NUMERIC(8,2) NOT NULL DEFAULT 0"),
    ("invoices",    "ADD COLUMN IF NOT EXISTS external_source VARCHAR(32)"),
    ("invoices",    "ADD COLUMN IF NOT EXISTS external_id VARCHAR(128)"),
    ("payments",    "ADD COLUMN IF NOT EXISTS external_source VARCHAR(32)"),
    ("payments",    "ADD COLUMN IF NOT EXISTS external_id VARCHAR(128)"),
    ("items",       "ADD COLUMN IF NOT EXISTS reorder_level NUMERIC(14,4) NOT NULL DEFAULT 0"),
    ("tasks",       "ADD COLUMN IF NOT EXISTS entity_type VARCHAR(64)"),
    ("tasks",       "ADD COLUMN IF NOT EXISTS entity_id INTEGER"),
    ("notifications", "ADD COLUMN IF NOT EXISTS link VARCHAR(512)"),
    ("sales_orders", "ADD COLUMN IF NOT EXISTS printing_instructions TEXT"),
    ("sales_orders", "ADD COLUMN IF NOT EXISTS printing_attachments JSONB"),
]

_DATA_FIXES: list[str] = [
    "UPDATE items SET unit = 'kg' WHERE lower(trim(unit)) = 'meter'",
    "UPDATE stock_batches SET unit = 'kg' WHERE lower(trim(unit)) = 'meter'",
    "UPDATE stock_movements SET unit = 'kg' WHERE lower(trim(unit)) = 'meter'",
    "UPDATE model_bom SET unit = 'kg' WHERE lower(trim(unit)) = 'meter'",
    "UPDATE cutting_records SET input_unit = 'kg' WHERE lower(trim(input_unit)) = 'meter'",
]


def run(engine: Engine) -> None:
    """Apply every patch in its own transaction.

    Each patch runs in an isolated transaction so that a single failure (e.g.
    referenced table doesn't exist yet on first boot) doesn't roll back the
    other successful patches — Postgres aborts the entire transaction on the
    first error otherwise.
    """
    if engine.dialect.name != "postgresql":
        log.info("schema_hotfix: skipped (dialect=%s)", engine.dialect.name)
        return
    for table, ddl in _PATCHES:
        sql = f"ALTER TABLE {table} {ddl}"
        try:
            with engine.begin() as conn:
                conn.execute(text(sql))
            log.info("schema_hotfix: OK %s", sql)
        except Exception as e:
            # Common cause on first boot: dependent table (e.g. sewing_flows)
            # doesn't exist yet. Next restart, after create_all, will fix it.
            log.warning("schema_hotfix: skipped (%s) -- %s", sql, e)

    for sql in _DATA_FIXES:
        try:
            with engine.begin() as conn:
                conn.execute(text(sql))
            log.info("schema_hotfix: OK %s", sql)
        except Exception as e:
            log.warning("schema_hotfix: skipped (%s) -- %s", sql, e)
