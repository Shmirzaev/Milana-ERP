"""Shared validation for values persisted on stock batches."""

from fastapi import HTTPException

from app.models import Item, Warehouse


STOCK_BATCH_QC_STATUSES = frozenset({"pending", "passed", "failed", "rejected", "hold"})
STOCK_BATCH_WAREHOUSE_TYPES = {
    "fabric": ("fabric_storage", "Fabric Storage"),
    "semi_finished": ("fabric_storage", "Fabric Storage"),
    "accessory": ("accessory_storage", "Accessory Storage"),
    "packaging": ("accessory_storage", "Accessory Storage"),
}


def normalize_stock_batch_qc_status(value: str | None) -> str:
    status = str(value or "").strip().lower()
    if status not in STOCK_BATCH_QC_STATUSES:
        raise HTTPException(400, "Invalid QC status")
    return status


def validate_stock_batch_warehouse(item: Item, warehouse: Warehouse) -> None:
    """Require category-specific storage for every stock-batch receipt writer."""
    expected = STOCK_BATCH_WAREHOUSE_TYPES.get(str(item.category or "").strip().lower())
    if expected is None:
        return
    expected_type, expected_name = expected
    if str(warehouse.type or "").strip().lower() != expected_type:
        raise HTTPException(400, f"{item.name} must be received into {expected_name}")
