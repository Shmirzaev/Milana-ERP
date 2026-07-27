"""Idempotent schema patches for explicit local/dev schema bootstrap.

Production startup relies on Alembic migrations. This module is only used when
STARTUP_SCHEMA_SYNC=true in non-production environments. Each statement is
`ADD COLUMN IF NOT EXISTS`, so repeated local bootstraps are no-ops once a
column exists.

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
    ("users",       "ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ"),
    ("users",       "ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ"),
    ("users",       "ADD COLUMN IF NOT EXISTS extra_permissions JSON NOT NULL DEFAULT '[]'::json"),
    ("audit_logs",  "ADD COLUMN IF NOT EXISTS prev_hash VARCHAR(64)"),
    ("audit_logs",  "ADD COLUMN IF NOT EXISTS entry_hash VARCHAR(64)"),
    ("work_orders", "ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN NOT NULL DEFAULT FALSE"),
    ("work_orders", "ADD COLUMN IF NOT EXISTS block_reason TEXT"),
    ("work_orders", "ADD COLUMN IF NOT EXISTS deadline TIMESTAMPTZ"),
    ("work_orders", "ADD COLUMN IF NOT EXISTS sewing_flow_id INTEGER REFERENCES sewing_flows(id)"),
    ("sewing_assignments", "ADD COLUMN IF NOT EXISTS production_batch_id INTEGER REFERENCES production_batches(id)"),
    ("payroll_records", "ADD COLUMN IF NOT EXISTS original_scan_uid VARCHAR(128)"),
    ("models",      "ADD COLUMN IF NOT EXISTS sam_minutes NUMERIC(8,2) NOT NULL DEFAULT 0"),
    ("models",      "ADD COLUMN IF NOT EXISTS brand_id INTEGER REFERENCES brands(id)"),
    ("models",      "ADD COLUMN IF NOT EXISTS collection_id INTEGER REFERENCES collections(id)"),
    ("models",      "ADD COLUMN IF NOT EXISTS product_type VARCHAR(64)"),
    ("models",      "ADD COLUMN IF NOT EXISTS season VARCHAR(64)"),
    ("models",      "ADD COLUMN IF NOT EXISTS constructor_employee_id INTEGER REFERENCES employees(id)"),
    ("models",      "ADD COLUMN IF NOT EXISTS designer_employee_id INTEGER REFERENCES employees(id)"),
    ("model_images", "ADD COLUMN IF NOT EXISTS file_name VARCHAR(255)"),
    ("model_images", "ADD COLUMN IF NOT EXISTS content_type VARCHAR(128)"),
    ("model_images", "ADD COLUMN IF NOT EXISTS file_data BYTEA"),
    ("model_images", "ADD COLUMN IF NOT EXISTS image_type VARCHAR(32)"),
    ("model_bom",   "ADD COLUMN IF NOT EXISTS photo_url VARCHAR(512)"),
    ("production_orders", "ADD COLUMN IF NOT EXISTS estimated_material_code VARCHAR(128)"),
    ("production_orders", "ADD COLUMN IF NOT EXISTS estimated_material_amount NUMERIC(14,4)"),
    ("production_orders", "ADD COLUMN IF NOT EXISTS estimated_material_unit VARCHAR(32)"),
    ("production_orders", "ADD COLUMN IF NOT EXISTS printing_instructions TEXT"),
    ("production_orders", "ADD COLUMN IF NOT EXISTS printing_attachments JSONB"),
    ("production_orders", "ADD COLUMN IF NOT EXISTS brand_id INTEGER REFERENCES brands(id)"),
    ("production_orders", "ADD COLUMN IF NOT EXISTS fabric_batch_id INTEGER REFERENCES stock_batches(id)"),
    ("production_order_items", "ADD COLUMN IF NOT EXISTS printing_required BOOLEAN NOT NULL DEFAULT FALSE"),
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
    ("items",       "ADD COLUMN IF NOT EXISTS composition_json JSON NOT NULL DEFAULT '[]'::json"),
    ("items",       "ADD COLUMN IF NOT EXISTS image_url VARCHAR(512)"),
    ("stock_batches", "ADD COLUMN IF NOT EXISTS supplier_id INTEGER REFERENCES suppliers(id)"),
    ("stock_batches", "ADD COLUMN IF NOT EXISTS old_code VARCHAR(64)"),
    ("stock_batches", "ADD COLUMN IF NOT EXISTS color_code VARCHAR(32)"),
    ("stock_batches", "ADD COLUMN IF NOT EXISTS color_status VARCHAR(64)"),
    ("stock_batches", "ADD COLUMN IF NOT EXISTS order_no VARCHAR(64)"),
    ("stock_batches", "ADD COLUMN IF NOT EXISTS width NUMERIC(10,2)"),
    ("stock_batches", "ADD COLUMN IF NOT EXISTS gsm NUMERIC(10,2)"),
    ("stock_batches", "ADD COLUMN IF NOT EXISTS piece_count INTEGER"),
    ("stock_batches", "ADD COLUMN IF NOT EXISTS processes VARCHAR(255)"),
    ("stock_movements", "ADD COLUMN IF NOT EXISTS batch_id INTEGER REFERENCES stock_batches(id)"),
    ("stock_movements", "ADD COLUMN IF NOT EXISTS from_warehouse_id INTEGER REFERENCES warehouses(id)"),
    ("stock_movements", "ADD COLUMN IF NOT EXISTS to_warehouse_id INTEGER REFERENCES warehouses(id)"),
    ("stock_movements", "ADD COLUMN IF NOT EXISTS reference_type VARCHAR(64)"),
    ("stock_movements", "ADD COLUMN IF NOT EXISTS reference_id INTEGER"),
    ("stock_movements", "ADD COLUMN IF NOT EXISTS created_by INTEGER REFERENCES users(id)"),
    ("stock_movements", "ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()"),
    ("tasks",       "ADD COLUMN IF NOT EXISTS entity_type VARCHAR(64)"),
    ("tasks",       "ADD COLUMN IF NOT EXISTS entity_id INTEGER"),
    ("notifications", "ADD COLUMN IF NOT EXISTS link VARCHAR(512)"),
    ("sales_orders", "ADD COLUMN IF NOT EXISTS printing_instructions TEXT"),
    ("sales_orders", "ADD COLUMN IF NOT EXISTS printing_attachments JSONB"),
    ("packages",    "ADD COLUMN IF NOT EXISTS production_batch_id INTEGER REFERENCES production_batches(id)"),
    ("packages",    "ADD COLUMN IF NOT EXISTS weight_kg NUMERIC(14,4)"),
    ("packages",    "ADD COLUMN IF NOT EXISTS storage_cell VARCHAR(32)"),
    ("packages",    "ADD COLUMN IF NOT EXISTS storage_shelf VARCHAR(8)"),
    ("packages",    "ADD COLUMN IF NOT EXISTS storage_placed_at TIMESTAMPTZ"),
    ("bundles",     "ADD COLUMN IF NOT EXISTS qr_code_url VARCHAR(512)"),
    ("bundles",     "ADD COLUMN IF NOT EXISTS production_batch_id INTEGER REFERENCES production_batches(id)"),
    ("bundles",     "ADD COLUMN IF NOT EXISTS sales_order_id INTEGER REFERENCES sales_orders(id)"),
    ("bundles",     "ADD COLUMN IF NOT EXISTS brand_id INTEGER REFERENCES brands(id)"),
    ("bundles",     "ADD COLUMN IF NOT EXISTS collection_id INTEGER REFERENCES collections(id)"),
    ("bundles",     "ADD COLUMN IF NOT EXISTS current_department_id INTEGER REFERENCES departments(id)"),
    ("bundles",     "ADD COLUMN IF NOT EXISTS next_department_id INTEGER REFERENCES departments(id)"),
    ("bundles",     "ADD COLUMN IF NOT EXISTS sewing_factory_code VARCHAR(32)"),
    ("bundles",     "ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'created'"),
    ("bundles",     "ADD COLUMN IF NOT EXISTS created_by INTEGER REFERENCES users(id)"),
    ("bundles",     "ADD COLUMN IF NOT EXISTS notes TEXT"),
    ("bundles",     "ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()"),
    ("bundles",     "ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"),
    ("bundle_scan_logs", "ADD COLUMN IF NOT EXISTS scanned_by INTEGER REFERENCES users(id)"),
    ("bundle_scan_logs", "ADD COLUMN IF NOT EXISTS from_department_id INTEGER REFERENCES departments(id)"),
    ("bundle_scan_logs", "ADD COLUMN IF NOT EXISTS to_department_id INTEGER REFERENCES departments(id)"),
    ("bundle_scan_logs", "ADD COLUMN IF NOT EXISTS location VARCHAR(128)"),
    ("bundle_scan_logs", "ADD COLUMN IF NOT EXISTS scanned_at TIMESTAMPTZ NOT NULL DEFAULT now()"),
    ("cutting_records", "ADD COLUMN IF NOT EXISTS production_batch_id INTEGER REFERENCES production_batches(id)"),
    ("cutting_records", "ADD COLUMN IF NOT EXISTS fabric_batch_id INTEGER REFERENCES stock_batches(id)"),
    ("cutting_records", "ADD COLUMN IF NOT EXISTS input_quantity NUMERIC(14,4) NOT NULL DEFAULT 0"),
    ("cutting_records", "ADD COLUMN IF NOT EXISTS input_unit VARCHAR(32) NOT NULL DEFAULT 'kg'"),
    ("cutting_records", "ADD COLUMN IF NOT EXISTS cut_pieces INTEGER NOT NULL DEFAULT 0"),
    ("cutting_records", "ADD COLUMN IF NOT EXISTS passed_pieces INTEGER NOT NULL DEFAULT 0"),
    ("cutting_records", "ADD COLUMN IF NOT EXISTS defective_pieces INTEGER NOT NULL DEFAULT 0"),
    ("cutting_records", "ADD COLUMN IF NOT EXISTS waste_quantity NUMERIC(14,4) NOT NULL DEFAULT 0"),
    ("cutting_records", "ADD COLUMN IF NOT EXISTS waste_unit VARCHAR(32) NOT NULL DEFAULT 'kg'"),
    ("cutting_records", "ADD COLUMN IF NOT EXISTS layer_material_kg NUMERIC(14,4) NOT NULL DEFAULT 0"),
    ("cutting_records", "ADD COLUMN IF NOT EXISTS beika_kg NUMERIC(14,4) NOT NULL DEFAULT 0"),
    ("cutting_records", "ADD COLUMN IF NOT EXISTS material_rolls_used NUMERIC(14,4) NOT NULL DEFAULT 0"),
    ("cutting_records", "ADD COLUMN IF NOT EXISTS bundle_count INTEGER NOT NULL DEFAULT 0"),
    ("cutting_records", "ADD COLUMN IF NOT EXISTS total_bundled_quantity INTEGER NOT NULL DEFAULT 0"),
    ("cutting_records", "ADD COLUMN IF NOT EXISTS operator_id INTEGER REFERENCES users(id)"),
    ("cutting_records", "ADD COLUMN IF NOT EXISTS notes TEXT"),
    ("cutting_records", "ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()"),
    ("cutting_records", "ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"),
    ("printing_records", "ADD COLUMN IF NOT EXISTS production_batch_id INTEGER REFERENCES production_batches(id)"),
    ("sewing_records", "ADD COLUMN IF NOT EXISTS production_batch_id INTEGER REFERENCES production_batches(id)"),
    ("packaging_records", "ADD COLUMN IF NOT EXISTS production_batch_id INTEGER REFERENCES production_batches(id)"),
    ("waste_records", "ADD COLUMN IF NOT EXISTS production_order_id INTEGER REFERENCES production_orders(id)"),
    ("waste_records", "ADD COLUMN IF NOT EXISTS work_order_id INTEGER REFERENCES work_orders(id)"),
    ("waste_records", "ADD COLUMN IF NOT EXISTS source_department_id INTEGER REFERENCES departments(id)"),
    ("waste_records", "ADD COLUMN IF NOT EXISTS item_id INTEGER REFERENCES items(id)"),
    ("waste_records", "ADD COLUMN IF NOT EXISTS batch_id INTEGER REFERENCES stock_batches(id)"),
    ("waste_records", "ADD COLUMN IF NOT EXISTS reason TEXT"),
    ("waste_records", "ADD COLUMN IF NOT EXISTS sellable BOOLEAN NOT NULL DEFAULT FALSE"),
    ("waste_records", "ADD COLUMN IF NOT EXISTS estimated_value NUMERIC(12,2) NOT NULL DEFAULT 0"),
    ("waste_records", "ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'recorded'"),
    ("waste_records", "ADD COLUMN IF NOT EXISTS created_by INTEGER REFERENCES users(id)"),
    ("waste_records", "ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()"),
    ("waste_records", "ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"),
    ("payroll_adjustments", "ADD COLUMN IF NOT EXISTS adjustment_type VARCHAR(16) NOT NULL DEFAULT 'bonus'"),
]

_TABLE_PATCHES: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS sewing_replacement_requests (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        production_order_id INTEGER NOT NULL REFERENCES production_orders(id),
        sewing_work_order_id INTEGER NOT NULL REFERENCES work_orders(id),
        cutting_work_order_id INTEGER REFERENCES work_orders(id),
        production_batch_id INTEGER REFERENCES production_batches(id),
        sewing_record_id INTEGER NOT NULL REFERENCES sewing_records(id),
        requested_qty INTEGER NOT NULL,
        cut_qty INTEGER NOT NULL DEFAULT 0,
        replaced_qty INTEGER NOT NULL DEFAULT 0,
        status VARCHAR(32) NOT NULL DEFAULT 'waiting_cutting',
        defect_reason VARCHAR(255),
        created_by INTEGER REFERENCES users(id),
        CONSTRAINT uq_sewing_replacements_sewing_record UNIQUE (sewing_record_id),
        CONSTRAINT ck_sewing_replacements_requested_positive CHECK (requested_qty > 0),
        CONSTRAINT ck_sewing_replacements_cut_nonnegative CHECK (cut_qty >= 0),
        CONSTRAINT ck_sewing_replacements_replaced_nonnegative CHECK (replaced_qty >= 0),
        CONSTRAINT ck_sewing_replacements_cut_lte_requested CHECK (cut_qty <= requested_qty),
        CONSTRAINT ck_sewing_replacements_replaced_lte_requested CHECK (replaced_qty <= requested_qty),
        CONSTRAINT ck_sewing_replacements_status CHECK (status IN ('waiting_cutting', 'waiting_sewing', 'completed'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_sewing_replacements_production_order_id ON sewing_replacement_requests(production_order_id)",
    "CREATE INDEX IF NOT EXISTS ix_sewing_replacements_sewing_work_order_id ON sewing_replacement_requests(sewing_work_order_id)",
    "CREATE INDEX IF NOT EXISTS ix_sewing_replacements_cutting_work_order_id ON sewing_replacement_requests(cutting_work_order_id)",
    "CREATE INDEX IF NOT EXISTS ix_sewing_replacements_production_batch_id ON sewing_replacement_requests(production_batch_id)",
    "CREATE INDEX IF NOT EXISTS ix_sewing_replacements_status ON sewing_replacement_requests(status)",
    """
    CREATE TABLE IF NOT EXISTS purchase_requests (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        request_no VARCHAR(64) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'draft',
        sales_order_id INTEGER REFERENCES sales_orders(id),
        production_order_id INTEGER REFERENCES production_orders(id),
        requested_by INTEGER REFERENCES users(id),
        approved_by INTEGER REFERENCES users(id),
        approved_at TIMESTAMPTZ,
        notes TEXT
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_purchase_requests_request_no ON purchase_requests(request_no)",
    """
    CREATE TABLE IF NOT EXISTS purchase_request_lines (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        purchase_request_id INTEGER NOT NULL REFERENCES purchase_requests(id),
        item_id INTEGER NOT NULL REFERENCES items(id),
        required_quantity NUMERIC(14,4) NOT NULL DEFAULT 0,
        requested_quantity NUMERIC(14,4) NOT NULL DEFAULT 0,
        unit VARCHAR(32) NOT NULL,
        available_quantity NUMERIC(14,4) NOT NULL DEFAULT 0,
        shortage_quantity NUMERIC(14,4) NOT NULL DEFAULT 0,
        preferred_supplier_id INTEGER REFERENCES suppliers(id),
        notes TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_purchase_request_lines_purchase_request_id ON purchase_request_lines(purchase_request_id)",
    """
    CREATE TABLE IF NOT EXISTS purchase_orders (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        po_no VARCHAR(64) NOT NULL,
        purchase_request_id INTEGER REFERENCES purchase_requests(id),
        supplier_id INTEGER REFERENCES suppliers(id),
        status VARCHAR(32) NOT NULL DEFAULT 'draft',
        ordered_by INTEGER REFERENCES users(id),
        expected_date TIMESTAMPTZ,
        notes TEXT
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_purchase_orders_po_no ON purchase_orders(po_no)",
    """
    CREATE TABLE IF NOT EXISTS purchase_order_lines (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id),
        item_id INTEGER NOT NULL REFERENCES items(id),
        ordered_quantity NUMERIC(14,4) NOT NULL DEFAULT 0,
        received_quantity NUMERIC(14,4) NOT NULL DEFAULT 0,
        unit VARCHAR(32) NOT NULL,
        unit_cost NUMERIC(12,4) NOT NULL DEFAULT 0,
        warehouse_id INTEGER REFERENCES warehouses(id),
        notes TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_purchase_order_lines_purchase_order_id ON purchase_order_lines(purchase_order_id)",
    """
    CREATE TABLE IF NOT EXISTS package_batch_allocations (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        package_id INTEGER NOT NULL REFERENCES packages(id),
        production_batch_id INTEGER NOT NULL REFERENCES production_batches(id),
        quantity INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_package_batch_allocations_package_id ON package_batch_allocations(package_id)",
    "CREATE INDEX IF NOT EXISTS ix_package_batch_allocations_production_batch_id ON package_batch_allocations(production_batch_id)",
    """
    CREATE TABLE IF NOT EXISTS material_reservations (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        reservation_no VARCHAR(64) NOT NULL UNIQUE,
        production_order_id INTEGER NOT NULL REFERENCES production_orders(id),
        sales_order_id INTEGER REFERENCES sales_orders(id),
        item_id INTEGER NOT NULL REFERENCES items(id),
        stock_batch_id INTEGER REFERENCES stock_batches(id),
        warehouse_id INTEGER REFERENCES warehouses(id),
        reserved_quantity NUMERIC(14,4) NOT NULL,
        consumed_quantity NUMERIC(14,4) NOT NULL DEFAULT 0,
        released_quantity NUMERIC(14,4) NOT NULL DEFAULT 0,
        unit VARCHAR(32) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'reserved',
        reservation_type VARCHAR(32) NOT NULL DEFAULT 'material',
        source VARCHAR(32) NOT NULL DEFAULT 'manual',
        reserved_by INTEGER REFERENCES users(id),
        reserved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        notes TEXT,
        CONSTRAINT ck_material_reservations_reserved_positive CHECK (reserved_quantity > 0),
        CONSTRAINT ck_material_reservations_consumed_nonnegative CHECK (consumed_quantity >= 0),
        CONSTRAINT ck_material_reservations_released_nonnegative CHECK (released_quantity >= 0),
        CONSTRAINT ck_material_reservations_consumed_released_lte_reserved
            CHECK (consumed_quantity + released_quantity <= reserved_quantity)
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_material_reservations_reservation_no ON material_reservations(reservation_no)",
    "CREATE INDEX IF NOT EXISTS ix_material_reservations_production_order_id ON material_reservations(production_order_id)",
    "CREATE INDEX IF NOT EXISTS ix_material_reservations_sales_order_id ON material_reservations(sales_order_id)",
    "CREATE INDEX IF NOT EXISTS ix_material_reservations_item_id ON material_reservations(item_id)",
    "CREATE INDEX IF NOT EXISTS ix_material_reservations_stock_batch_id ON material_reservations(stock_batch_id)",
    "CREATE INDEX IF NOT EXISTS ix_material_reservations_warehouse_id ON material_reservations(warehouse_id)",
    "CREATE INDEX IF NOT EXISTS ix_material_reservations_status ON material_reservations(status)",
    """
    CREATE TABLE IF NOT EXISTS payroll_periods (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        period_no VARCHAR(64) NOT NULL UNIQUE,
        name VARCHAR(128) NOT NULL,
        start_date TIMESTAMPTZ NOT NULL,
        end_date TIMESTAMPTZ NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'open',
        created_by INTEGER REFERENCES users(id),
        approved_by INTEGER REFERENCES users(id),
        approved_at TIMESTAMPTZ,
        notes TEXT,
        CONSTRAINT ck_payroll_periods_status
            CHECK (status IN ('draft', 'open', 'locked', 'approved', 'paid', 'cancelled'))
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_payroll_periods_period_no ON payroll_periods(period_no)",
    """
    CREATE TABLE IF NOT EXISTS payroll_records (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        payroll_period_id INTEGER REFERENCES payroll_periods(id),
        scan_uid VARCHAR(128) UNIQUE,
        dedupe_key VARCHAR(64) NOT NULL UNIQUE,
        employee_id INTEGER NOT NULL REFERENCES employees(id),
        employee_user_id INTEGER REFERENCES users(id),
        production_order_id INTEGER REFERENCES production_orders(id),
        sales_order_id INTEGER REFERENCES sales_orders(id),
        work_order_id INTEGER REFERENCES work_orders(id),
        production_batch_id INTEGER REFERENCES production_batches(id),
        model_id INTEGER REFERENCES models(id),
        production_no VARCHAR(64),
        sales_order_no VARCHAR(64),
        batch_no VARCHAR(64),
        model_code VARCHAR(64),
        operation_section VARCHAR(64),
        operation_code VARCHAR(64),
        operation_name VARCHAR(255),
        quantity NUMERIC(14,4) NOT NULL DEFAULT 0,
        rate_per_piece NUMERIC(14,4) NOT NULL DEFAULT 0,
        currency VARCHAR(8) NOT NULL DEFAULT 'UZS',
        total_amount NUMERIC(14,2) NOT NULL DEFAULT 0,
        scanned_by INTEGER REFERENCES users(id),
        scanned_at TIMESTAMPTZ NOT NULL,
        source VARCHAR(64) NOT NULL DEFAULT 'payroll_scan',
        raw_employee_json JSONB,
        raw_work_json JSONB,
        status VARCHAR(32) NOT NULL DEFAULT 'recorded',
        notes TEXT,
        CONSTRAINT ck_payroll_records_quantity_nonnegative CHECK (quantity >= 0),
        CONSTRAINT ck_payroll_records_rate_nonnegative CHECK (rate_per_piece >= 0),
        CONSTRAINT ck_payroll_records_total_nonnegative CHECK (total_amount >= 0),
        CONSTRAINT ck_payroll_records_status CHECK (status IN ('recorded', 'voided', 'approved', 'paid'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_payroll_records_payroll_period_id ON payroll_records(payroll_period_id)",
    "CREATE INDEX IF NOT EXISTS ix_payroll_records_employee_id ON payroll_records(employee_id)",
    "CREATE INDEX IF NOT EXISTS ix_payroll_records_scan_uid ON payroll_records(scan_uid)",
    "CREATE INDEX IF NOT EXISTS ix_payroll_records_dedupe_key ON payroll_records(dedupe_key)",
    """
    CREATE TABLE IF NOT EXISTS payroll_adjustments (
        id SERIAL PRIMARY KEY,
        payroll_period_id INTEGER REFERENCES payroll_periods(id),
        employee_id INTEGER NOT NULL REFERENCES employees(id),
        adjustment_type VARCHAR(16) NOT NULL DEFAULT 'bonus',
        amount NUMERIC(14,2) NOT NULL,
        currency VARCHAR(8) NOT NULL DEFAULT 'UZS',
        reason VARCHAR(255) NOT NULL,
        created_by INTEGER REFERENCES users(id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_payroll_adjustments_amount_nonnegative CHECK (amount >= 0)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_payroll_adjustments_payroll_period_id ON payroll_adjustments(payroll_period_id)",
    "CREATE INDEX IF NOT EXISTS ix_payroll_adjustments_employee_id ON payroll_adjustments(employee_id)",
    """
    CREATE TABLE IF NOT EXISTS forecast_recommendations (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        recommendation_type VARCHAR(64) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'open',
        model_id INTEGER REFERENCES models(id),
        item_id INTEGER REFERENCES items(id),
        brand_id INTEGER REFERENCES brands(id),
        collection_id INTEGER REFERENCES collections(id),
        color VARCHAR(64),
        size VARCHAR(32),
        suggested_quantity NUMERIC(14,4) NOT NULL,
        unit VARCHAR(32),
        confidence VARCHAR(16),
        reason TEXT,
        source_json JSONB,
        created_by INTEGER REFERENCES users(id),
        reviewed_by INTEGER REFERENCES users(id),
        reviewed_at TIMESTAMPTZ
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_forecast_recommendations_recommendation_type ON forecast_recommendations(recommendation_type)",
    "CREATE INDEX IF NOT EXISTS ix_forecast_recommendations_status ON forecast_recommendations(status)",
    """
    CREATE TABLE IF NOT EXISTS idempotency_records (
        id SERIAL PRIMARY KEY,
        scope VARCHAR(128) NOT NULL,
        key VARCHAR(128) NOT NULL,
        request_hash VARCHAR(64) NOT NULL,
        response_json JSONB NOT NULL,
        status_code INTEGER NOT NULL DEFAULT 200,
        user_id INTEGER REFERENCES users(id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_idempotency_records_scope_key UNIQUE (scope, key)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_idempotency_records_scope ON idempotency_records(scope)",
    "CREATE INDEX IF NOT EXISTS ix_idempotency_records_created_at ON idempotency_records(created_at)",
]

_DATA_FIXES: list[str] = [
    "CREATE INDEX IF NOT EXISTS ix_bundles_production_batch_id ON bundles(production_batch_id)",
    "ALTER TABLE stock_movements ALTER COLUMN created_at SET DEFAULT now()",
    "ALTER TABLE material_reservations ALTER COLUMN created_at SET DEFAULT now()",
    "ALTER TABLE material_reservations ALTER COLUMN updated_at SET DEFAULT now()",
    "ALTER TABLE material_reservations ALTER COLUMN consumed_quantity SET DEFAULT 0",
    "ALTER TABLE material_reservations ALTER COLUMN released_quantity SET DEFAULT 0",
    "ALTER TABLE material_reservations ALTER COLUMN status SET DEFAULT 'reserved'",
    "ALTER TABLE material_reservations ALTER COLUMN reservation_type SET DEFAULT 'material'",
    "ALTER TABLE material_reservations ALTER COLUMN source SET DEFAULT 'manual'",
    "ALTER TABLE material_reservations ALTER COLUMN reserved_at SET DEFAULT now()",
    "ALTER TABLE bundles ALTER COLUMN created_at SET DEFAULT now()",
    "ALTER TABLE bundles ALTER COLUMN updated_at SET DEFAULT now()",
    "ALTER TABLE bundles ALTER COLUMN status SET DEFAULT 'created'",
    "ALTER TABLE bundle_scan_logs ALTER COLUMN scanned_at SET DEFAULT now()",
    "ALTER TABLE cutting_records ALTER COLUMN created_at SET DEFAULT now()",
    "ALTER TABLE cutting_records ALTER COLUMN updated_at SET DEFAULT now()",
    "ALTER TABLE cutting_records ALTER COLUMN input_unit SET DEFAULT 'kg'",
    "ALTER TABLE cutting_records ALTER COLUMN waste_unit SET DEFAULT 'kg'",
    "ALTER TABLE cutting_records ALTER COLUMN bundle_count SET DEFAULT 0",
    "ALTER TABLE cutting_records ALTER COLUMN total_bundled_quantity SET DEFAULT 0",
    "ALTER TABLE waste_records ALTER COLUMN created_at SET DEFAULT now()",
    "ALTER TABLE waste_records ALTER COLUMN updated_at SET DEFAULT now()",
    "ALTER TABLE waste_records ALTER COLUMN sellable SET DEFAULT FALSE",
    "ALTER TABLE waste_records ALTER COLUMN estimated_value SET DEFAULT 0",
    "ALTER TABLE waste_records ALTER COLUMN status SET DEFAULT 'recorded'",
    "UPDATE items SET unit = 'kg' WHERE lower(trim(unit)) = 'meter'",
    "UPDATE stock_batches SET unit = 'kg' WHERE lower(trim(unit)) = 'meter'",
    "UPDATE stock_movements SET unit = 'kg' WHERE lower(trim(unit)) = 'meter'",
    "UPDATE model_bom SET unit = 'kg' WHERE lower(trim(unit)) = 'meter'",
    "UPDATE cutting_records SET input_unit = 'kg' WHERE lower(trim(input_unit)) = 'meter'",
    "UPDATE collections SET year = 2024 WHERE year IS NULL",
    "ALTER TABLE collections ALTER COLUMN year SET DEFAULT 2024",
    "ALTER TABLE collections ALTER COLUMN year SET NOT NULL",
    "ALTER TABLE payments ALTER COLUMN invoice_id DROP NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_stock_batches_item_warehouse ON stock_batches(item_id, warehouse_id)",
    "CREATE INDEX IF NOT EXISTS ix_stock_movements_item_created ON stock_movements(item_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_stock_movements_reference ON stock_movements(reference_type, reference_id)",
    "CREATE INDEX IF NOT EXISTS ix_production_orders_status_id ON production_orders(status, id)",
    "CREATE INDEX IF NOT EXISTS ix_production_orders_sales_status ON production_orders(sales_order_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_work_orders_production_status ON work_orders(production_order_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_work_orders_batch_operation ON work_orders(production_batch_id, operation)",
    "CREATE INDEX IF NOT EXISTS ix_sewing_assignments_production_batch_id ON sewing_assignments(production_batch_id)",
    "CREATE INDEX IF NOT EXISTS ix_packages_status_id ON packages(status, id)",
    "CREATE INDEX IF NOT EXISTS ix_packages_production_status ON packages(production_order_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_packages_sales_status ON packages(sales_order_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_packages_storage_status ON packages(storage_cell, storage_shelf, status)",
    "CREATE INDEX IF NOT EXISTS ix_package_scan_logs_package_scanned ON package_scan_logs(package_id, scanned_at)",
    "CREATE INDEX IF NOT EXISTS ix_shipments_status_id ON shipments(status, id)",
    "CREATE INDEX IF NOT EXISTS ix_shipments_sales_status ON shipments(sales_order_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_shipment_scan_logs_shipment_package ON shipment_scan_logs(shipment_id, package_id)",
    "CREATE INDEX IF NOT EXISTS ix_audit_logs_entity ON audit_logs(entity_type, entity_id)",
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
    SET batch_no = LPAD(pb.production_order_id::text, 4, '0') || '-' || LPAD(r.rn::text, 2, '0')
    FROM ranked r
    WHERE pb.id = r.id
      AND (pb.batch_no IS NULL OR pb.batch_no !~ '^[0-9]{4,}-[0-9]{2}(-[0-9]+)?$')
    """,
    """
    WITH bundle_rank AS (
        SELECT
            id,
            production_order_id,
            ROW_NUMBER() OVER (
                PARTITION BY production_order_id
                ORDER BY created_at, id
            ) AS rn
        FROM bundles
        WHERE production_batch_id IS NULL
    ),
    cutting_ranges AS (
        SELECT
            wo.production_order_id,
            cr.production_batch_id,
            SUM(cr.bundle_count) OVER (
                PARTITION BY wo.production_order_id
                ORDER BY cr.created_at, cr.id
            ) - cr.bundle_count + 1 AS start_rn,
            SUM(cr.bundle_count) OVER (
                PARTITION BY wo.production_order_id
                ORDER BY cr.created_at, cr.id
            ) AS end_rn
        FROM cutting_records cr
        JOIN work_orders wo ON wo.id = cr.work_order_id
        WHERE cr.production_batch_id IS NOT NULL
          AND cr.bundle_count > 0
    )
    UPDATE bundles b
    SET production_batch_id = cr.production_batch_id
    FROM bundle_rank br
    JOIN cutting_ranges cr
      ON cr.production_order_id = br.production_order_id
     AND br.rn BETWEEN cr.start_rn AND cr.end_rn
    WHERE b.id = br.id
      AND b.production_batch_id IS NULL
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
    for sql in _TABLE_PATCHES:
        try:
            with engine.begin() as conn:
                conn.execute(text(sql))
            log.info("schema_hotfix: OK %s", sql)
        except Exception as e:
            log.warning("schema_hotfix: skipped (%s) -- %s", sql, e)

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
