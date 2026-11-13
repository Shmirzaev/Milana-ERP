"""Zero-balance material identities; physical stock remains exclusively in ECO."""
from decimal import Decimal

from sqlalchemy.orm import Session

from app.libs.enums.inventory import StockBatchQcStatus
from app.schemas import StockBatch
from app.schemas.inventory.eco_inventory import EcoMaterialBatch


def insert_direct_fabric_identity(db: Session, receipt: EcoMaterialBatch, *, warehouse_id: int) -> StockBatch:
    details = receipt.receipt_details or {}
    row = StockBatch(item_id=receipt.item_id, batch_no=receipt.batch_no,
        internal_batch_no=f"ECO-DIRECT-{receipt.id}", color=receipt.color, unit=receipt.unit,
        quantity=Decimal(0), cost_per_unit=Decimal(0), warehouse_id=warehouse_id,
        qc_status=StockBatchQcStatus.PASSED.value, width=details.get("width"), gsm=details.get("gsm"),
        image_url=details.get("image_url"), roll_weights_kg=[], roll_lengths_m=[])
    db.add(row)
    db.flush()
    receipt.source_stock_batch_id = row.id
    return row
