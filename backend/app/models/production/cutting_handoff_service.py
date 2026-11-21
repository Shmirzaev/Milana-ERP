"""Cutting storage by order and explicit Nastil dispatch to Sewing."""
import csv
from collections import defaultdict
from datetime import date, timezone
from io import StringIO

from fastapi import HTTPException
from sqlalchemy import case, func, or_
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, aliased

from app.libs.dto.production.cutting_handoff import CuttingHandoffIn
from app.libs.enums.production import CuttingHandoffFactory
from app.models.audit_service import log_action
from app.models.bundles_service import format_batch_passport
from app.models.department_dashboards_service import BUSINESS_TZ, cutting_origin_condition, destination_column, period_bounds
from app.models.factory_scope_service import cutting_department_scope
from app.models.inventory_service import ensure_accessories_issued_for_sewing
from app.models.production.cutting_balance_service import balance_totals, cutting_balances, cutting_inventory_balances
from app.models.workflow_service import notify_department, sync_production_order_status
from app.schemas import (
    AuditLog, BrandedPlanningOrder, Bundle, BundleScanLog, CuttingRecord, Department, ProductionBatch,
    ProductionOrder, SalesOrder, User, WorkOrder, public_production_order_no,
)
from app.schemas.production.cutting_handoff_persistence import record_cutting_dispatch


def _order_reference(production_no: str, sales_no: str | None) -> str:
    return sales_no or public_production_order_no(production_no) or production_no


def cutting_storage_by_order(db: Session, current: User, department: str | None) -> list[dict]:
    scope = cutting_department_scope(current, department)
    groups = [group for group in cutting_inventory_balances(db)
              if group.department == scope and group.factory in tuple(CuttingHandoffFactory)]
    references = db.query(ProductionOrder.id, ProductionOrder.production_no, SalesOrder.order_no,
                          BrandedPlanningOrder.order_no).outerjoin(
        SalesOrder, SalesOrder.id == ProductionOrder.sales_order_id,
    ).outerjoin(BrandedPlanningOrder, BrandedPlanningOrder.id == ProductionOrder.planning_order_id).filter(
        ProductionOrder.id.in_({group.order_id for group in groups}),
    ).all()
    names = {key: (branded_no or _order_reference(production_no, sales_no)) for key, production_no, sales_no, branded_no in references}
    result = []
    for factory in CuttingHandoffFactory:
        factory_groups = [group for group in groups if group.factory == factory]
        orders = defaultdict(list)
        for group in factory_groups:
            if group.order_id in names:
                orders[names[group.order_id]].append(group)
        result.append({"factory": factory, **balance_totals(factory_groups), "orders": [
            {**balance_totals(orders[number]), "order_no": number} for number in sorted(orders, reverse=True)
        ]})
    return result


def _approved_direct_bundles(db: Session, department: str, factory: CuttingHandoffFactory):
    return db.query(Bundle.id, Bundle.production_batch_id, Bundle.quantity).outerjoin(
        CuttingRecord, CuttingRecord.id == Bundle.cutting_record_id,
    ).join(Department, Department.id == Bundle.next_department_id).filter(
        Bundle.status == "created", Bundle.production_batch_id.is_not(None),
        destination_column() == factory.value, Department.code.in_((factory.value, "SEW")),
        cutting_origin_condition(db, department),
        or_(Bundle.cutting_record_id.is_(None), CuttingRecord.approval_status == "approved"),
        ~Bundle.scan_logs.any(BundleScanLog.scan_type.in_(("received_printing", "received_sewing"))),
    )


def _batch_label(batch: ProductionBatch) -> str:
    passport = format_batch_passport(batch, batch.production_order_id)
    return f"{passport} - {batch.name}" if batch.name else passport


def cutting_dispatch_options(db: Session, current: User, department: str | None,
                             factory: CuttingHandoffFactory, search: str) -> list[dict]:
    scope = cutting_department_scope(current, department)
    eligible = _approved_direct_bundles(db, scope, factory).subquery()
    blocked = db.query(Bundle.production_batch_id).filter(
        Bundle.production_batch_id.is_not(None),
        Bundle.status != "cancelled",
        or_(Bundle.status.notin_(("sent_to_sewing", "received_sewing")), destination_column() != factory.value),
        Bundle.id.notin_(db.query(eligible.c.id)),
    )
    query = db.query(ProductionBatch, ProductionOrder.production_no, SalesOrder.order_no,
                     BrandedPlanningOrder.order_no, func.sum(eligible.c.quantity)).join(
        eligible, eligible.c.production_batch_id == ProductionBatch.id,
    ).join(ProductionOrder, ProductionOrder.id == ProductionBatch.production_order_id).outerjoin(
        SalesOrder, SalesOrder.id == ProductionOrder.sales_order_id,
    ).outerjoin(BrandedPlanningOrder, BrandedPlanningOrder.id == ProductionOrder.planning_order_id).filter(
        ProductionBatch.id.notin_(blocked),
        ProductionOrder.status.notin_(("cancelled", "rejected", "completed", "finished_storage")),
    )
    if search := search.strip():
        text = search.lstrip("#")
        query = query.filter(or_(*(column.icontains(text, autoescape=True) for column in (
            ProductionBatch.batch_no, ProductionBatch.name, ProductionOrder.production_no,
            SalesOrder.order_no, BrandedPlanningOrder.order_no,
        ))))
    rows = query.group_by(ProductionBatch.id, ProductionOrder.production_no, SalesOrder.order_no,
                          BrandedPlanningOrder.order_no).order_by(ProductionBatch.id.desc()).limit(50).all()
    return [{"id": batch.id, "order_no": branded_no or _order_reference(production_no, sales_no),
             "production_no": production_no,
             "nastil": _batch_label(batch), "pieces": pieces}
            for batch, production_no, sales_no, branded_no, pieces in rows]


def dispatch_cutting_batch(db: Session, current: User, department: str | None, payload: CuttingHandoffIn) -> dict:
    scope = cutting_department_scope(current, department)
    parent_id = db.query(ProductionBatch.production_order_id).filter_by(id=payload.production_batch_id).scalar_subquery()
    order = db.query(ProductionOrder.id, ProductionOrder.status).filter(
        ProductionOrder.id == parent_id,
    ).with_for_update().first()
    if order is None:
        raise HTTPException(404, "Production batch not found")
    if order.status in {"cancelled", "rejected", "completed", "finished_storage"}:
        raise HTTPException(409, "This Nastil is no longer ready to send to Sewing.")
    try:
        db.query(WorkOrder.id).filter_by(production_order_id=order.id, operation="sewing").order_by(
            WorkOrder.id,
        ).with_for_update(of=WorkOrder, nowait=True).all()
    except OperationalError as error:
        state = getattr(error.orig, "sqlstate", None) or getattr(error.orig, "pgcode", None)
        if state != "55P03":
            raise
        db.rollback()
        raise HTTPException(409, "This production order is being updated. Reload the batch and try again.") from error
    batch = db.query(ProductionBatch).filter_by(id=payload.production_batch_id, production_order_id=order.id).with_for_update().first()
    if batch is None:
        raise HTTPException(404, "Production batch not found")
    bundles = db.query(Bundle).filter_by(production_order_id=order.id, production_batch_id=batch.id).filter(
        Bundle.status != "cancelled",
    ).order_by(Bundle.id).with_for_update(of=Bundle).all()
    eligible = {row.id for row in _approved_direct_bundles(db, scope, payload.factory).filter(
        Bundle.production_order_id == order.id, Bundle.production_batch_id == batch.id,
    )}
    if not eligible or any((bundle.sewing_factory_code or "").strip().upper() != payload.factory.value
                           or (bundle.id not in eligible and bundle.status not in {"sent_to_sewing", "received_sewing"})
                           for bundle in bundles):
        raise HTTPException(409, "This Nastil is no longer ready to send to Sewing.")
    pending = [bundle for bundle in bundles if bundle.id in eligible]
    balance_groups = [group for group in cutting_balances(db, order_id=order.id)
                      if group.batch_id == batch.id and group.department == scope and group.factory == payload.factory]
    if not any(not group.adjusted and eligible <= group.bundle_quantities.keys() for group in balance_groups):
        raise HTTPException(409, "This Nastil is no longer ready to send to Sewing.")
    departments = {row.code: row for row in db.query(Department).filter(Department.code.in_((scope, payload.factory.value)))}
    if not {scope, payload.factory.value} <= departments.keys():
        raise HTTPException(409, "This Nastil is no longer ready to send to Sewing.")
    ensure_accessories_issued_for_sewing(db, order.id, sewing_factory_code=payload.factory.value,
                                       production_batch_id=batch.id)
    target = departments[payload.factory.value]
    record_cutting_dispatch(db, pending, origin_id=departments[scope].id, destination_id=target.id,
                            factory=payload.factory, actor_id=current.id)
    pieces = sum(bundle.quantity for bundle in pending)
    log_action(db, current, "dispatch_cutting_batch", "ProductionBatch", batch.id,
               new_value={"factory": payload.factory.value, "pieces": pieces,
                          "bundles": [{"id": b.id, "quantity": b.quantity} for b in pending]})
    notify_department(db, department_code=target.code, title="Nastil sent to Sewing",
                      message=f"{_batch_label(batch)} is ready for receiving.",
                      link="/bundles/scan/sewing", exclude_user_id=current.id)
    sync_production_order_status(db, order.id)
    db.commit()
    return {"pieces": pieces, "bundles": len(pending)}


def cutting_handoffs(db: Session, current: User, department: str | None, day: date,
                     *, pending: bool = False) -> list[dict]:
    scope = cutting_department_scope(current, department)
    start, end = period_bounds(day, day)
    destination = aliased(Department)
    dispatch = db.query(
        BundleScanLog.bundle_id, BundleScanLog.id, BundleScanLog.scanned_at, case((destination.code == "SEW", "MIL"), else_=destination.code).label("factory"),
    ).join(Bundle, Bundle.id == BundleScanLog.bundle_id).join(
        destination, destination.id == BundleScanLog.to_department_id,
    ).filter(BundleScanLog.scan_type == "sent_sewing", destination.code.in_((*CuttingHandoffFactory, "SEW")),
             cutting_origin_condition(db, scope), Bundle.status != "cancelled")
    if pending:
        dispatch = dispatch.filter(Bundle.status == "sent_to_sewing")
    else:
        dispatch = dispatch.filter(BundleScanLog.scanned_at >= start, BundleScanLog.scanned_at < end)
    sent = dispatch.cte("cutting_dispatched_bundles")
    receipts = db.query(sent.c.id.label("scan_id"), func.min(BundleScanLog.scanned_at).label("received_at")).join(
        BundleScanLog, BundleScanLog.bundle_id == sent.c.bundle_id,
    ).filter(BundleScanLog.scan_type == "received_sewing",
             BundleScanLog.scanned_at >= sent.c.scanned_at).group_by(sent.c.id).subquery()
    query = db.query(Bundle.id, Bundle.quantity, ProductionOrder.production_no, SalesOrder.order_no,
                     BrandedPlanningOrder.order_no, ProductionBatch, sent.c.factory, sent.c.scanned_at,
                     receipts.c.received_at).select_from(sent).join(Bundle, Bundle.id == sent.c.bundle_id).outerjoin(
        receipts, receipts.c.scan_id == sent.c.id,
    ).join(ProductionOrder, ProductionOrder.id == Bundle.production_order_id).outerjoin(
        SalesOrder, SalesOrder.id == ProductionOrder.sales_order_id,
    ).outerjoin(BrandedPlanningOrder, BrandedPlanningOrder.id == ProductionOrder.planning_order_id).outerjoin(
        ProductionBatch, ProductionBatch.id == Bundle.production_batch_id,
    )
    if pending:
        query = query.filter(receipts.c.received_at.is_(None))
    rows = query.order_by(sent.c.scanned_at, sent.c.id).all()
    batch_ids = {row[5].id for row in rows if row[5] is not None}
    dispatch_values = db.query(AuditLog.new_value_json).filter(
        AuditLog.action == "dispatch_cutting_batch", AuditLog.entity_type == "ProductionBatch",
        AuditLog.entity_id.in_(batch_ids),
    ).all() if batch_ids else []
    sent_quantities = {bundle["id"]: bundle["quantity"] for (event,) in dispatch_values
                       for bundle in (event or {}).get("bundles", ())}
    groups = {}
    seen = set()
    for bid, qty, production_no, sales_no, branded_no, batch, factory, sent_at, received_at in rows:
        qty = sent_quantities.get(bid, qty)
        if bid in seen:
            continue
        seen.add(bid)
        key = (production_no, batch.id if batch else None, factory)
        row = groups.setdefault(key, {
            "order_no": branded_no or _order_reference(production_no, sales_no),
            "production_no": production_no,
            "nastil": _batch_label(batch) if batch else None, "factory": factory, "pieces": 0,
            "received_pieces": 0, "first_sent_at": _utc(sent_at), "last_received_at": None,
        })
        row["pieces"] += qty
        if received_at:
            row["received_pieces"] += qty
            row["last_received_at"] = max(row["last_received_at"] or _utc(received_at), _utc(received_at))
    return list(reversed(groups.values()))


def _utc(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def cutting_handoff_csv(rows: list[dict]) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(("Order", "Production order", "Nastil", "Dispatched to", "Sent pieces", "Accepted pieces",
                     "In transit pieces", "First sent (Tashkent)", "Last accepted (Tashkent)"))
    def safe(value):
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value

    for row in rows:
        writer.writerow((safe(row["order_no"]), safe(row["production_no"]), safe(row["nastil"] or ""),
                         "Milana" if row["factory"] == "MIL" else "Besttex", row["pieces"], row["received_pieces"],
                         row["pieces"] - row["received_pieces"],
                         row["first_sent_at"].astimezone(BUSINESS_TZ).isoformat(sep=" ", timespec="seconds"),
                         row["last_received_at"].astimezone(BUSINESS_TZ).isoformat(sep=" ", timespec="seconds")
                         if row["last_received_at"] else ""))
    return "\ufeff" + output.getvalue()
