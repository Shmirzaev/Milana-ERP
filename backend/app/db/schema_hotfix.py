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
# by Base.metadata.create_all (called in seed.py) must exist first.
_PATCHES: list[tuple[str, str]] = [
    ("work_orders", "ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN NOT NULL DEFAULT FALSE"),
    ("work_orders", "ADD COLUMN IF NOT EXISTS block_reason TEXT"),
    ("work_orders", "ADD COLUMN IF NOT EXISTS deadline TIMESTAMPTZ"),
    ("work_orders", "ADD COLUMN IF NOT EXISTS sewing_flow_id INTEGER REFERENCES sewing_flows(id)"),
    ("models",      "ADD COLUMN IF NOT EXISTS sam_minutes NUMERIC(8,2) NOT NULL DEFAULT 0"),
]


def run(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        log.info("schema_hotfix: skipped (dialect=%s)", engine.dialect.name)
        return
    with engine.begin() as conn:
        for table, ddl in _PATCHES:
            sql = f"ALTER TABLE {table} {ddl}"
            try:
                conn.execute(text(sql))
                log.info("schema_hotfix: OK %s", sql)
            except Exception as e:  # pragma: no cover
                # Most common cause: dependent table (e.g. sewing_flows) doesn't
                # exist yet because seed.create_all hasn't run. We log and
                # continue — the next deploy after seed runs will fix it.
                log.warning("schema_hotfix: skipped (%s) -- %s", sql, e)
