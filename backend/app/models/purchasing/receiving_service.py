"""Purchase order receiving: the receipt itself and its stock effects.

Contract for the receive operation:
* input: a purchase order id, a validated `PurchaseOrderReceiveIn`, the acting
  user and the optional `Idempotency-Key`
* output: the received purchase order as a serialized payload, or the stored
  response of an earlier receipt with the same key
* refusals: 404 "Purchase order not found", 409 for an order that is not
  receivable, the 400/404 messages the core operation raises, plus 403 when
  the caller may not reach one of the order's items
* records: the receipt's stock batches and movements, the order line updates,
  the audit rows and the idempotency record
* lock order: the purchase order row under FOR UPDATE, taken before the replay
  read; the core operation takes the same lock again for the receipt itself
* transaction owner: `receive_purchase_order`; the receipt, its stock, its
  audit trail and the replay record are written by one commit
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session, lazyload, selectinload

from app.libs.dto.purchasing.purchase_order_input import PurchaseOrderReceiveIn
from app.libs.dto.purchasing.purchase_order_output import PurchaseOrderOut
from app.models import purchasing_service as purchasing_core
from app.models.factory_scope_service import selected_factory_code
from app.models.idempotency_service import replay_idempotent_response, store_idempotent_response
from app.schemas import PurchaseOrder, User


def receive_purchase_order(
    db: Session,
    *,
    order_id: int,
    payload: PurchaseOrderReceiveIn,
    current: User,
    idempotency_key: str | None = None,
) -> dict:
    """Receive a purchase order and write its stock in one commit.

    The caller's access to the order's items is checked before the replay
    lookup, so a stored response can never be handed to a caller who may no
    longer reach those items.
    """
    # Lock and refresh the order before any replay check. Serializing here is
    # what makes a retry observe the first receipt's replay record instead of
    # racing past it and creating a second stock batch for the same receipt.
    # Eager joins are disabled so PostgreSQL locks only the purchase order row.
    order_query = (
        db.query(PurchaseOrder)
        .options(lazyload("*"), selectinload(PurchaseOrder.lines))
        .filter(PurchaseOrder.id == order_id)
        .populate_existing()
    )
    if db.bind and db.bind.dialect.name == "postgresql":
        order_query = order_query.with_for_update(of=PurchaseOrder)
    locked_order = order_query.one_or_none()
    if not locked_order:
        raise HTTPException(404, "Purchase order not found")

    # Authorize before replay: a stored response must not bypass the caller's
    # current inventory access to the order's items.
    purchasing_core.require_purchase_item_access(db, current, locked_order.lines)

    # Replay is scoped to factory, caller and order, so a key cannot be
    # borrowed across any of them.
    scope = f"purchasing.receive:{selected_factory_code(current)}:{current.id}:{order_id}"
    fingerprint_payload = payload.model_dump(mode="json")
    # The empty spelling historically stored "passed" but was fingerprinted
    # as "". Preserve it so already-committed retries remain replayable.
    for line, fingerprint_line in zip(payload.lines, fingerprint_payload["lines"]):
        if line.raw_qc_status is not None:
            fingerprint_line["qc_status"] = line.raw_qc_status
    replay = replay_idempotent_response(
        db, scope=scope, key=idempotency_key, payload=fingerprint_payload,
    )
    if replay is not None:
        return replay

    order = purchasing_core.receive_purchase_order(
        db, order_id=order_id, data=payload.model_dump(), current=current
    )
    # No second authorization pass here. The loop above already checked every
    # line of this order against the caller's current inventory access, and
    # receive_purchase_order only updates received quantity, cost and
    # warehouse on existing lines: it neither adds a line nor changes item_id,
    # so re-reading the same references could not reach a different verdict.
    # Flush so the database evaluates updated_at (onupdate=func.now()), then
    # read it back. Without this the response, and the replay record stored
    # from it, would carry the pre-receipt timestamp. Refreshing only this
    # column keeps the loaded lines and preserves the single commit below.
    db.flush()
    db.refresh(order, ["updated_at"])
    # The receipt, its stock, its audit trail and the replay record are written
    # by one commit; a failure here must leave no stock and no replay row.
    response = PurchaseOrderOut.model_validate(order).model_dump(mode="json")
    store_idempotent_response(
        db, scope=scope, key=idempotency_key, payload=fingerprint_payload,
        response=response, user=current, status_code=200,
    )
    db.commit()
    return response
