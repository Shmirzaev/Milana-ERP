"""Issue new Nastil serials from the order's authoritative public reference.

Existing stored serials and printed QR identities are never recomputed. Legacy
nonstandard references keep the previous PK-based creation fallback.
"""
import re

from app.schemas import ProductionOrder


def new_batch_number(order: ProductionOrder, batch_index: int) -> str:
    match = re.fullmatch(r"(?:PO|SO|USL)-(?:[0-9]{4}-)?([0-9]+)", str(order.order_no or "").strip())
    order_number = int(match.group(1)) if match else order.id
    return f"{order_number:04d}-{batch_index:02d}"
