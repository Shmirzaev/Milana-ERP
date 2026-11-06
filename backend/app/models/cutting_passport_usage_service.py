"""Read saved passport usage; the cutting transaction remains the stock ledger owner."""
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import func
from app.schemas import CuttingPassport, CuttingRecord, ProductionOrderMaterial, StockBatch, StockMovement, WorkOrder
from app.models.production.ect_passport_fabric_service import transferred_fabric_balance
from app.models.production.passport_material_allocation_service import (
    grouped_stock_sources, material_quantity, material_source_ids, passport_unit,
    material_stock_metadata,
    normalize_grouped_materials,
)


def validate_passport_stock(db, order, values, passport_id=None):
    """Check usage at passport entry, allowing stock already debited by this passport."""
    if order.source_type == "usluga":
        return
    sources = values.get("materials") or []
    batch_ids = [row.stock_batch_id for row in order.materials] or ([order.fabric_batch_id] if order.fabric_batch_id else [])
    if not sources and len(batch_ids) == 1:
        sources = [{**values, "stock_batch_id": batch_ids[0]}]
    consumed = {}
    if passport_id:
        consumed = dict(db.query(StockMovement.batch_id, func.sum(StockMovement.quantity)).join(
            CuttingRecord, CuttingRecord.id == StockMovement.reference_id,
        ).join(WorkOrder, WorkOrder.id == CuttingRecord.work_order_id).filter(
            CuttingRecord.cutting_passport_id == passport_id,
            WorkOrder.production_order_id == order.id,
            StockMovement.reference_type == "CuttingRecord",
            StockMovement.movement_type == "consume",
        ).group_by(StockMovement.batch_id).all())
    eco_consumed = {}
    if passport_id:
        from app.schemas.inventory.eco_inventory import EcoMaterialBatch, EcoMaterialMovement
        eco_consumed = dict(db.query(EcoMaterialBatch.source_stock_batch_id, func.sum(EcoMaterialMovement.quantity)).join(
            EcoMaterialMovement, EcoMaterialMovement.batch_id == EcoMaterialBatch.id,
        ).join(CuttingRecord, CuttingRecord.id == EcoMaterialMovement.reference_id).join(
            WorkOrder, WorkOrder.id == CuttingRecord.work_order_id,
        ).filter(CuttingRecord.cutting_passport_id == passport_id, WorkOrder.production_order_id == order.id,
            EcoMaterialMovement.reference_type == "CuttingRecord", EcoMaterialMovement.kind == "consume",
        ).group_by(EcoMaterialBatch.source_stock_batch_id).all())
    grouped_ids = [part["stock_batch_id"] for row in sources for part in row.get("batch_allocations") or []]
    group_available = material_stock_metadata(db, grouped_ids, order.id)
    for source in grouped_stock_sources(sources):
        quantity = Decimal(str(source["allocated_quantity"])) if source.get("allocated_quantity") is not None else material_quantity(source)
        batch = db.get(StockBatch, source["stock_batch_id"])
        if not batch:
            raise HTTPException(404, "Cutting material inventory batch not found")
        unit = passport_unit(source, batch.unit)
        if quantity <= 0:  # Incomplete passports may still be saved as before.
            continue
        transferred = transferred_fabric_balance(db, order.id, batch.id)
        central_available = group_available[batch.id]["available_quantity"] if batch.id in group_available else batch.quantity or 0
        available = (Decimal(str(central_available)) + Decimal(str(consumed.get(batch.id, 0)))
                     if transferred is None else transferred + Decimal(str(eco_consumed.get(batch.id, 0)))
                     + Decimal(str(consumed.get(batch.id, 0))))
        if quantity > available:
            raise HTTPException(409, f"Insufficient fabric for passport: batch {batch.batch_no}; available {available:g} {unit}; required {quantity:g} {unit}")


def passport_material_usage(db, order, passport_id, current=None):
    passport = db.query(CuttingPassport).filter_by(id=passport_id).with_for_update(of=CuttingPassport).first()
    if not passport or passport.production_order_id != order.id:
        raise HTTPException(400, "Select a saved cutting passport for this order")
    if db.query(CuttingRecord.id).filter_by(cutting_passport_id=passport.id).first():
        raise HTTPException(409, "This cutting passport has already been used. Open its cutting sheet or create a new passport")
    planned = db.query(ProductionOrderMaterial).filter_by(production_order_id=order.id).order_by(ProductionOrderMaterial.position).all()
    batch_ids = [row.stock_batch_id for row in planned] or ([order.fabric_batch_id] if order.fabric_batch_id else [])
    sources = passport.materials or []
    if current is not None:
        sources = normalize_grouped_materials(db, order, sources, current)
    if not sources and len(batch_ids) == 1:
        sources = [{column.name: getattr(passport, column.name) for column in CuttingPassport.__table__.columns}]
        sources[0]["stock_batch_id"] = batch_ids[0]
    if not sources or set(material_source_ids(sources)) != set(batch_ids):
        raise HTTPException(400, "Complete the material rows in the cutting passport before creating bundles")
    units = {row.stock_batch_id: row.unit for row in planned}
    result = []
    for source in sources:
        def number(key):
            value = Decimal(str(source.get(key) or 0))
            if not value.is_finite() or value < 0:
                raise HTTPException(400, "Correct the material quantities in the cutting passport")
            return value
        layer, layers, scrap = number("layer_weight_kg"), number("total_layers"), number("scrap_kg")
        quantity = material_quantity(source)
        if quantity <= 0:
            raise HTTPException(400, "Enter the actual material amount in the cutting passport")
        batch = db.get(StockBatch, source["stock_batch_id"])
        if not batch:
            raise HTTPException(404, "Cutting material inventory batch not found")
        unit = passport_unit(source, batch.unit)
        passport_unit(source, units.get(batch.id, batch.unit))
        pieces = number("pieces")
        waste = quantity * number("waste_pct") / 100 if number("waste_pct") > 0 else scrap
        common = {"layer_material_kg": 0 if source.get("meter_mode") else float(layer),
                                   "beika_kg": 0 if source.get("meter_mode") else float((number("beka_per_piece_kg") + number("other_beka_per_piece_kg")) * pieces),
                                   "material_rolls_used": float(number("rolls_count")),
                                   "layup_operator_name": source.get("operator_name_manual") or passport.operator_name_manual or "",
                                   "cut_pieces": int(pieces), "waste_quantity": float(round(waste, 3)), "waste_unit": unit}
        allocations = source.get("batch_allocations") or []
        if not allocations:
            result.append({"stock_batch_id": source["stock_batch_id"], "quantity": float(round(quantity, 3)), "unit": unit, "details": common})
            continue
        for part in allocations:
            passport_unit(source, units.get(part["stock_batch_id"], unit))
        from app.models.production.passport_material_allocation_service import allocated_usage_lines
        result.extend(allocated_usage_lines(source, common, quantity, unit))
    return result
