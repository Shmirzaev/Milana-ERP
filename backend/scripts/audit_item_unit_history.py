"""Report historical quantity rows whose unit label differs from its catalog item.

This preflight is read-only. It compares stored unit labels exactly and never
infers conversions or updates rows.
"""
from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, literal, or_, select
from sqlalchemy.engine import Connection, Engine, create_engine
from sqlalchemy.orm import aliased

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import (
    CuttingBeikaMaterialUsage,
    CuttingMaterialUsage,
    EcoFabricRoll,
    ForecastRecommendation,
    Item,
    ManualAccessoryIssue,
    ModelBOM,
    MaterialReservation,
    PurchaseOrderLine,
    PurchaseRequestLine,
    ProductionOrderMaterial,
    StockBatch,
    StockMovement,
    WasteRecord,
)


_SOURCES = (
    ("stock_batches", StockBatch, "item_id", None),
    ("material_reservations", MaterialReservation, "item_id", "stock_batch_id"),
    ("purchase_request_lines", PurchaseRequestLine, "item_id", None),
    ("purchase_order_lines", PurchaseOrderLine, "item_id", None),
    ("stock_movements", StockMovement, "item_id", "batch_id"),
    ("forecast_recommendations", ForecastRecommendation, "item_id", None),
    ("waste_records", WasteRecord, "item_id", "batch_id"),
    ("model_bom", ModelBOM, "item_id", "stock_batch_id"),
    ("production_order_materials", ProductionOrderMaterial, None, "stock_batch_id"),
    ("cutting_material_usages", CuttingMaterialUsage, None, "stock_batch_id"),
    ("cutting_beika_material_usages", CuttingBeikaMaterialUsage, None, "stock_batch_id"),
    ("manual_accessory_issues", ManualAccessoryIssue, "item_id", None),
    ("eco_fabric_rolls", EcoFabricRoll, None, "batch_id"),
)

_REQUIRED_COLUMNS = {
    "items": {"id", "unit"},
    "stock_batches": {"id", "item_id", "unit"},
}
for table_name, _model, item_column, batch_column in _SOURCES:
    required = {"id", "unit"}
    if item_column:
        required.add(item_column)
    if batch_column:
        required.add(batch_column)
    _REQUIRED_COLUMNS[table_name] = required


def _validate_schema(connection: Connection) -> None:
    inspector = inspect(connection)
    for table_name, required in _REQUIRED_COLUMNS.items():
        if not inspector.has_table(table_name):
            raise RuntimeError(f"Required table is missing: {table_name}")
        found = {column["name"] for column in inspector.get_columns(table_name)}
        missing = sorted(required - found)
        if missing:
            raise RuntimeError(f"Required columns are missing from {table_name}: {', '.join(missing)}")


@contextmanager
def _read_only_transaction(connection: Connection) -> Iterator[None]:
    """Set a server-side read-only transaction for supported ERP databases."""
    dialect = connection.dialect.name
    previous_query_only = None
    if dialect == "postgresql":
        connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
    elif dialect == "sqlite":
        # query_only is connection-scoped and rejects accidental DML/DDL during this run.
        previous_query_only = int(connection.exec_driver_sql("PRAGMA query_only").scalar_one())
        if not previous_query_only:
            connection.exec_driver_sql("PRAGMA query_only = ON")
    else:
        raise RuntimeError(f"Unsupported database dialect for read-only preflight: {dialect}")
    try:
        yield
    finally:
        if dialect == "sqlite" and not previous_query_only:
            # Preserve the pooled connection's original read-only mode.
            connection.exec_driver_sql("PRAGMA query_only = OFF")


def audit_item_unit_history(connection: Connection) -> dict[str, Any]:
    """Return exact mismatch IDs and counts without selecting business notes or names."""
    with _read_only_transaction(connection):
        _validate_schema(connection)
        tables: dict[str, Any] = {}
        for table_name, model, item_column, batch_column in _SOURCES:
            direct_item = aliased(Item, name=f"{table_name}_direct_item")
            batch = aliased(StockBatch, name=f"{table_name}_batch")
            batch_item = aliased(Item, name=f"{table_name}_batch_item")
            direct_id = getattr(model, item_column) if item_column else literal(None)
            batch_id = getattr(model, batch_column) if batch_column else literal(None)
            direct_record_id = direct_item.id if item_column else literal(None)
            direct_unit = direct_item.unit if item_column else literal(None)
            batch_record_id = batch.id if batch_column else literal(None)
            batch_item_id = batch.item_id if batch_column else literal(None)
            batch_item_record_id = batch_item.id if batch_column else literal(None)
            batch_item_unit = batch_item.unit if batch_column else literal(None)
            statement = select(
                model.id.label("row_id"),
                model.unit.label("row_unit"),
                direct_id.label("direct_item_id"),
                direct_record_id.label("direct_item_record_id"),
                direct_unit.label("direct_item_unit"),
                batch_id.label("batch_id"),
                batch_record_id.label("batch_record_id"),
                batch_item_id.label("batch_item_id"),
                batch_item_record_id.label("batch_item_record_id"),
                batch_item_unit.label("batch_item_unit"),
            ).select_from(model)
            if item_column:
                statement = statement.outerjoin(direct_item, direct_item.id == direct_id)
            if batch_column:
                statement = statement.outerjoin(batch, batch.id == batch_id).outerjoin(
                    batch_item, batch_item.id == batch.item_id,
                )
            linked_references = []
            if item_column:
                linked_references.append(direct_id.is_not(None))
            if batch_column:
                linked_references.append(batch_id.is_not(None))
            statement = (
                statement.where(or_(*linked_references))
                .order_by(model.id)
                .execution_options(stream_results=True)
            )
            scanned_count = 0
            equal_count = 0
            missing_unit_count = 0
            unresolved_item_count = 0
            mismatches: list[dict[str, Any]] = []
            unresolved_items: list[dict[str, Any]] = []
            for row in connection.execute(statement).mappings():
                scanned_count += 1
                direct_item_id = row["direct_item_id"]
                linked_batch_id = row["batch_id"]
                if direct_item_id is not None and row["direct_item_record_id"] is None:
                    unresolved_item_count += 1
                    unresolved_items.append({
                        "row_id": row["row_id"], "item_id": direct_item_id,
                        "batch_id": linked_batch_id, "reason": "item not found",
                    })
                    continue
                if linked_batch_id is not None:
                    if row["batch_record_id"] is None:
                        unresolved_item_count += 1
                        unresolved_items.append({
                            "row_id": row["row_id"], "item_id": direct_item_id,
                            "batch_id": linked_batch_id, "reason": "batch not found",
                        })
                        continue
                    if row["batch_item_record_id"] is None:
                        unresolved_item_count += 1
                        unresolved_items.append({
                            "row_id": row["row_id"], "item_id": direct_item_id,
                            "batch_id": linked_batch_id,
                            "reason": "batch item not found",
                        })
                        continue
                    if direct_item_id is not None and direct_item_id != row["batch_item_id"]:
                        unresolved_item_count += 1
                        unresolved_items.append({
                            "row_id": row["row_id"], "item_id": direct_item_id,
                            "batch_id": linked_batch_id,
                            "reason": "item does not match batch item",
                        })
                        continue

                item_id = direct_item_id or row["batch_item_id"]
                item_unit = (
                    row["direct_item_unit"]
                    if direct_item_id is not None
                    else row["batch_item_unit"]
                )
                if item_id is None:
                    unresolved_item_count += 1
                    unresolved_items.append({
                        "row_id": row["row_id"], "item_id": None,
                        "batch_id": linked_batch_id, "reason": "item reference missing",
                    })
                    continue
                row_unit = row["row_unit"]
                if row_unit is None or item_unit is None or not str(row_unit).strip() or not str(item_unit).strip():
                    missing_unit_count += 1
                    continue
                if row_unit == item_unit:
                    equal_count += 1
                    continue
                mismatches.append(
                    {
                        "row_id": row["row_id"],
                        "item_id": item_id,
                        "row_unit": row_unit,
                        "item_unit": item_unit,
                    }
                )
            tables[table_name] = {
                "scanned_count": scanned_count,
                "equal_count": equal_count,
                "missing_unit_count": missing_unit_count,
                "unresolved_item_count": unresolved_item_count,
                "mismatch_count": len(mismatches),
                "mismatches": mismatches,
                "unresolved_items": unresolved_items,
            }
        return {"comparison": "exact unit-label equality", "tables": tables}


def main() -> int:
    database_url = os.environ.get("ITEM_UNIT_AUDIT_DATABASE_URL")
    if not database_url:
        raise SystemExit("Set ITEM_UNIT_AUDIT_DATABASE_URL to the explicitly selected database URL.")
    engine: Engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            report = audit_item_unit_history(connection)
    finally:
        engine.dispose()
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
