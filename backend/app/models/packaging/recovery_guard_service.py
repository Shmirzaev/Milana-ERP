"""Narrow recovery restriction for evidence the legacy editor cannot maintain."""
from fastapi import HTTPException


RECOVERY_REFUSAL = "Exact-source packages require the attribution-aware release for edits or deletion"


def require_recovery_editable(package) -> None:
    """Keep legacy NULL packages unchanged; preserve every new exact source row."""
    if any(row.item_breakdown is not None for row in package.batch_allocations):
        raise HTTPException(409, RECOVERY_REFUSAL)
