"""Idempotent schema patches that run automatically on backend startup.

Hosted environments do not always expose an interactive Shell, so we cannot
count on running ad-hoc ALTER TABLE commands by hand. This module performs
those changes via SQLAlchemy on every
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
    ("users",       "ADD COLUMN IF NOT EXISTS tokens_valid_from TIMESTAMPTZ"),
    ("work_orders", "ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN NOT NULL DEFAULT FALSE"),
    ("work_orders", "ADD COLUMN IF NOT EXISTS block_reason TEXT"),
    ("work_orders", "ADD COLUMN IF NOT EXISTS deadline TIMESTAMPTZ"),
    ("work_orders", "ADD COLUMN IF NOT EXISTS sewing_flow_id INTEGER REFERENCES sewing_flows(id)"),
    ("models",      "ADD COLUMN IF NOT EXISTS sam_minutes NUMERIC(8,2) NOT NULL DEFAULT 0"),
    ("models",      "ADD COLUMN IF NOT EXISTS brand_id INTEGER REFERENCES brands(id)"),
    ("models",      "ADD COLUMN IF NOT EXISTS collection_id INTEGER REFERENCES collections(id)"),
    ("models",      "ADD COLUMN IF NOT EXISTS product_type VARCHAR(64)"),
    ("models",      "ADD COLUMN IF NOT EXISTS season VARCHAR(64)"),
    ("models",      "ADD COLUMN IF NOT EXISTS constructor_employee_id INTEGER REFERENCES employees(id)"),
    ("models",      "ADD COLUMN IF NOT EXISTS designer_employee_id INTEGER REFERENCES employees(id)"),
    ("model_images", "ADD COLUMN IF NOT EXISTS file_name VARCHAR(255)"),
    ("model_images", "ADD COLUMN IF NOT EXISTS content_type VARCHAR(128)"),
    ("model_images", "ADD COLUMN IF NOT EXISTS image_type VARCHAR(32)"),
    ("production_orders", "ADD COLUMN IF NOT EXISTS estimated_material_code VARCHAR(128)"),
    ("production_orders", "ADD COLUMN IF NOT EXISTS estimated_material_amount NUMERIC(14,4)"),
    ("production_orders", "ADD COLUMN IF NOT EXISTS estimated_material_unit VARCHAR(32)"),
    ("cutting_passports", "ADD COLUMN IF NOT EXISTS model_code VARCHAR(128)"),
    ("cutting_passports", "ADD COLUMN IF NOT EXISTS image_ref VARCHAR(512)"),
    ("cutting_passports", "ADD COLUMN IF NOT EXISTS operator_name_manual VARCHAR(128)"),
    ("cutting_passports", "ADD COLUMN IF NOT EXISTS order_no VARCHAR(128)"),
    ("invoices",    "ADD COLUMN IF NOT EXISTS external_source VARCHAR(32)"),
    ("invoices",    "ADD COLUMN IF NOT EXISTS external_id VARCHAR(128)"),
    ("payments",    "ADD COLUMN IF NOT EXISTS external_source VARCHAR(32)"),
    ("payments",    "ADD COLUMN IF NOT EXISTS external_id VARCHAR(128)"),
    ("payments",    "ADD COLUMN IF NOT EXISTS customer_id INTEGER REFERENCES customers(id)"),
    ("items",       "ADD COLUMN IF NOT EXISTS reorder_level NUMERIC(14,4) NOT NULL DEFAULT 0"),
    ("tasks",       "ADD COLUMN IF NOT EXISTS entity_type VARCHAR(64)"),
    ("tasks",       "ADD COLUMN IF NOT EXISTS entity_id INTEGER"),
    ("notifications", "ADD COLUMN IF NOT EXISTS link VARCHAR(512)"),
    ("sales_orders", "ADD COLUMN IF NOT EXISTS printing_instructions TEXT"),
    ("sales_orders", "ADD COLUMN IF NOT EXISTS printing_attachments JSONB"),
    ("packages",    "ADD COLUMN IF NOT EXISTS production_batch_id INTEGER REFERENCES production_batches(id)"),
    ("packages",    "ADD COLUMN IF NOT EXISTS storage_cell VARCHAR(32)"),
    ("packages",    "ADD COLUMN IF NOT EXISTS storage_shelf VARCHAR(8)"),
    ("packages",    "ADD COLUMN IF NOT EXISTS storage_placed_at TIMESTAMPTZ"),
    ("bundles",     "ADD COLUMN IF NOT EXISTS sewing_factory_code VARCHAR(32)"),
    ("cutting_records", "ADD COLUMN IF NOT EXISTS production_batch_id INTEGER REFERENCES production_batches(id)"),
    ("printing_records", "ADD COLUMN IF NOT EXISTS production_batch_id INTEGER REFERENCES production_batches(id)"),
    ("sewing_records", "ADD COLUMN IF NOT EXISTS production_batch_id INTEGER REFERENCES production_batches(id)"),
    ("packaging_records", "ADD COLUMN IF NOT EXISTS production_batch_id INTEGER REFERENCES production_batches(id)"),
]

_DATA_FIXES: list[str] = [
    "UPDATE items SET unit = 'kg' WHERE lower(trim(unit)) = 'meter'",
    "UPDATE stock_batches SET unit = 'kg' WHERE lower(trim(unit)) = 'meter'",
    "UPDATE stock_movements SET unit = 'kg' WHERE lower(trim(unit)) = 'meter'",
    "UPDATE model_bom SET unit = 'kg' WHERE lower(trim(unit)) = 'meter'",
    "UPDATE cutting_records SET input_unit = 'kg' WHERE lower(trim(input_unit)) = 'meter'",
    "UPDATE collections SET year = 2024 WHERE year IS NULL",
    "ALTER TABLE collections ALTER COLUMN year SET DEFAULT 2024",
    "ALTER TABLE collections ALTER COLUMN year SET NOT NULL",
    "ALTER TABLE payments ALTER COLUMN invoice_id DROP NOT NULL",
    """
    UPDATE payments p
    SET customer_id = so.customer_id
    FROM invoices i
    JOIN sales_orders so ON so.id = i.sales_order_id
    WHERE p.invoice_id = i.id
      AND p.customer_id IS NULL
      AND so.customer_id IS NOT NULL
    """,
    """
    WITH ranked AS (
        SELECT
            id,
            production_order_id,
            ROW_NUMBER() OVER (
                PARTITION BY production_order_id
                ORDER BY COALESCE(batch_index, 0), id
            ) AS rn
        FROM production_batches
    )
    UPDATE production_batches pb
    SET batch_no = 'BT-' || LPAD(pb.production_order_id::text, 4, '0') || '-' || LPAD(r.rn::text, 2, '0')
    FROM ranked r
    WHERE pb.id = r.id
      AND (pb.batch_no IS NULL OR pb.batch_no !~ '^BT-[0-9]{4,}-[0-9]{2}$')
    """,
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
