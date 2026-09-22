"""Read saved passport usage; the cutting transaction remains the stock ledger owner."""
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import func
from app.models import CuttingPassport, CuttingRecord, ProductionOrderMaterial, StockBatch, StockMovement, WorkOrder


def material_quantity(source):
    def number(key):
        value = Decimal(str(source.get(key) or 0))
        if not value.is_finite() or value < 0:
            raise HTTPException(400, "Correct the material quantities in the cutting passport")
        return value
    layer, layers = number("layer_weight_kg"), number("total_layers")
    return round(layer * layers + number("scrap_kg") if layer > 0 and layers > 0 else number("planned_kg"), 3)


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
    for source in sources:
        quantity = material_quantity(source)
        if quantity <= 0:  # Incomplete passports may still be saved as before.
            continue
        batch = db.get(StockBatch, source["stock_batch_id"])
        if not batch:
            raise HTTPException(404, "Cutting material inventory batch not found")
        available = Decimal(str(batch.quantity or 0)) + Decimal(str(consumed.get(batch.id, 0)))
        if quantity > available:
            raise HTTPException(409, f"Insufficient fabric for passport: batch {batch.batch_no}; available {available:g} kg; required {quantity:g} kg")


def passport_material_usage(db, order, passport_id):
    passport = db.query(CuttingPassport).filter_by(id=passport_id).with_for_update(of=CuttingPassport).first()
    if not passport or passport.production_order_id != order.id:
        raise HTTPException(400, "Select a saved cutting passport for this order")
    if db.query(CuttingRecord.id).filter_by(cutting_passport_id=passport.id).first():
        raise HTTPException(409, "This cutting passport has already been used. Open its cutting sheet or create a new passport")
    planned = db.query(ProductionOrderMaterial).filter_by(production_order_id=order.id).order_by(ProductionOrderMaterial.position).all()
    batch_ids = [row.stock_batch_id for row in planned] or ([order.fabric_batch_id] if order.fabric_batch_id else [])
    sources = passport.materials or []
    if not sources and len(batch_ids) == 1:
        sources = [{column.name: getattr(passport, column.name) for column in CuttingPassport.__table__.columns}]
        sources[0]["stock_batch_id"] = batch_ids[0]
    if not sources or {row.get("stock_batch_id") for row in sources} != set(batch_ids):
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
        if str(units.get(source["stock_batch_id"], "kg")).strip().lower() != "kg":
            raise HTTPException(400, "Passport material usage requires a kilogram inventory batch")
        pieces = number("pieces")
        waste = quantity * number("waste_pct") / 100 if number("waste_pct") > 0 else scrap
        result.append({"stock_batch_id": source["stock_batch_id"], "quantity": float(round(quantity, 3)), "unit": "kg",
                       "details": {"layer_material_kg": float(layer),
                                   "beika_kg": float((number("beka_per_piece_kg") + number("other_beka_per_piece_kg")) * pieces),
                                   "material_rolls_used": float(number("rolls_count")),
                                   "layup_operator_name": source.get("operator_name_manual") or passport.operator_name_manual or "",
                                   "cut_pieces": int(pieces), "waste_quantity": float(round(waste, 3)), "waste_unit": "kg"}})
    return result
