"""add idempotency records, constraints, and reporting indexes

Revision ID: 0028_idempotency
Revises: 0027_payroll_adjustment_types
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa


revision = "0028_idempotency"
down_revision = "0027_payroll_adjustment_types"
branch_labels = None
depends_on = None


def _has_index(inspector, table_name: str, name: str) -> bool:
    return any(index.get("name") == name for index in inspector.get_indexes(table_name))


def _has_check(inspector, table_name: str, name: str) -> bool:
    return any(check.get("name") == name for check in inspector.get_check_constraints(table_name))


def _has_unique(inspector, table_name: str, name: str) -> bool:
    return any(constraint.get("name") == name for constraint in inspector.get_unique_constraints(table_name))


def _create_index_if_missing(inspector, table_name: str, name: str, columns: list[str]) -> None:
    if table_name in inspector.get_table_names() and not _has_index(inspector, table_name, name):
        op.create_index(name, table_name, columns)


def _ensure_valid_rows(bind, table_name: str, constraint_name: str, condition: str) -> None:
    row = bind.execute(sa.text(f"SELECT id FROM {table_name} WHERE NOT ({condition}) LIMIT 1")).first()
    if row:
        raise RuntimeError(
            f"{table_name} contains data that violates {constraint_name}; "
            f"clean row id={row[0]} before running this migration."
        )


def _create_check_if_missing(inspector, bind, table_name: str, name: str, condition: str) -> None:
    if table_name not in inspector.get_table_names() or _has_check(inspector, table_name, name):
        return
    _ensure_valid_rows(bind, table_name, name, condition)
    op.create_check_constraint(name, table_name, condition)


def _ensure_no_duplicate_groups(bind, table_name: str, constraint_name: str, columns: list[str], where: str | None = None) -> None:
    cols = ", ".join(columns)
    where_sql = f"WHERE {where}" if where else ""
    row = bind.execute(
        sa.text(
            f"SELECT {cols}, COUNT(*) FROM {table_name} "
            f"{where_sql} GROUP BY {cols} HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if row:
        raise RuntimeError(
            f"{table_name} contains duplicate rows for {constraint_name}; "
            "deduplicate the grouped columns before running this migration."
        )


def _create_unique_if_missing(
    inspector,
    bind,
    table_name: str,
    name: str,
    columns: list[str],
    where: str | None = None,
) -> None:
    if table_name not in inspector.get_table_names() or _has_unique(inspector, table_name, name):
        return
    _ensure_no_duplicate_groups(bind, table_name, name, columns, where=where)
    op.create_unique_constraint(name, table_name, columns)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "idempotency_records" not in tables:
        op.create_table(
            "idempotency_records",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("scope", sa.String(length=128), nullable=False),
            sa.Column("key", sa.String(length=128), nullable=False),
            sa.Column("request_hash", sa.String(length=64), nullable=False),
            sa.Column("response_json", sa.JSON(), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=False, server_default="200"),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("scope", "key", name="uq_idempotency_records_scope_key"),
        )

    inspector = sa.inspect(bind)
    _create_index_if_missing(inspector, "idempotency_records", "ix_idempotency_records_scope", ["scope"])
    _create_index_if_missing(inspector, "idempotency_records", "ix_idempotency_records_created_at", ["created_at"])
    _create_index_if_missing(inspector, "stock_batches", "ix_stock_batches_item_warehouse", ["item_id", "warehouse_id"])
    _create_index_if_missing(inspector, "stock_movements", "ix_stock_movements_item_created", ["item_id", "created_at"])
    _create_index_if_missing(inspector, "stock_movements", "ix_stock_movements_reference", ["reference_type", "reference_id"])
    _create_index_if_missing(inspector, "production_orders", "ix_production_orders_status_id", ["status", "id"])
    _create_index_if_missing(inspector, "production_orders", "ix_production_orders_sales_status", ["sales_order_id", "status"])
    _create_index_if_missing(inspector, "work_orders", "ix_work_orders_production_status", ["production_order_id", "status"])
    _create_index_if_missing(inspector, "work_orders", "ix_work_orders_batch_operation", ["production_batch_id", "operation"])
    _create_index_if_missing(inspector, "packages", "ix_packages_status_id", ["status", "id"])
    _create_index_if_missing(inspector, "packages", "ix_packages_production_status", ["production_order_id", "status"])
    _create_index_if_missing(inspector, "packages", "ix_packages_sales_status", ["sales_order_id", "status"])
    _create_index_if_missing(inspector, "packages", "ix_packages_storage_status", ["storage_cell", "storage_shelf", "status"])
    _create_index_if_missing(inspector, "package_scan_logs", "ix_package_scan_logs_package_scanned", ["package_id", "scanned_at"])
    _create_index_if_missing(inspector, "shipments", "ix_shipments_status_id", ["status", "id"])
    _create_index_if_missing(inspector, "shipments", "ix_shipments_sales_status", ["sales_order_id", "status"])
    _create_index_if_missing(inspector, "shipment_scan_logs", "ix_shipment_scan_logs_shipment_package", ["shipment_id", "package_id"])
    _create_index_if_missing(inspector, "audit_logs", "ix_audit_logs_entity", ["entity_type", "entity_id"])

    if bind.dialect.name == "sqlite":
        return

    check_constraints = [
        ("items", "ck_items_default_cost_nonnegative", "default_cost >= 0"),
        ("items", "ck_items_reorder_level_nonnegative", "reorder_level >= 0"),
        ("stock_batches", "ck_stock_batches_quantity_nonnegative", "quantity >= 0"),
        ("stock_batches", "ck_stock_batches_cost_nonnegative", "cost_per_unit >= 0"),
        ("stock_batches", "ck_stock_batches_piece_count_nonnegative", "piece_count IS NULL OR piece_count >= 0"),
        ("stock_batches", "ck_stock_batches_qc_status", "qc_status IN ('pending', 'passed', 'failed', 'rejected', 'hold')"),
        ("stock_movements", "ck_stock_movements_quantity_nonnegative", "quantity >= 0"),
        (
            "stock_movements",
            "ck_stock_movements_type",
            "movement_type IN ('receive', 'transfer', 'issue', 'consume', 'adjustment', 'return', 'produce', 'waste', 'shipment')",
        ),
        ("production_orders", "ck_production_orders_planned_quantity_nonnegative", "planned_quantity >= 0"),
        ("production_batches", "ck_production_batches_index_positive", "batch_index > 0"),
        ("production_batches", "ck_production_batches_planned_quantity_nonnegative", "planned_quantity >= 0"),
        ("production_order_items", "ck_production_order_items_planned_nonnegative", "planned_quantity >= 0"),
        ("production_order_items", "ck_production_order_items_completed_nonnegative", "completed_quantity >= 0"),
        ("work_orders", "ck_work_orders_planned_input_nonnegative", "planned_input_qty >= 0"),
        ("work_orders", "ck_work_orders_planned_output_nonnegative", "planned_output_qty >= 0"),
        ("work_orders", "ck_work_orders_actual_input_nonnegative", "actual_input_qty >= 0"),
        ("work_orders", "ck_work_orders_actual_output_nonnegative", "actual_output_qty >= 0"),
        ("work_orders", "ck_work_orders_passed_nonnegative", "passed_qty >= 0"),
        ("work_orders", "ck_work_orders_failed_nonnegative", "failed_qty >= 0"),
        ("work_orders", "ck_work_orders_rework_nonnegative", "rework_qty >= 0"),
        (
            "work_orders",
            "ck_work_orders_status",
            "status IN ('new', 'planning', 'waiting', 'pending', 'ready', 'collected', 'in_progress', 'paused', 'completed', 'rejected', 'cancelled')",
        ),
        ("cutting_records", "ck_cutting_records_input_nonnegative", "input_quantity >= 0"),
        ("cutting_records", "ck_cutting_records_cut_nonnegative", "cut_pieces >= 0"),
        ("cutting_records", "ck_cutting_records_passed_nonnegative", "passed_pieces >= 0"),
        ("cutting_records", "ck_cutting_records_defective_nonnegative", "defective_pieces >= 0"),
        ("cutting_records", "ck_cutting_records_waste_nonnegative", "waste_quantity >= 0"),
        ("cutting_records", "ck_cutting_records_bundle_count_nonnegative", "bundle_count >= 0"),
        ("cutting_records", "ck_cutting_records_total_bundled_nonnegative", "total_bundled_quantity >= 0"),
        ("printing_records", "ck_printing_records_input_nonnegative", "input_qty >= 0"),
        ("printing_records", "ck_printing_records_printed_nonnegative", "printed_qty >= 0"),
        ("printing_records", "ck_printing_records_passed_nonnegative", "passed_qty >= 0"),
        ("printing_records", "ck_printing_records_rejected_nonnegative", "rejected_qty >= 0"),
        ("sewing_records", "ck_sewing_records_input_nonnegative", "input_qty >= 0"),
        ("sewing_records", "ck_sewing_records_sewn_nonnegative", "sewn_qty >= 0"),
        ("sewing_records", "ck_sewing_records_passed_nonnegative", "passed_qty >= 0"),
        ("sewing_records", "ck_sewing_records_failed_nonnegative", "failed_qty >= 0"),
        ("sewing_records", "ck_sewing_records_rework_nonnegative", "rework_qty >= 0"),
        ("sewing_records", "ck_sewing_records_rejected_nonnegative", "rejected_qty >= 0"),
        ("packaging_records", "ck_packaging_records_input_nonnegative", "input_qty >= 0"),
        ("packaging_records", "ck_packaging_records_packed_nonnegative", "packed_qty >= 0"),
        ("packaging_records", "ck_packaging_records_damaged_nonnegative", "damaged_qty >= 0"),
        ("packaging_records", "ck_packaging_records_package_count_nonnegative", "package_count >= 0"),
        ("packaging_records", "ck_packaging_records_total_packed_nonnegative", "total_packed_quantity >= 0"),
        ("quality_checks", "ck_quality_checks_checked_nonnegative", "checked_qty >= 0"),
        ("quality_checks", "ck_quality_checks_passed_nonnegative", "passed_qty >= 0"),
        ("quality_checks", "ck_quality_checks_failed_nonnegative", "failed_qty >= 0"),
        ("quality_checks", "ck_quality_checks_severity", "severity IN ('low', 'medium', 'high', 'critical')"),
        ("sales_orders", "ck_sales_orders_total_nonnegative", "total_amount >= 0"),
        (
            "sales_orders",
            "ck_sales_orders_status",
            "status IN ('draft', 'pending_sales_approval', 'confirmed', 'planning', 'planning_approved', 'in_production', 'production', 'cutting', 'printing', 'sewing', 'packaging', 'storage', 'ready_to_ship', 'ready', 'reserved', 'shipped', 'delivered', 'closed', 'cancelled')",
        ),
        ("sales_order_items", "ck_sales_order_items_quantity_nonnegative", "quantity >= 0"),
        ("sales_order_items", "ck_sales_order_items_unit_price_nonnegative", "unit_price >= 0"),
        ("shipments", "ck_shipments_status", "status IN ('draft', 'created', 'shipped', 'delivered', 'cancelled')"),
        ("shipment_packages", "ck_shipment_packages_quantity_positive", "quantity > 0"),
        ("invoices", "ck_invoices_amount_nonnegative", "amount >= 0"),
        ("invoices", "ck_invoices_status", "status IN ('unpaid', 'partially_paid', 'paid', 'void', 'cancelled')"),
        ("payments", "ck_payments_amount_positive", "amount > 0"),
        ("bundles", "ck_bundles_quantity_positive", "quantity > 0"),
        (
            "bundles",
            "ck_bundles_status",
            "status IN ('created', 'sent_to_printing', 'received_printing', 'sent_to_sewing', 'received_sewing', 'cancelled')",
        ),
        ("packages", "ck_packages_total_quantity_nonnegative", "total_quantity >= 0"),
        ("packages", "ck_packages_capacity_positive", "capacity > 0"),
        ("packages", "ck_packages_weight_nonnegative", "weight_kg IS NULL OR weight_kg >= 0"),
        ("packages", "ck_packages_status", "status IN ('packed', 'received_in_storage', 'reserved', 'shipped', 'delivered', 'damaged')"),
        ("package_items", "ck_package_items_quantity_positive", "quantity > 0"),
        ("package_batch_allocations", "ck_package_batch_allocations_quantity_positive", "quantity > 0"),
        ("package_change_requests", "ck_package_change_requests_type", "request_type IN ('edit', 'delete')"),
        ("package_change_requests", "ck_package_change_requests_status", "status IN ('pending', 'approved', 'rejected')"),
        ("finished_goods_stock", "ck_finished_goods_quantity_nonnegative", "quantity >= 0"),
        ("finished_goods_stock", "ck_finished_goods_available_nonnegative", "available_qty >= 0"),
        ("finished_goods_stock", "ck_finished_goods_reserved_nonnegative", "reserved_qty >= 0"),
        ("finished_goods_stock", "ck_finished_goods_sold_nonnegative", "sold_qty >= 0"),
        ("finished_goods_stock", "ck_finished_goods_cost_nonnegative", "cost_per_piece >= 0"),
        ("finished_goods_stock", "ck_finished_goods_price_nonnegative", "selling_price >= 0"),
        ("finished_goods_stock", "ck_finished_goods_status", "status IN ('available', 'reserved', 'sold', 'damaged')"),
        ("stock_reservations", "ck_stock_reservations_quantity_positive", "quantity > 0"),
        ("material_reservations", "ck_material_reservations_status", "status IN ('reserved', 'partially_consumed', 'consumed', 'released', 'cancelled')"),
        ("material_reservations", "ck_material_reservations_type", "reservation_type IN ('material', 'accessory', 'packaging')"),
        ("material_reservations", "ck_material_reservations_source", "source IN ('manual', 'auto_bom', 'planning')"),
    ]
    inspector = sa.inspect(bind)
    for table_name, name, condition in check_constraints:
        _create_check_if_missing(inspector, bind, table_name, name, condition)
        inspector = sa.inspect(bind)

    unique_constraints = [
        ("production_batches", "uq_production_batches_order_batch_no", ["production_order_id", "batch_no"], None),
        (
            "work_orders",
            "uq_work_orders_order_batch_operation",
            ["production_order_id", "production_batch_id", "operation"],
            "production_batch_id IS NOT NULL",
        ),
        ("shipment_packages", "uq_shipment_packages_shipment_package", ["shipment_id", "package_id"], None),
        ("package_batch_allocations", "uq_package_batch_allocations_package_batch", ["package_id", "production_batch_id"], None),
        (
            "stock_reservations",
            "uq_stock_reservations_order_stock_package",
            ["sales_order_id", "finished_goods_stock_id", "package_id"],
            "package_id IS NOT NULL",
        ),
    ]
    inspector = sa.inspect(bind)
    for table_name, name, columns, where in unique_constraints:
        _create_unique_if_missing(inspector, bind, table_name, name, columns, where=where)
        inspector = sa.inspect(bind)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table_name, name in [
        ("audit_logs", "ix_audit_logs_entity"),
        ("shipment_scan_logs", "ix_shipment_scan_logs_shipment_package"),
        ("shipments", "ix_shipments_sales_status"),
        ("shipments", "ix_shipments_status_id"),
        ("package_scan_logs", "ix_package_scan_logs_package_scanned"),
        ("packages", "ix_packages_storage_status"),
        ("packages", "ix_packages_sales_status"),
        ("packages", "ix_packages_production_status"),
        ("packages", "ix_packages_status_id"),
        ("work_orders", "ix_work_orders_batch_operation"),
        ("work_orders", "ix_work_orders_production_status"),
        ("production_orders", "ix_production_orders_sales_status"),
        ("production_orders", "ix_production_orders_status_id"),
        ("stock_movements", "ix_stock_movements_reference"),
        ("stock_movements", "ix_stock_movements_item_created"),
        ("stock_batches", "ix_stock_batches_item_warehouse"),
        ("idempotency_records", "ix_idempotency_records_created_at"),
        ("idempotency_records", "ix_idempotency_records_scope"),
    ]:
        if table_name in inspector.get_table_names() and _has_index(inspector, table_name, name):
            op.drop_index(name, table_name=table_name)
            inspector = sa.inspect(bind)

    if bind.dialect.name != "sqlite":
        for table_name, name in [
            ("stock_reservations", "uq_stock_reservations_order_stock_package"),
            ("package_batch_allocations", "uq_package_batch_allocations_package_batch"),
            ("shipment_packages", "uq_shipment_packages_shipment_package"),
            ("work_orders", "uq_work_orders_order_batch_operation"),
            ("production_batches", "uq_production_batches_order_batch_no"),
        ]:
            if table_name in inspector.get_table_names() and _has_unique(inspector, table_name, name):
                op.drop_constraint(name, table_name, type_="unique")
                inspector = sa.inspect(bind)

    if "idempotency_records" in inspector.get_table_names():
        op.drop_table("idempotency_records")
