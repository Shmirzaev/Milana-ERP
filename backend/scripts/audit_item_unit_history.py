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

from sqlalchemy import inspect, select
from sqlalchemy.engine import Connection, Engine, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import (
    ForecastRecommendation,
    Item,
    MaterialReservation,
    PurchaseOrderLine,
    PurchaseRequestLine,
    StockBatch,
    StockMovement,
)


_SOURCES = (
    ("stock_batches", StockBatch),
    ("material_reservations", MaterialReservation),
    ("purchase_request_lines", PurchaseRequestLine),
    ("purchase_order_lines", PurchaseOrderLine),
    ("stock_movements", StockMovement),
    ("forecast_recommendations", ForecastRecommendation),
)

_REQUIRED_COLUMNS = {
    "items": {"id", "unit"},
    **{
        table_name: {"id", "item_id", "unit"}
        for table_name, _model in _SOURCES
    },
}


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
        for table_name, model in _SOURCES:
            statement = (
                select(
                    model.id.label("row_id"),
                    model.item_id.label("item_id"),
                    model.unit.label("row_unit"),
                    Item.id.label("item_record_id"),
                    Item.unit.label("item_unit"),
                )
                .outerjoin(Item, Item.id == model.item_id)
                .where(model.item_id.is_not(None))
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
                row_unit = row["row_unit"]
                item_unit = row["item_unit"]
                if row["item_record_id"] is None:
                    unresolved_item_count += 1
                    unresolved_items.append({"row_id": row["row_id"], "item_id": row["item_id"]})
                    continue
                if row_unit is None or item_unit is None or not str(row_unit).strip() or not str(item_unit).strip():
                    missing_unit_count += 1
                    continue
                if row_unit == item_unit:
                    equal_count += 1
                    continue
                mismatches.append(
                    {
                        "row_id": row["row_id"],
                        "item_id": row["item_id"],
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
