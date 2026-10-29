"""Route selected, unused Nastils without moving another Nastil's history."""
from fastapi import HTTPException
from sqlalchemy import or_

from app.schemas import (Bundle, Department, Package, PackageBatchAllocation, PackagingRecord,
                         PackagingReceipt, PayrollQrLabel, PayrollRecord, ProductionBatch,
                         ProductionOrder, SewingAssignment, WorkOrder)
from app.schemas.production.factory_routing import (assign_batch_work_order, assign_bundle_factory,
    cancel_unused_assignment, complete_empty_shared_stage, insert_batch_work_order, reduce_shared_plan)
from app.models.audit_service import log_action
from app.models.cutting_batch_guard_service import require_cutting_batch_mutable
from app.models.factory_scope_service import PACKAGING_DEPARTMENTS
from app.models.sewing_input_service import sync_sewing_input


def change_nastil_factories(db, work, factory, batch_ids, current):
    order = db.query(ProductionOrder).filter_by(id=work.production_order_id).with_for_update(
        of=ProductionOrder, nowait=True).one()
    if order.source_type != "standard" or order.status in {"completed", "cancelled", "rejected", "finished_storage"}:
        raise HTTPException(409, "SEWING_FACTORY_ORDER_LOCKED")
    works = db.query(WorkOrder).filter_by(production_order_id=order.id).order_by(WorkOrder.id).with_for_update(
        of=WorkOrder, nowait=True).populate_existing().all()
    batches = db.query(ProductionBatch).filter(ProductionBatch.production_order_id == order.id,
        ProductionBatch.id.in_(batch_ids)).order_by(ProductionBatch.id).with_for_update().all()
    if len(batches) != len(batch_ids):
        raise HTTPException(404, "Nastil not found for this order")
    for batch in batches:
        require_cutting_batch_mutable(db, work, batch.id)
    departments = {d.code: d.id for d in db.query(Department)}
    if factory not in departments or PACKAGING_DEPARTMENTS[factory] not in departments:
        raise HTTPException(409, "Factory departments are not configured")
    bundles = db.query(Bundle).filter(Bundle.production_order_id == order.id,
        Bundle.production_batch_id.in_(batch_ids), Bundle.status != "cancelled").order_by(Bundle.id).with_for_update(
            of=Bundle, nowait=True).populate_existing().all()
    if not bundles or set(b.production_batch_id for b in bundles) != set(batch_ids):
        raise HTTPException(409, "Select Nastils with saved cutting bundles")
    if any(b.status not in {"created", "sent_to_printing", "received_printing", "sent_to_sewing", "received_sewing"} for b in bundles):
        raise HTTPException(409, "SEWING_FACTORY_HISTORY_LOCKED")
    # Refuse selected or unattributed downstream evidence. Other Nastils' history
    # must not prevent an independent destination correction.
    for model in (Package, PayrollQrLabel, PayrollRecord, PackagingReceipt):
        if db.query(model.id).filter(model.production_order_id == order.id,
            or_(model.production_batch_id.in_(batch_ids), model.production_batch_id.is_(None))).first():
            raise HTTPException(409, "SEWING_FACTORY_HISTORY_LOCKED")
    if db.query(PackageBatchAllocation.id).join(Package, Package.id == PackageBatchAllocation.package_id).filter(
        Package.production_order_id == order.id, PackageBatchAllocation.production_batch_id.in_(batch_ids)).first():
        raise HTTPException(409, "SEWING_FACTORY_HISTORY_LOCKED")
    if db.query(PackagingRecord.id).filter(PackagingRecord.work_order_id.in_([w.id for w in works]),
        or_(PackagingRecord.production_batch_id.in_(batch_ids), PackagingRecord.production_batch_id.is_(None))).first():
        raise HTTPException(409, "SEWING_FACTORY_HISTORY_LOCKED")
    assignments = db.query(SewingAssignment).filter(SewingAssignment.work_order_id.in_([w.id for w in works]),
        SewingAssignment.status.notin_({"cancelled", "transferred"}),
        or_(SewingAssignment.production_batch_id.in_(batch_ids), SewingAssignment.production_batch_id.is_(None))).order_by(
            SewingAssignment.id).with_for_update(of=SewingAssignment, nowait=True).all()
    if any(a.production_batch_id is None or a.completed_qty or a.actual_end for a in assignments):
        raise HTTPException(409, "SEWING_FACTORY_HISTORY_LOCKED")
    sewing_ids = {departments[c] for c in ("MIL", "BST", "ECO", "SEW") if c in departments}
    packaging_ids = {departments[c] for c in ("PKG", "BPK", "ECP") if c in departments}
    before = {"bundles": [{"id": b.id, "factory": b.sewing_factory_code} for b in bundles]}
    changed = False
    for batch in batches:
        scoped = [b for b in bundles if b.production_batch_id == batch.id]
        def routed_work(operation):
            rows = [w for w in works if w.operation == operation and w.status != "cancelled"]
            return next((w for w in rows if w.production_batch_id == batch.id),
                        next((w for w in rows if w.production_batch_id is None), None))
        routing_matches = all(routed_work(operation) and routed_work(operation).department_id == departments[code]
            for operation, code in (("sewing", factory), ("packaging", PACKAGING_DEPARTMENTS[factory])))
        if all(b.sewing_factory_code == factory for b in scoped) and routing_matches:
            continue
        changed = True
        quantity = sum(b.quantity for b in scoped)
        for operation, code in (("sewing", factory), ("packaging", PACKAGING_DEPARTMENTS[factory])):
            exact = next((w for w in works if w.operation == operation and w.production_batch_id == batch.id and w.status != "cancelled"), None)
            if exact:
                assign_batch_work_order(exact, departments[code])
            else:
                shared = next((w for w in works if w.operation == operation and w.production_batch_id is None and w.status != "cancelled"), None)
                if not shared:
                    raise HTTPException(409, "Stage work order not found")
                received = sum(b.quantity for b in scoped if b.status == "received_sewing") if operation == "sewing" else 0
                exact = insert_batch_work_order(db, shared, batch.id, departments[code], quantity, received)
                reduce_shared_plan(shared, max(quantity, batch.planned_quantity))
                works.append(exact)
        for b in scoped:
            assign_bundle_factory(b, factory, departments[factory], departments[PACKAGING_DEPARTMENTS[factory]], sewing_ids, packaging_ids)
        for assignment in assignments:
            if assignment.production_batch_id == batch.id:
                cancel_unused_assignment(assignment)
    if changed:
        db.flush()
        for row in works:
            if row.operation == "sewing":
                sync_sewing_input(db, row)
            if row.operation in {"sewing", "packaging"} and row.production_batch_id is None:
                from app.models.production.batch_scope_service import filter_work_order_batches
                if not filter_work_order_batches(db.query(ProductionBatch.id).filter(
                    ProductionBatch.production_order_id == order.id), ProductionBatch.id, row).first():
                    complete_empty_shared_stage(row)
        log_action(db, current, "change_nastil_factory", "ProductionOrder", order.id, old_value=before,
            new_value={"production_batch_ids": batch_ids, "sewing_factory_code": factory,
                       "bundles": [{"id": b.id, "factory": b.sewing_factory_code} for b in bundles]})
    return {"sewing_factory_code": factory, "production_batch_ids": batch_ids, "changed": changed}
