"""Remove an unused Nastil and reverse only proven fabric consumption."""

from collections import defaultdict
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import OperationalError

from app.db.base import Base
from app.schemas import (
    Bundle, CuttingRecord, MaterialReservation, ProductionBatch, ProductionOrder,
    SewingAssignment, StockBatch, StockMovement, WasteRecord, WasteSale, WorkOrder,
)
from app.models.audit_service import log_action
from app.models.cutting_batch_guard_service import require_cutting_batch_mutable
from app.models.inventory_service import _set_reservation_status


def _snapshot(row):
    return {column.key: getattr(row, column.key) for column in row.__table__.columns}


def _reject_references(db, table_name, ids, allowed):
    if not ids:
        return
    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_keys:
            if fk.column.table.name == table_name and table.name not in allowed:
                if db.execute(select(fk.parent).where(fk.parent.in_(ids)).limit(1)).first():
                    raise HTTPException(409, "This batch has linked production, payroll or packaging history and cannot be deleted")


def delete_cutting_batch(db, work, batch_id, current):
    try:
        return _delete_cutting_batch(db, work, batch_id, current)
    except OperationalError as error:
        if getattr(error.orig, "sqlstate", None) == "55P03" or getattr(error.orig, "pgcode", None) == "55P03":
            raise HTTPException(409, "This production order is being updated. Reload the batch and try again.") from error
        raise


def _delete_cutting_batch(db, work, batch_id, current):
    require_cutting_batch_mutable(db, work, batch_id)
    order = db.query(ProductionOrder).filter_by(id=work.production_order_id).with_for_update(
        of=ProductionOrder, nowait=True,
    ).one()
    if order.status in {"completed", "cancelled", "rejected"}:
        raise HTTPException(409, "A batch cannot be deleted from a closed production order")
    # Hold all stage locks before reading evidence; output submissions serialize here.
    db.query(WorkOrder).filter_by(production_order_id=order.id).order_by(
        WorkOrder.id,
    ).with_for_update(of=WorkOrder, nowait=True).populate_existing().all()
    batch = db.query(ProductionBatch).filter_by(
        id=batch_id, production_order_id=order.id,
    ).with_for_update(of=ProductionBatch).first()
    if not batch:
        raise HTTPException(404, "Production batch not found for this cutting work order")
    require_cutting_batch_mutable(db, work, batch.id)
    records = db.query(CuttingRecord).filter_by(production_batch_id=batch.id).order_by(
        CuttingRecord.id,
    ).with_for_update(of=CuttingRecord).all()
    if any(row.work_order_id != work.id for row in records):
        raise HTTPException(409, "Batch cutting records belong to another work order")
    bundles = db.query(Bundle).filter_by(production_batch_id=batch.id).order_by(
        Bundle.id,
    ).with_for_update(of=Bundle).all()
    if any(row.status not in {"created", "sent_to_sewing", "received_sewing"} or any(
        scan.scan_type not in {"created", "sent_sewing", "received_sewing"} for scan in row.scan_logs
    ) for row in bundles):
        raise HTTPException(409, "This batch has processing history that cannot be reversed by Cutting")
    receipt_changes = []
    received = sum(row.quantity for row in bundles if row.status == "received_sewing")
    if received:
        from app.models.bundles_service import _work_order_for_bundle
        sewing = _work_order_for_bundle(db, bundles[0], "sewing")
        received_query = db.query(func.coalesce(func.sum(Bundle.quantity), 0)).filter(
            Bundle.production_order_id == order.id, Bundle.status == "received_sewing",
        )
        if sewing and sewing.production_batch_id is not None:
            received_query = received_query.filter(Bundle.production_batch_id == sewing.production_batch_id)
        if not sewing or sewing.actual_input_qty != received_query.scalar():
            raise HTTPException(409, "Sewing receipt totals need review before deleting this batch")
        receipt_changes.append({"work_order_id": sewing.id, "before": sewing.actual_input_qty,
                                "after": sewing.actual_input_qty - received})
        sewing.actual_input_qty -= received
    assignments = db.query(SewingAssignment).filter_by(production_batch_id=batch.id).with_for_update(
        of=SewingAssignment,
    ).all()
    record_ids = [row.id for row in records]
    bundle_ids = [row.id for row in bundles]
    _reject_references(db, "production_batches", [batch.id], {"cutting_records", "bundles", "sewing_assignments"})
    _reject_references(db, "cutting_records", record_ids, {"cutting_material_usages", "cutting_beika_material_usages", "bundles"})
    _reject_references(db, "bundles", bundle_ids, {"bundle_scan_logs"})
    _reject_references(db, "sewing_assignments", [row.id for row in assignments], set())
    # Unallocated legacy evidence cannot be assigned to a sibling by guessing.
    stage_ids = select(WorkOrder.id).where(WorkOrder.production_order_id == order.id)
    for name in ("printing_records", "packaging_records", "packaging_receipts", "packages",
                 "payroll_records", "payroll_qr_labels", "sewing_daily_reports", "sewing_replacement_requests"):
        table = Base.metadata.tables[name]
        scope = table.c.production_order_id == order.id if "production_order_id" in table.c else table.c.work_order_id.in_(stage_ids)
        history = select(table.c.id).where(scope, table.c.production_batch_id.is_(None))
        if name == "payroll_qr_labels":
            # Retain retired, never-used labels for audit without freezing every
            # empty sibling Nastil. Any usage or derived-label history still blocks.
            children = table.alias("derived_labels")
            payroll = Base.metadata.tables["payroll_records"]
            unused_retired = and_(
                table.c.status == "superseded",
                table.c.payroll_record_id.is_(None),
                table.c.last_scanned_at.is_(None),
                table.c.returned_at.is_(None),
                table.c.returned_by.is_(None),
                table.c.return_count == 0,
                table.c.split_from_label_id.is_(None),
                ~select(children.c.id).where(children.c.split_from_label_id == table.c.id).exists(),
                ~select(payroll.c.id).where(
                    payroll.c.factory_code == table.c.factory_code,
                    or_(payroll.c.scan_uid == table.c.label_uid, payroll.c.original_scan_uid == table.c.label_uid),
                ).exists(),
            )
            history = history.where(~unused_retired)
        if db.execute(history.limit(1)).first():
            raise HTTPException(409, "Unallocated downstream history must be reviewed before deleting this batch")
    # Detect broken legacy links rather than deleting another batch's bundle.
    if db.query(Bundle.id).filter(Bundle.cutting_record_id.in_(record_ids), Bundle.id.notin_(bundle_ids)).first():
        raise HTTPException(409, "Cutting records have bundles outside the selected batch")

    expected = defaultdict(Decimal)
    for row in records:
        materials = list(row.materials) + list(row.beika_materials)
        if materials:
            for usage in materials:
                consumption = (getattr(usage, "details", None) or {}).get("inventory_consumption") or {}
                if consumption.get("status") == "pending" and consumption.get("consumed_quantity") == 0:
                    continue  # A saved shortage never debited stock.
                expected[(row.id, usage.stock_batch_id, usage.unit)] += Decimal(str(usage.quantity))
        elif row.fabric_batch_id and row.input_quantity:
            expected[(row.id, row.fabric_batch_id, row.input_unit)] += Decimal(str(row.input_quantity))
    movements = db.query(StockMovement).filter(
        StockMovement.reference_type == "CuttingRecord", StockMovement.reference_id.in_(record_ids),
    ).order_by(StockMovement.id).with_for_update(of=StockMovement).all() if record_ids else []
    actual = defaultdict(Decimal)
    records_by_id = {row.id: row for row in records}
    for movement in movements:
        rec = records_by_id[movement.reference_id]
        if movement.movement_type != "consume" or movement.created_at < rec.created_at:
            raise HTTPException(409, "Fabric movement history needs review before deleting this batch")
        actual[(rec.id, movement.batch_id, movement.unit)] += Decimal(str(movement.quantity))
    if dict(actual) != dict(expected):
        raise HTTPException(409, "Fabric usage does not match stock movements; review this batch before deletion")

    returns = defaultdict(Decimal)
    for (_, stock_id, unit), quantity in actual.items():
        returns[(stock_id, unit)] += quantity
    stocks = {row.id: row for row in db.query(StockBatch).filter(
        StockBatch.id.in_([key[0] for key in returns]),
    ).order_by(StockBatch.id).with_for_update(of=StockBatch).populate_existing()}
    reservation_changes = []
    for (stock_id, unit), quantity in returns.items():
        stock = stocks.get(stock_id)
        if not stock or stock.unit != unit or any(
            movement.item_id != stock.item_id or movement.from_warehouse_id != stock.warehouse_id
            for movement in movements if movement.batch_id == stock_id
        ):
            raise HTTPException(409, "The consumed fabric identity or warehouse has changed")
        reservations = db.query(MaterialReservation).filter(
            MaterialReservation.production_order_id == order.id,
            MaterialReservation.stock_batch_id == stock_id,
            MaterialReservation.consumed_quantity > 0,
        ).order_by(MaterialReservation.id).with_for_update(of=MaterialReservation).populate_existing().all()
        if reservations:
            all_record_ids = db.query(CuttingRecord.id).join(WorkOrder, WorkOrder.id == CuttingRecord.work_order_id).filter(
                WorkOrder.production_order_id == order.id,
            )
            all_consumption = sum((Decimal(str(row.quantity)) for row in db.query(StockMovement).filter(
                StockMovement.reference_type == "CuttingRecord", StockMovement.reference_id.in_(all_record_ids),
                StockMovement.batch_id == stock_id, StockMovement.movement_type == "consume",
            )), Decimal(0))
            # Legacy movements do not store reservation IDs. Only reverse an
            # allocation when its exact ownership is provable.
            if len(reservations) != 1 or Decimal(str(reservations[0].consumed_quantity)) != all_consumption:
                raise HTTPException(409, "Fabric reservation allocation is ambiguous; review it before batch deletion")
            reservation = reservations[0]
            if reservation.unit != unit or Decimal(str(reservation.consumed_quantity)) < quantity:
                raise HTTPException(409, "Fabric reservation does not match the recorded consumption")
            reservation_changes.append({"id": reservation.id, "quantity": str(quantity)})
            reservation.consumed_quantity = Decimal(str(reservation.consumed_quantity)) - quantity
            _set_reservation_status(reservation)

    # Waste has no cutting_record_id in legacy schema. Transaction timestamps
    # plus exact material/quantity evidence must identify it without guessing.
    waste_rows = []
    for rec in records:
        waste_expected = defaultdict(Decimal)
        if rec.materials:
            for usage in rec.materials:
                details = usage.details or {}
                quantity = Decimal(str(details.get("waste_quantity") or 0))
                if quantity:
                    waste_expected[(usage.stock_batch_id, details.get("waste_unit") or "kg")] += quantity
        elif rec.waste_quantity:
            waste_expected[(rec.fabric_batch_id, rec.waste_unit)] += Decimal(str(rec.waste_quantity))
        if not waste_expected:
            continue
        same_transaction = [row for row in db.query(CuttingRecord.id, CuttingRecord.created_at).filter(
            CuttingRecord.work_order_id == work.id,
        ) if row.created_at == rec.created_at]
        if len(same_transaction) != 1:
            raise HTTPException(409, "Waste history cannot be attributed uniquely to this cutting record")
        candidates = [row for row in db.query(WasteRecord).filter_by(
            work_order_id=work.id, waste_type="cutting_waste",
        ).with_for_update(of=WasteRecord) if row.created_at == rec.created_at]
        waste_actual = defaultdict(Decimal)
        for row in candidates:
            waste_actual[(row.batch_id, row.unit)] += Decimal(str(row.quantity))
        if dict(waste_actual) != dict(waste_expected) or any(row.status != "recorded" for row in candidates):
            raise HTTPException(409, "Waste history needs review before deleting this cutting batch")
        if candidates and db.query(WasteSale.id).filter(WasteSale.waste_record_id.in_([row.id for row in candidates])).first():
            raise HTTPException(409, "Sold waste cannot be reversed")
        waste_rows.extend(candidates)

    old = {"batch": _snapshot(batch), "records": [
        {**_snapshot(row), "materials": [_snapshot(x) for x in row.materials],
         "beika_materials": [_snapshot(x) for x in row.beika_materials]} for row in records
    ], "bundles": [{**_snapshot(row), "scans": [_snapshot(x) for x in row.scan_logs]} for row in bundles],
        "assignments": [_snapshot(row) for row in assignments], "waste": [_snapshot(row) for row in waste_rows]}
    for (stock_id, unit), quantity in returns.items():
        stock = stocks[stock_id]
        stock.quantity = Decimal(str(stock.quantity)) + quantity
        stock.archived_at = None
        stock.archived_by = None
        db.add(StockMovement(
            movement_type="return", item_id=stock.item_id, batch_id=stock.id,
            to_warehouse_id=stock.warehouse_id, quantity=quantity, unit=unit,
            reference_type="CuttingBatchDeletion", reference_id=batch.id, created_by=current.id,
        ))
    for row in [*waste_rows, *assignments, *bundles]:
        db.delete(row)
    db.flush()
    for row in records:
        db.delete(row)
    db.flush()
    db.delete(batch)
    db.flush()
    # Preserve the sales/order plan; only remove this erroneous physical output.
    from app.api.routes.production import _sync_cutting_work_order_from_records, _reconcile_cutting_workflow_plans
    work.status = "in_progress"
    work.end_time = None
    _sync_cutting_work_order_from_records(db, work)
    if order.source_type == "usluga":
        from app.api.routes.production import _sync_usluga_material_usage
        _sync_usluga_material_usage(db, order)
    _reconcile_cutting_workflow_plans(db, work)
    log_action(db, current, "delete_cutting_batch", "ProductionBatch", batch_id, old_value=old, new_value={
        "deleted": True, "returned_fabric": [{"stock_batch_id": sid, "unit": unit, "quantity": str(q)}
                                            for (sid, unit), q in returns.items()],
        "restored_reservations": reservation_changes,
        "reversed_sewing_receipts": receipt_changes,
    })
    return {"deleted": True, "batch_no": batch.batch_no, "deleted_bundle_count": len(bundles)}
