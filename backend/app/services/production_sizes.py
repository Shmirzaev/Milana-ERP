"""Edit existing planned size labels without changing quantities or row identities."""
from fastapi import HTTPException
from sqlalchemy.orm import Session, lazyload

from app.models import Bundle, CuttingRecord, ProductionOrder, ProductionOrderItem, User, WorkOrder
from app.models.payroll import PayrollQrLabel
from app.schemas.production import ProductionOrderSizesIn
from app.services.audit import log_action

PRE_CUTTING_STATUSES = {"new", "planning", "pending", "waiting", "ready"}


def update_production_sizes(db: Session, pid: int, payload: ProductionOrderSizesIn, current: User) -> None:
    po = (db.query(ProductionOrder).options(lazyload("*"))
          .filter(ProductionOrder.id == pid).with_for_update().populate_existing().first())
    if po is None:
        raise HTTPException(404, "Production order not found")
    if po.source_type == "usluga" or po.status not in PRE_CUTTING_STATUSES:
        raise HTTPException(409, "production_sizes_locked")
    work_orders = (db.query(WorkOrder).options(lazyload("*"))
                   .filter(WorkOrder.production_order_id == pid).order_by(WorkOrder.id)
                   .with_for_update().populate_existing().all())
    if any(wo.operation == "cutting" and wo.status not in PRE_CUTTING_STATUSES for wo in work_orders):
        raise HTTPException(409, "production_sizes_locked")
    items = (db.query(ProductionOrderItem).filter(ProductionOrderItem.production_order_id == pid)
             .order_by(ProductionOrderItem.id).with_for_update().populate_existing().all())
    if (any(item.completed_quantity > 0 for item in items)
            or db.query(Bundle.id).filter(Bundle.production_order_id == pid).first()
            or db.query(CuttingRecord.id).join(WorkOrder, WorkOrder.id == CuttingRecord.work_order_id)
            .filter(WorkOrder.production_order_id == pid).first()
            or db.query(PayrollQrLabel.id).filter(PayrollQrLabel.production_order_id == pid).first()):
        raise HTTPException(409, "production_sizes_locked")
    submitted = {row.id: row for row in payload.items}
    if len(submitted) != len(payload.items) or set(submitted) != {item.id for item in items}:
        raise HTTPException(409, "production_sizes_stale")
    seen = set()
    changes = []
    for item in items:
        row = submitted[item.id]
        if row.original_size != item.size:
            raise HTTPException(409, "production_sizes_stale")
        size = row.size.strip()
        if not size:
            raise HTTPException(400, "production_sizes_required")
        key = (item.color.strip().casefold(), size.casefold())
        if key in seen:
            raise HTTPException(400, "production_sizes_duplicate")
        seen.add(key)
        changes.append((item, size))
    old = [{"id": item.id, "color": item.color, "size": item.size,
            "planned_quantity": item.planned_quantity} for item in items]
    if all(item.size == size for item, size in changes):
        return
    for item, size in changes:
        item.size = size
    log_action(db, current, "update_sizes", "ProductionOrder", po.id,
               old_value={"items": old},
               new_value={"items": [{**row, "size": size} for row, (_, size) in zip(old, changes)]})
