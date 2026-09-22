"""Shared validation for values persisted on stock batches."""

from fastapi import HTTPException


STOCK_BATCH_QC_STATUSES = frozenset({"pending", "passed", "failed", "rejected", "hold"})


def normalize_stock_batch_qc_status(value: str | None) -> str:
    status = str(value or "").strip().lower()
    if status not in STOCK_BATCH_QC_STATUSES:
        raise HTTPException(400, "Invalid QC status")
    return status
