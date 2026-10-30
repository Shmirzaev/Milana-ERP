"""Schema-owned persistence for the stock batch receipt.

`receive_stock` in `app.models.inventory.stock_service` owns the business rules:
permissions, the item and warehouse lookups, cost rounding, roll normalisation,
the QC guard, idempotency, the audit call and the transaction. This module owns
only the mapped `stock_batches` and `stock_movements` construction and writes.

Rules this module follows:

* It never commits, never begins a transaction and never swallows an error. The
  calling service owns the one session and the one transaction.
* It flushes only where the caller needs a generated identifier. The receipt
  needs `stock_batches.id` before it can point the movement at the batch, so
  `add_stock_batch` flushes once; `add_receive_movement` leaves the insert to
  the caller's own flush, exactly as the receipt did before.
* Every mapped field is named explicitly. There is no mass assignment from a
  request payload, so a new request field cannot silently reach a column.
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.libs.enums.inventory import StockBatchQcStatus, StockMovementType
from app.schemas.inventory.inventory import StockBatch, StockMovement


def add_stock_batch(
    db: Session,
    *,
    item_id: int,
    batch_no: str,
    supplier_id: int | None,
    color: str | None,
    old_code: str | None,
    color_code: str | None,
    color_status: str | None,
    order_no: str | None,
    width: float | None,
    gsm: float | None,
    quantity: float,
    piece_count: int | None,
    roll_weights_kg: list[float],
    processes: str | None,
    unit: str,
    cost_per_unit: Decimal,
    image_url: str | None,
    warehouse_id: int,
    qc_status: StockBatchQcStatus,
    length_m: float | None = None,
    roll_lengths_m: list[float | None] | None = None,
    internal_batch_no: str | None = None,
) -> StockBatch:
    """Insert one received stock batch and return it with its generated id.

    `internal_batch_no` defaults to its historical Inventory receipt value;
    Purchase Order receiving supplies its existing PO number. `received_date`,
    `archived_at` and `archived_by` keep their column defaults. The QC member
    reaches the `String(32)` column as its plain stored value.
    """
    batch = StockBatch(
        item_id=item_id,
        batch_no=batch_no,
        internal_batch_no=internal_batch_no,
        supplier_id=supplier_id,
        color=color,
        old_code=old_code,
        color_code=color_code,
        color_status=color_status,
        order_no=order_no,
        width=width,
        gsm=gsm,
        quantity=quantity,
        piece_count=piece_count,
        roll_weights_kg=roll_weights_kg,
        processes=processes,
        unit=unit,
        cost_per_unit=cost_per_unit,
        image_url=image_url,
        warehouse_id=warehouse_id,
        qc_status=qc_status.value,
    )
    # Purchase-order receipt historically leaves these two values to their
    # mapped defaults. Inventory's HTTP receipt passes both explicitly.
    if length_m is not None:
        batch.length_m = length_m
    if roll_lengths_m is not None:
        batch.roll_lengths_m = roll_lengths_m
    db.add(batch)
    db.flush()
    return batch


def add_receive_movement(
    db: Session,
    *,
    item_id: int,
    batch_id: int,
    to_warehouse_id: int,
    quantity: float,
    unit: str,
    reference_type: str,
    reference_id: int,
    created_by: int | None,
) -> StockMovement:
    """Insert the ledger movement that records the batch entering a warehouse."""
    movement = StockMovement(
        movement_type=StockMovementType.RECEIVE.value,
        item_id=item_id,
        batch_id=batch_id,
        from_warehouse_id=None,
        to_warehouse_id=to_warehouse_id,
        quantity=quantity,
        unit=unit,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by=created_by,
    )
    db.add(movement)
    return movement
