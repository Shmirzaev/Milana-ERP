"""Stock batch persistence for purchase-order receipts."""
from decimal import Decimal

from sqlalchemy.orm import Session

from app.schemas.inventory.inventory import StockBatch


def add_purchase_receipt_batch(
    db: Session, *, item_id: int, batch_no: str, internal_batch_no: str,
    supplier_id: int | None, color: str | None, old_code: str | None,
    color_code: str | None, color_status: str | None, order_no: str | None,
    width: float | None, gsm: float | None, quantity: float,
    piece_count: int | None, roll_weights_kg: list[float], processes: str | None,
    unit: str, cost_per_unit: Decimal, image_url: str | None,
    warehouse_id: int | None, qc_status: str,
) -> StockBatch:
    """Add the decided batch and flush for its movement and audit references."""
    batch = StockBatch(
        item_id=item_id, batch_no=batch_no, internal_batch_no=internal_batch_no,
        supplier_id=supplier_id, color=color, old_code=old_code,
        color_code=color_code, color_status=color_status, order_no=order_no,
        width=width, gsm=gsm, quantity=quantity, piece_count=piece_count,
        roll_weights_kg=roll_weights_kg, processes=processes, unit=unit,
        cost_per_unit=cost_per_unit, image_url=image_url,
        warehouse_id=warehouse_id, qc_status=qc_status,
    )
    db.add(batch)
    db.flush()
    return batch
