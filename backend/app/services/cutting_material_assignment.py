from fastapi import HTTPException
from sqlalchemy import or_

from app.models import (
    CuttingMaterialUsage, CuttingRecord, Item, MaterialReservation,
    ProductionOrder, ProductionOrderMaterial, StockBatch, WorkOrder,
)
from app.models.cutting_passport import CuttingPassport
from app.services.audit import log_action
from app.services.factory_scope import require_work_order_factory_access
from app.services.inventory import create_material_reservations, release_material_reservation


def replace_cutting_material_batch(db, current, work_order_id, old_batch_id, new_batch_id):
    wo = db.get(WorkOrder, work_order_id)
    if not wo:
        raise HTTPException(404, "Work order not found")
    require_work_order_factory_access(current, db, wo)
    if wo.operation != "cutting":
        raise HTTPException(400, "Work order is not a cutting operation")
    # Serialize with Cutting submission and passport material additions.
    order = db.query(ProductionOrder).filter_by(id=wo.production_order_id).with_for_update(of=ProductionOrder).one()
    db.refresh(wo, with_for_update=True)
    if order.source_type == "usluga":
        raise HTTPException(400, "Customer-supplied fabrics cannot use warehouse batches")
    if order.status in {"completed", "cancelled", "rejected"} or wo.status in {"completed", "cancelled", "rejected"}:
        raise HTTPException(409, "Materials can only be changed while Cutting is open")
    materials = db.query(ProductionOrderMaterial).filter_by(production_order_id=order.id).order_by(ProductionOrderMaterial.position).all()
    material = next((row for row in materials if row.stock_batch_id == old_batch_id), None)
    if not material:
        raise HTTPException(409, "The assigned material changed. Reload Cutting before saving")
    if old_batch_id == new_batch_id:
        return {"stock_batch_id": new_batch_id}
    if any(row.stock_batch_id == new_batch_id for row in materials):
        raise HTTPException(409, "This batch is already assigned to another material row")
    used = db.query(CuttingRecord.id).outerjoin(CuttingMaterialUsage, CuttingMaterialUsage.cutting_record_id == CuttingRecord.id).join(
        WorkOrder, WorkOrder.id == CuttingRecord.work_order_id,
    ).filter(WorkOrder.production_order_id == order.id, or_(
        CuttingMaterialUsage.stock_batch_id == old_batch_id,
        CuttingRecord.fabric_batch_id == old_batch_id,
    )).first()
    if used:
        raise HTTPException(409, "This material has already been used in Cutting; its recorded batch cannot be replaced")
    batches = db.query(StockBatch).filter(StockBatch.id.in_([old_batch_id, new_batch_id])).order_by(StockBatch.id).with_for_update(of=StockBatch).all()
    batch = next((row for row in batches if row.id == new_batch_id), None)
    item = db.get(Item, batch.item_id) if batch else None
    if not batch or not item or item.category not in {"fabric", "semi_finished"}:
        raise HTTPException(400, "Select a fabric inventory batch")
    if batch.archived_at is not None or float(batch.quantity or 0) <= 0:
        raise HTTPException(409, "This fabric batch is archived or empty")
    if batch.unit != material.unit:
        raise HTTPException(400, "The replacement batch must use the same unit as the planned material")
    reservations = db.query(MaterialReservation).filter(
        MaterialReservation.production_order_id == order.id,
        MaterialReservation.stock_batch_id.in_([old_batch_id, new_batch_id]),
    ).with_for_update(of=MaterialReservation).all()
    old_reservations = [row for row in reservations if row.stock_batch_id == old_batch_id]
    if any(float(row.consumed_quantity or 0) > 0 for row in old_reservations):
        raise HTTPException(409, "This material reservation has already been consumed; its batch cannot be replaced")

    def remaining(row):
        return max(0, float(row.reserved_quantity) - float(row.consumed_quantity or 0) - float(row.released_quantity or 0)) if row.status in {"reserved", "partially_consumed"} else 0

    required = max(float(material.estimated_quantity), sum(remaining(row) for row in old_reservations))
    missing = required - sum(remaining(row) for row in reservations if row.stock_batch_id == new_batch_id)
    if missing > 0.0001:
        create_material_reservations(db, production_order_id=order.id, lines=[{
            "item_id": batch.item_id, "stock_batch_id": batch.id, "warehouse_id": batch.warehouse_id,
            "reserved_quantity": missing, "unit": batch.unit,
            "notes": "Material batch corrected in Cutting",
        }], user_id=current.id)
    for reservation in old_reservations:
        if remaining(reservation) > 0:
            release_material_reservation(db, reservation.id)
    material.stock_batch_id = batch.id
    primary = materials[0] is material
    if primary:
        order.fabric_batch_id = batch.id
        order.estimated_material_code = item.sku
        order.estimated_material_amount = material.estimated_quantity
        order.estimated_material_unit = material.unit
    passports = db.query(CuttingPassport).filter_by(production_order_id=order.id).with_for_update(of=CuttingPassport).all()
    for passport in passports:
        rows = passport.materials or []
        changed = any(row.get("stock_batch_id") == old_batch_id for row in rows)
        identity = {"stock_batch_id": batch.id, "fabric_type": item.name, "lot_no": batch.batch_no or batch.internal_batch_no}
        if changed:
            passport.materials = [{**row, **identity} if row.get("stock_batch_id") == old_batch_id else row for row in rows]
        if (rows and rows[0].get("stock_batch_id") == old_batch_id) or (not rows and primary):
            passport.fabric_type = identity["fabric_type"]
            passport.lot_no = identity["lot_no"]
        if changed or (not rows and primary):
            log_action(db, current, "correct_material_batch", "CuttingPassport", passport.id,
                       old_value={"stock_batch_id": old_batch_id}, new_value=identity)
    log_action(db, current, "correct_cutting_material_batch", "ProductionOrder", order.id,
               old_value={"stock_batch_id": old_batch_id},
               new_value={"stock_batch_id": batch.id, "estimated_quantity": float(material.estimated_quantity), "unit": material.unit})
    db.flush()
    return {"stock_batch_id": batch.id}
