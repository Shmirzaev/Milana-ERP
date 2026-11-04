"""Read-only schema gate for the exact 3 November runtime's ECO rollback image.

This image contains the additive migration graph but no ECO application paths.
Only the verified, untouched predecessor may start before those migrations run.
"""
from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy import text
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.libs.enums.production import SewingFactoryCode

PREDECESSOR = "0150_package_customer_release"
SUCCESSOR = "0154_eco_receipt_details"
ECO_COLUMNS = {
    "eco_material_batches": {
        "id", "item_id", "kind", "batch_no", "color", "unit", "quantity", "reserved_quantity",
        "source_stock_batch_id", "received_at", "created_by", "receipt_details",
    },
    "eco_material_movements": {
        "id", "batch_id", "kind", "quantity", "production_order_id", "reference_type", "reference_id",
        "notes", "created_at", "created_by",
    },
    "factory_fabric_transfers": {"id", "status", "notes", "dispatched_at", "dispatched_by"},
    "factory_fabric_transfer_lines": {
        "id", "transfer_id", "source_batch_id", "item_id", "item_name", "batch_no", "color", "unit",
        "quantity", "received_quantity", "receipt_details",
    },
    "eco_accessory_plans": {
        "id", "created_at", "updated_at", "production_order_id", "model_id", "planning_order_id",
        "planned_quantity", "status", "revision", "notes", "approval_notes", "approved_by", "approved_at", "created_by",
    },
    "eco_accessory_requirements": {"id", "plan_id", "item_id", "quantity", "unit"},
    "eco_accessory_allocations": {"id", "requirement_id", "batch_id", "quantity", "issued_quantity"},
}


def accepts_eco_rollback_predecessor(
    connection: Connection, current_heads: set[str], expected_heads: set[str],
) -> bool:
    """Accept only the known empty predecessor; validate the complete successor.

    Unknown heads remain subject to the existing strict equality failure. Never
    stamp, create tables, migrate, downgrade or change business data at startup.
    """
    if expected_heads != {SUCCESSOR} or current_heads not in ({PREDECESSOR}, {SUCCESSOR}):
        return False
    inspector = inspect(connection)
    present = set(inspector.get_table_names()).intersection(ECO_COLUMNS)
    if current_heads == {PREDECESSOR}:
        if present:
            raise RuntimeError("ECO rollback predecessor has partial/unversioned ECO tables; reconcile migrations before startup")
        return True
    if present != set(ECO_COLUMNS):
        raise RuntimeError("ECO rollback successor schema is incomplete; reconcile migrations before startup")
    for table, required_columns in ECO_COLUMNS.items():
        columns = {column["name"] for column in inspector.get_columns(table)}
        if not required_columns.issubset(columns):
            raise RuntimeError(f"ECO rollback successor table {table} is incomplete; reconcile migrations before startup")
    return False


def eco_item_has_evidence(db: Session, item_id: int) -> bool:
    """Read additive ECO links without registering new runtime ORM mappings."""
    if not inspect(db.connection()).has_table("eco_material_batches"):
        return False
    return bool(db.execute(text("""
        SELECT EXISTS (SELECT 1 FROM eco_material_batches WHERE item_id = :item_id)
            OR EXISTS (SELECT 1 FROM eco_accessory_requirements WHERE item_id = :item_id)
    """), {"item_id": item_id}).scalar())


def _known_sewing_factory(value: str | None, *, bundle_default: bool = False) -> SewingFactoryCode:
    # Reuse the historical alias map, but not its unknown -> MIL fallback.
    # Lazy import preserves the old startup/import graph and creates no writes.
    from app.models.bundles_service import SEWING_FACTORY_ALIASES
    normalized = str(value or "").strip().upper()
    if normalized == "SEW" or (not normalized and bundle_default):
        return SewingFactoryCode.MILANA
    factory = SEWING_FACTORY_ALIASES.get(normalized)
    if factory is None:
        raise HTTPException(400, "Cannot resolve persisted sewing factory on compatibility rollback")
    return SewingFactoryCode(factory)


def freeze_eco_sewing_on_rollback(
    db: Session, order_id: int, *, sewing_factory_code: str | None = None,
    sewing_work_order_id: int | None = None, sewing_assignment_id: int | None = None,
) -> None:
    """The old application cannot enforce the new ledger: freeze ECO handoffs.

    An explicit persisted destination preserves MIL/BST work in a mixed order.
    This check stays dynamic so an already-running predecessor notices upgrade.
    """
    if not inspect(db.connection()).has_table("eco_accessory_plans"):
        return
    if sewing_assignment_id is not None:
        if sewing_work_order_id is None:
            raise HTTPException(400, "Selected sewing assignment requires its validated work order")
        assignment_factory = db.execute(text("""
            SELECT f.factory_code FROM sewing_assignments AS a
            JOIN sewing_flows AS f ON f.id = a.sewing_flow_id
            JOIN work_orders AS w ON w.id = a.work_order_id
            WHERE a.id = :assignment_id AND w.id = :work_id
                AND w.production_order_id = :order_id AND w.operation = 'sewing'
                AND a.status IN ('planned', 'in_progress', 'completed')
        """), {"assignment_id": sewing_assignment_id, "work_id": sewing_work_order_id,
                "order_id": order_id}).scalar_one_or_none()
        if assignment_factory is None:
            raise HTTPException(400, "Selected sewing assignment does not belong to this work order")
        # Actual assigned line is authoritative when historical/shared work
        # remains on SEW/MIL while its recorded assignment belongs to ECO.
        factories = {_known_sewing_factory(assignment_factory)}
    elif sewing_factory_code is not None and sewing_work_order_id is None:
        factories = {_known_sewing_factory(sewing_factory_code)}
    else:
        # Active splits describe the actual destinations. A direct line is
        # authoritative only while no active split exists; the historical
        # department is the last fallback. One read handles both a particular
        # work order and the conservative generic-order gate without N+1 reads.
        rows = db.execute(text("""
            WITH scoped_work AS (
                SELECT w.id, w.sewing_flow_id, d.code AS department_code,
                       f.factory_code AS direct_factory
                FROM work_orders AS w
                LEFT JOIN departments AS d ON d.id = w.department_id
                LEFT JOIN sewing_flows AS f ON f.id = w.sewing_flow_id
                WHERE w.production_order_id = :order_id AND w.operation = 'sewing'
                  AND w.status NOT IN ('cancelled', 'rejected')
                  AND (:work_id IS NULL OR w.id = :work_id)
            ), active_splits AS (
                SELECT a.work_order_id, f.factory_code
                FROM sewing_assignments AS a
                JOIN scoped_work AS w ON w.id = a.work_order_id
                LEFT JOIN sewing_flows AS f ON f.id = a.sewing_flow_id
                WHERE a.status IN ('planned', 'in_progress', 'completed')
            )
            SELECT factory_code, 0 AS bundle_default FROM active_splits
            UNION ALL
            SELECT CASE WHEN w.sewing_flow_id IS NOT NULL THEN w.direct_factory
                        ELSE w.department_code END, 0
            FROM scoped_work AS w
            WHERE NOT EXISTS (SELECT 1 FROM active_splits AS a WHERE a.work_order_id = w.id)
            UNION ALL
            SELECT b.sewing_factory_code, 1 FROM bundles AS b
            WHERE :work_id IS NULL AND b.production_order_id = :order_id AND b.status != 'cancelled'
            UNION ALL
            SELECT :eco, 0 FROM eco_accessory_plans
            WHERE :work_id IS NULL AND production_order_id = :order_id
        """), {"order_id": order_id, "work_id": sewing_work_order_id,
                "eco": SewingFactoryCode.ECO_COTTON.value}).all()
        if sewing_work_order_id is not None and not rows:
            raise HTTPException(400, "Selected sewing work order does not belong to this active order")
        factories = {_known_sewing_factory(code, bundle_default=bool(bundle_default)) for code, bundle_default in rows}
    if SewingFactoryCode.ECO_COTTON in factories:
        raise HTTPException(409, "ECO sewing is paused on the compatibility rollback. Restore the ECO inventory release before handing off or recording sewing.")
