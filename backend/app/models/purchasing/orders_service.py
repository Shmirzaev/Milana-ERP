"""Purchase order operations: the order directory, its page and its creation.

Contract for the purchase order operations:
* input: a validated `PurchaseOrderIn` and the acting user for the creation; a
  status filter, a page window and a receivable-only flag for the directory
* output: one page of purchase orders plus the exact filtered total, or the
  persisted `PurchaseOrder`
* refusals: the 400/404 messages the core operation raises, plus 403 when the
  caller may not reach one of the order's items
* records: purchase order rows and their lines, the audit rows and the
  department notification the core operation writes
* transaction owner: `create_purchase_order`; it commits once, after the
  caller's access to every line has been checked
"""
from sqlalchemy.orm import Session, joinedload

from app.libs.dto.purchasing.purchase_order_input import PurchaseOrderIn
from app.libs.dto.purchasing.purchase_order_output import PurchaseOrderOut
from app.models import inventory_access_service as inventory_access
from app.models import purchasing_service as purchasing_core
from app.schemas import Item, PurchaseOrder, PurchaseOrderLine, User

# Largest page the order directory will serve.
PURCHASE_ORDER_LIST_MAX_LIMIT = 200


def _purchase_orders_query(db: Session, user: User):
    """Base query for the order directory, shared by the page and its count.

    The count MUST be derived from this same query or `total` stops describing
    the list the UI is showing.
    """
    return db.query(PurchaseOrder).filter(
        ~PurchaseOrder.lines.any(PurchaseOrderLine.item_id.in_(
            db.query(Item.id).filter(Item.category.notin_(inventory_access.MATERIAL_CATEGORIES))
        )) if inventory_access.materials_only(user) else True
    )


def list_purchase_orders(
    db: Session,
    *,
    user: User,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    receivable_only: bool = False,
) -> dict:
    """One page of purchase orders plus the exact filtered total.

    `total` is the true count for the same filters, not the page length, so the
    receiving screen can page instead of silently showing a truncated list.
    Ordering is unchanged (`PurchaseOrder.id.desc()`).
    """
    query = _purchase_orders_query(db, user)
    term = str(status or "").strip()
    if term:
        query = query.filter(PurchaseOrder.status == term)
    if receivable_only:
        # Match the receiving queue without loading every order or counting
        # its outstanding lines more than once. The page and total share scope.
        query = query.filter(
            PurchaseOrder.status.in_(("sent", "approved", "partially_received")),
            PurchaseOrder.lines.any(PurchaseOrderLine.ordered_quantity > PurchaseOrderLine.received_quantity),
        )

    total = int(query.with_entities(PurchaseOrder.id).count())
    orders = (
        query.options(joinedload(PurchaseOrder.lines))
        .order_by(PurchaseOrder.id.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return {
        "items": [PurchaseOrderOut.model_validate(order) for order in orders],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def create_purchase_order(db: Session, *, payload: PurchaseOrderIn, current: User) -> PurchaseOrder:
    """Create a purchase order and commit it once its lines are authorized."""
    order = purchasing_core.create_purchase_order(db, data=payload.model_dump(), current=current)
    purchasing_core.require_purchase_item_access(db, current, order.lines)
    db.commit()
    db.refresh(order)
    return order
