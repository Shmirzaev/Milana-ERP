"""Passport output is saved separately from confirmed bundle/stock movements."""
from fastapi import HTTPException

from app.models import Bundle, CuttingRecord, ProductionBatch, WorkOrder
from app.services.audit import log_action


def sync_passport_nastil(db, passport, current):
    # Caller holds the production order lock before the passport/batch locks.
    if not passport.production_order_id:
        return
    batches = db.query(ProductionBatch).filter_by(production_order_id=passport.production_order_id).order_by(ProductionBatch.batch_index).all()
    batch = next((row for row in batches if row.cutting_passport_id == passport.id), None)
    records = db.query(CuttingRecord).filter_by(cutting_passport_id=passport.id).all()
    if not batch and records:
        ids = {row.production_batch_id for row in records}
        if len(ids) != 1 or None in ids:
            return  # Historical unbatched/mixed cuts cannot be assigned by guessing.
        batch = next((row for row in batches if row.id in ids), None)
        if batch is None or batch.cutting_passport_id not in (None, passport.id):
            return
    if batch:
        records = db.query(CuttingRecord).filter_by(production_batch_id=batch.id).all()
    quantity = passport.pieces
    if quantity is None or quantity <= 0:
        if batch:
            raise HTTPException(409, "Enter the actual piece count for this passport Nastil")
        return  # Incomplete/manual passports remain valid drafts.
    work_order = db.query(WorkOrder).filter_by(production_order_id=passport.production_order_id, operation="cutting").first()
    if not work_order:
        return
    if not batch and work_order.status in {"completed", "cancelled", "rejected"}:
        return
    if not batch:
        # Reuse the sole unused generated planning Nastil; preserve manual names
        # and never attach a new passport to previously recorded production.
        if len(batches) == 1:
            candidate = batches[0]
            used = db.query(CuttingRecord.id).filter_by(production_batch_id=candidate.id).first() or db.query(Bundle.id).filter_by(production_batch_id=candidate.id).first()
            if not used and not candidate.cutting_passport_id and candidate.name == f"Nastil {candidate.batch_index}":
                batch = candidate
        if not batch:
            if work_order.production_batch_id is not None:
                raise HTTPException(409, "Select the existing Nastil work order before adding another passport")
            index = max((row.batch_index for row in batches), default=0) + 1
            batch_no = f"{passport.production_order_id:04d}-{index:02d}"
            while any(row.batch_no == batch_no for row in batches):
                index += 1
                batch_no = f"{passport.production_order_id:04d}-{index:02d}"
            batch = ProductionBatch(production_order_id=passport.production_order_id, batch_index=index,
                                    batch_no=batch_no, name=f"Nastil {index}", planned_quantity=quantity, start_date=passport.date)
            db.add(batch)
            db.flush()
    if records and batch.passport_actual_quantity is not None and batch.passport_actual_quantity != quantity:
        raise HTTPException(409, "This passport already has cutting records; correct its cutting quantities before changing the passport count")
    old_quantity = batch.passport_actual_quantity
    batch.cutting_passport_id = passport.id
    batch.passport_actual_quantity = quantity
    # Confirmed cutting remains authoritative downstream; saving a passport
    # must not debit fabric or create/credit bundles a second time.
    if not records and not db.query(Bundle.id).filter_by(production_batch_id=batch.id).first():
        batch.planned_quantity = quantity
    db.flush()
    log_action(db, current, "sync_passport_nastil", "ProductionBatch", batch.id,
               old_value={"passport_actual_quantity": old_quantity},
               new_value={"cutting_passport_id": passport.id, "passport_actual_quantity": quantity, "name": batch.name})


def passport_batch_map(db, passport_ids):
    if not passport_ids:
        return {}
    used_ids = set(row[0] for row in db.query(CuttingRecord.cutting_passport_id).filter(CuttingRecord.cutting_passport_id.in_(passport_ids)).distinct())
    result = {pid: {"used_for_cutting": pid in used_ids} for pid in passport_ids}
    for row in db.query(ProductionBatch).filter(ProductionBatch.cutting_passport_id.in_(passport_ids)).all():
        result[row.cutting_passport_id].update(production_batch_id=row.id, nastil_name=row.name)
        if db.query(CuttingRecord.id).filter_by(production_batch_id=row.id).first():
            result[row.cutting_passport_id]["used_for_cutting"] = True
    return result
