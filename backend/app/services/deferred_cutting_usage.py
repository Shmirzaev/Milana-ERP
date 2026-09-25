"""Record actual fabric usage after issuing a cutting sheet, exactly once."""

import math

from fastapi import HTTPException

from app.models import CuttingMaterialUsage, ProductionOrder, ProductionOrderMaterial, WorkOrder
from app.schemas.cutting_material import CuttingMaterialDetails
from app.services.inventory import (
    consume_material_reservations_for_stock_batch,
    require_material_reservation_before_cutting,
)
from app.services.workflow import consume_stock_batch, create_waste_record


def pending_materials(db, record):
    # No usage row represents unknown consumption, never a fabricated stock debit.
    if record.materials or record.input_quantity or record.cutting_passport_id or not record.fabric_batch_id:
        return []
    work = db.get(WorkOrder, record.work_order_id)
    order = db.get(ProductionOrder, work.production_order_id) if work else None
    if not order or order.source_type == "usluga":
        return []
    return db.query(ProductionOrderMaterial).filter_by(production_order_id=order.id).order_by(
        ProductionOrderMaterial.position.asc(),
    ).all()


def save_material_usage(db, record, work, materials, user_id):
    # Caller holds the cutting-record lock; a second save cannot debit twice.
    planned = pending_materials(db, record)
    if not planned:
        raise HTTPException(409, "Actual fabric usage has already been recorded or is not pending")
    order = db.get(ProductionOrder, work.production_order_id)
    if work.status in {"cancelled", "rejected"} or order.status in {"cancelled", "rejected"}:
        raise HTTPException(409, "Cannot record fabric usage for cancelled or rejected cutting")
    by_batch = {row.stock_batch_id: row for row in materials}
    if len(by_batch) != len(materials) or set(by_batch) != {row.stock_batch_id for row in planned}:
        raise HTTPException(400, "Enter the actual amount used for every planned fabric")
    for row in planned:
        material = by_batch[row.stock_batch_id]
        if not math.isfinite(material.quantity) or material.quantity <= 0:
            raise HTTPException(400, "Actual fabric consumption must be positive and finite")
        if material.unit.strip().lower() != row.unit.strip().lower():
            raise HTTPException(400, "Cutting material unit must match the planned material unit")

    # All debits and usage rows share the request transaction: any shortage rolls
    # back the entire save, including reservations and waste records.
    for position, row in enumerate(planned, start=1):
        material = by_batch[row.stock_batch_id]
        details = (material.details or CuttingMaterialDetails()).model_dump()
        reserved = consume_material_reservations_for_stock_batch(
            db, production_order_id=work.production_order_id,
            stock_batch_id=row.stock_batch_id, quantity=material.quantity,
            reference_type="CuttingRecord", reference_id=record.id, user_id=user_id,
            require_full=require_material_reservation_before_cutting(db),
        )
        direct = material.quantity - reserved
        if direct > 1e-9:
            consume_stock_batch(
                db, batch_id=row.stock_batch_id, quantity=direct, unit=row.unit,
                reference_type="CuttingRecord", reference_id=record.id, user_id=user_id,
            )
        record.materials.append(CuttingMaterialUsage(
            stock_batch_id=row.stock_batch_id, quantity=material.quantity,
            unit=row.unit, position=position, details=details,
        ))
        create_waste_record(
            db, production_order_id=work.production_order_id, work_order_id=work.id,
            source_department_id=work.department_id, item_id=None, batch_id=row.stock_batch_id,
            waste_type="cutting_waste", quantity=details["waste_quantity"], unit=details["waste_unit"],
            reason="Actual fabric usage entered after cutting sheet", created_by=user_id,
        )
        if position == 1:
            record.fabric_batch_id = row.stock_batch_id
            record.input_quantity = material.quantity
            record.input_unit = row.unit
            for field in ("layer_material_kg", "beika_kg", "material_rolls_used", "layup_operator_name",
                          "waste_quantity", "waste_unit"):
                setattr(record, field, details[field])
