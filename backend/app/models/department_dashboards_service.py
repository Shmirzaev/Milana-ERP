"""Read-only department boards. Current balances and period movements stay separate."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import selectinload

from app.models import (
    Bundle, BundleScanLog, CuttingRecord, Department, Model, Package,
    ProductionBatch, ProductionOrder, SalesOrder, Shipment, ShipmentPackage, WasteRecord, WorkOrder,
)
from app.models.model_images_service import model_preview_image_url, model_print_image_url
from app.core.signing import sign_path

FACTORIES = ("MIL", "BST", "ECO", "UNASSIGNED")
BUSINESS_TZ = ZoneInfo("Asia/Tashkent")


def period_bounds(start: date, end: date):
    if end < start or (end - start).days > 365:
        raise HTTPException(422, "Choose an ordered date range of at most 366 days")
    return (datetime.combine(start, time.min, BUSINESS_TZ).astimezone(timezone.utc),
            datetime.combine(end + timedelta(days=1), time.min, BUSINESS_TZ).astimezone(timezone.utc))


def cutting_inventory_condition():
    received_printing = Bundle.scan_logs.any(BundleScanLog.scan_type == "received_printing")
    return or_(Bundle.status.in_(("created", "sent_to_printing")),
               and_(Bundle.status == "sent_to_sewing", ~received_printing))


def cutting_origin_condition(db, department: str):
    eco_orders = db.query(WorkOrder.production_order_id).join(Department).filter(
        WorkOrder.operation == "cutting", Department.code == "ECT")
    return (Bundle.production_order_id.in_(eco_orders) if department == "ECT"
            else Bundle.production_order_id.notin_(eco_orders))


def destination_column():
    normalized = func.upper(func.trim(Bundle.sewing_factory_code))
    return case((normalized.in_(FACTORIES[:3]), normalized), else_="UNASSIGNED")


def inventory_totals(db, query):
    """Aggregate before pagination; cutting jobs are distinct work-order identities."""
    total, pieces, orders = query.with_entities(
        func.count(Bundle.id), func.coalesce(func.sum(Bundle.quantity), 0),
        func.count(func.distinct(Bundle.production_order_id)),
    ).order_by(None).one()
    work_ids = db.query(CuttingRecord.work_order_id).filter(
        CuttingRecord.id.in_(query.with_entities(Bundle.cutting_record_id).order_by(None)))
    work_count = db.query(func.count(func.distinct(WorkOrder.id))).filter(WorkOrder.id.in_(work_ids)).scalar()
    return {"bundles": int(total), "pieces": int(pieces), "orders": int(orders), "work_orders": int(work_count or 0)}


def cutting_board(db, department: str, start: date, end: date):
    lower, upper = period_bounds(start, end)
    base = db.query(Bundle).filter(cutting_origin_condition(db, department), Bundle.status != "cancelled")
    current = base.filter(cutting_inventory_condition())
    destination = destination_column()
    grouped = current.with_entities(destination, func.count(Bundle.id), func.sum(Bundle.quantity),
                                    func.count(func.distinct(Bundle.production_order_id))).group_by(destination).all()
    by_factory = {code: {"factory": code, "bundles": 0, "pieces": 0, "orders": 0,
                         "created_bundles": 0, "created_pieces": 0,
                         "transferred_bundles": 0, "transferred_pieces": 0} for code in FACTORIES}
    for code, count, pieces, orders in grouped:
        by_factory[code].update(bundles=int(count), pieces=int(pieces or 0), orders=int(orders))
    created = base.filter(Bundle.created_at >= lower, Bundle.created_at < upper).with_entities(
        destination, func.count(Bundle.id), func.sum(Bundle.quantity)).group_by(destination).all()
    # First physical receipt is the exit from Cutting. Repeated scans and the
    # later Printing -> Sewing receipt must never count the same bundle twice.
    first_receipt = db.query(BundleScanLog.bundle_id.label("bundle_id"),
                             func.min(BundleScanLog.scanned_at).label("received_at")).filter(
        BundleScanLog.scan_type.in_(("received_printing", "received_sewing")),
    ).group_by(BundleScanLog.bundle_id).subquery()
    transferred = base.join(first_receipt, first_receipt.c.bundle_id == Bundle.id).filter(
        first_receipt.c.received_at >= lower, first_receipt.c.received_at < upper).with_entities(
        destination, func.count(Bundle.id), func.sum(Bundle.quantity)).group_by(destination).all()
    for code, count, pieces in created:
        by_factory[code].update(created_bundles=int(count), created_pieces=int(pieces or 0))
    for code, count, pieces in transferred:
        by_factory[code].update(transferred_bundles=int(count), transferred_pieces=int(pieces or 0))
    wastes = db.query(WasteRecord.unit, func.count(WasteRecord.id), func.sum(WasteRecord.quantity)).join(
        Department, Department.id == WasteRecord.source_department_id).filter(
        Department.code == department, WasteRecord.waste_type.in_(("cutting_waste", "fabric")),
        WasteRecord.created_at >= lower, WasteRecord.created_at < upper,
    ).group_by(WasteRecord.unit).all()
    return {"totals": inventory_totals(db, current), "factories": list(by_factory.values()),
            "waste": [{"unit": unit, "records": int(count), "quantity": float(quantity or 0)}
                      for unit, count, quantity in wastes],
            "start": start, "end": end, "timezone": str(BUSINESS_TZ),
            "updated_at": datetime.now(timezone.utc)}


def _image_attachment(attachments):
    for item in attachments or []:
        path = str(item.get("file_url") or "")
        if str(item.get("content_type") or "").startswith("image/") or path.lower().split("?")[0].endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
            return sign_path(path)
    return None


def printing_board(db, *, offset: int = 0, limit: int = 24):
    pending = db.query(Bundle).join(Department, Department.id == Bundle.next_department_id).join(
        ProductionOrder, ProductionOrder.id == Bundle.production_order_id).filter(
        Department.code == "PRT", Bundle.status.in_(("created", "sent_to_printing")),
        ProductionOrder.status.notin_(("cancelled", "rejected")))
    totals = inventory_totals(db, pending)
    groups = pending.with_entities(Bundle.production_order_id, Bundle.production_batch_id, Bundle.model_id,
                                   func.count(Bundle.id).label("bundles"), func.sum(Bundle.quantity).label("pieces"),
                                   func.min(Bundle.created_at).label("waiting_since"),
                                   func.min(ProductionOrder.deadline).label("deadline")).group_by(
        Bundle.production_order_id, Bundle.production_batch_id, Bundle.model_id)
    total_groups = groups.count()
    rows = groups.order_by(func.min(ProductionOrder.deadline).asc().nullslast(),
                           func.min(Bundle.created_at), Bundle.production_order_id,
                           Bundle.production_batch_id, Bundle.model_id).offset(offset).limit(limit).all()
    batch_ids = {r.production_batch_id for r in rows if r.production_batch_id is not None}
    batch_names = dict(db.query(ProductionBatch.id, ProductionBatch.name).filter(
        ProductionBatch.id.in_(batch_ids)).all()) if batch_ids else {}
    po_ids = {r.production_order_id for r in rows}
    orders = {p.id: p for p in db.query(ProductionOrder).filter(ProductionOrder.id.in_(po_ids)).all()} if po_ids else {}
    so_ids = {p.sales_order_id for p in orders.values() if p.sales_order_id}
    sales = {s.id: s for s in db.query(SalesOrder).filter(SalesOrder.id.in_(so_ids)).all()} if so_ids else {}
    ids = {r.model_id for r in rows}
    models = {m.id: m for m in db.query(Model).options(selectinload(Model.images)).filter(Model.id.in_(ids)).all()} if ids else {}
    output = []
    for row in rows:
        po = orders[row.production_order_id]
        so = sales.get(po.sales_order_id)
        model = models.get(row.model_id)
        # Match the work-order source; fallback also handles orders whose print
        # instructions live on the production order rather than the sales order.
        attachments = (so.printing_attachments if so else None) or po.printing_attachments
        artwork = _image_attachment(attachments) or model_print_image_url(model)
        output.append({"production_order_id": po.id, "order_no": po.order_no or po.production_no,
                       "production_batch_id": row.production_batch_id, "model_code": model.code if model else None,
                       "batch_label": batch_names.get(row.production_batch_id),
                       "model_image_url": model_preview_image_url(model), "print_image_url": artwork,
                       "bundles": int(row.bundles), "pieces": int(row.pieces), "waiting_since": row.waiting_since,
                       "deadline": row.deadline})
    return {"totals": totals, "rows": output, "total": total_groups, "offset": offset, "limit": limit,
            "has_more": offset + len(rows) < total_groups, "updated_at": datetime.now(timezone.utc)}


def warehouse_board(db, start: date, end: date, *, stock_kind: str = "ALL"):
    lower, upper = period_bounds(start, end)
    remaining = Package.total_quantity - Package.dispatched_quantity
    # Count physical warehouse receipts once per package, including partial
    # dispatch remainders. Packed-but-unreceived goods belong to Packaging.
    stock = db.query(Package).filter(Package.status.in_(("received_in_storage", "reserved")), remaining > 0)
    shipped = db.query(ShipmentPackage).join(Shipment).join(Package).filter(
        Shipment.deleted_at.is_(None), Shipment.status.in_(("shipped", "delivered")),
        Shipment.shipped_at >= lower, Shipment.shipped_at < upper)
    if stock_kind != "ALL":
        stock = stock.filter(Package.stock_kind == stock_kind)
        shipped = shipped.filter(Package.stock_kind == stock_kind)
    packs, pieces, models = stock.with_entities(func.count(Package.id), func.coalesce(func.sum(remaining), 0),
                                               func.count(func.distinct(Package.model_id))).one()
    shipments, shipped_packs, shipped_pieces = shipped.with_entities(
        func.count(func.distinct(Shipment.id)), func.count(ShipmentPackage.id),
        func.coalesce(func.sum(ShipmentPackage.quantity), 0)).one()
    ranking = shipped.with_entities(Package.model_id, func.sum(ShipmentPackage.quantity).label("pieces")).group_by(
        Package.model_id).order_by(func.sum(ShipmentPackage.quantity).desc(), Package.model_id).limit(12).all()
    model_ids = {r.model_id for r in ranking if r.model_id}
    model_map = {m.id: m for m in db.query(Model).options(selectinload(Model.images)).filter(Model.id.in_(model_ids)).all()} if model_ids else {}
    hot = []
    for row in ranking:
        model = model_map.get(row.model_id)
        hot.append({"model_id": row.model_id, "model_code": model.code if model else None,
                    "model_image_url": model_preview_image_url(model), "shipped_pieces": int(row.pieces)})
    return {"inventory_packages": int(packs), "inventory_pieces": int(pieces), "inventory_models": int(models),
            "shipment_count": int(shipments), "shipped_packages": int(shipped_packs), "shipped_pieces": int(shipped_pieces),
            "hot_products": hot, "start": start, "end": end, "stock_kind": stock_kind,
            "timezone": str(BUSINESS_TZ), "updated_at": datetime.now(timezone.utc)}
