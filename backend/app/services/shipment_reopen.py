"""Reverse one complete dispatch without deleting its stock or audit evidence."""
from collections import defaultdict
from datetime import timezone
from hashlib import sha256

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.models import (FinishedGoodsStock, IdempotencyRecord, Invoice, Package, PackageItem,
                        PackageScanLog, Payment, SalesOrder, Shipment, ShipmentPackage,
                        ShipmentScanLog, StockReservation, User)
from app.schemas.shipment_review import ShipmentReopen
from app.services.audit import log_action
from app.services.packages import _sync_package_production
from app.services.shipment_review import locked_shipment


def _conflict(code: str):
    raise HTTPException(409, "shipment_reopen_" + code)


def reopen_shipment(db: Session, sid: int, payload: ShipmentReopen, user: User) -> Shipment:
    shipment = locked_shipment(db, sid)
    def utc(value):
        return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value
    if shipment.status not in {"shipped", "delivered"} or utc(shipment.shipped_at) != utc(payload.expected_shipped_at):
        _conflict("stale")
    if not payload.packages_returned or len(payload.reason.strip()) < 3:
        _conflict("confirmation")
    links = db.query(ShipmentPackage).filter_by(shipment_id=sid).order_by(ShipmentPackage.package_id).all()
    ids = [link.package_id for link in links]
    packages = db.query(Package).filter(Package.id.in_(ids)).order_by(Package.id).with_for_update().all()
    if not ids or len(packages) != len(ids):
        _conflict("stock")
    stocks = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(ids)).order_by(
        FinishedGoodsStock.id).with_for_update().all()
    reservations = db.query(StockReservation).filter(StockReservation.finished_goods_stock_id.in_(
        [row.id for row in stocks])).order_by(StockReservation.id).with_for_update().all()
    reserved = defaultdict(int)
    for row in reservations:
        if not shipment.sales_order_id or row.sales_order_id != shipment.sales_order_id:
            _conflict("stock")
        reserved[row.finished_goods_stock_id] += row.quantity
    # A package cannot be restored if another live dispatch also claims it.
    if db.query(ShipmentPackage.id).join(Shipment).filter(
            ShipmentPackage.package_id.in_(ids), Shipment.id != sid,
            Shipment.status != "cancelled", Shipment.deleted_at.is_(None)).first():
        _conflict("stock")
    quantities = {link.package_id: link.quantity for link in links}
    by_package = defaultdict(list)
    for row in stocks:
        by_package[row.package_id].append(row)
        if (row.quantity <= 0 or row.sold_qty != row.quantity or row.available_qty != 0
                or row.reserved_qty != 0 or reserved[row.id] > row.quantity):
            _conflict("stock")
    for package in packages:
        if (package.status not in {"shipped", "delivered"}
                or not (package.production_order_id or package.manual_receipt_id or package.legacy_receipt_id)
                or package.total_quantity != quantities[package.id]):
            _conflict("stock")
        expected = defaultdict(int)
        actual = defaultdict(int)
        for item in db.query(PackageItem).filter_by(package_id=package.id):
            expected[(item.model_id, item.color, item.size)] += item.quantity
        for stock in by_package[package.id]:
            actual[(stock.model_id, stock.color, stock.size)] += stock.quantity
        if expected != actual or sum(actual.values()) != package.total_quantity:
            _conflict("stock")
    manual = bool((shipment.dispatch_snapshot or {}).get("manual"))
    order = None
    invoices = []
    if shipment.sales_order_id:
        order = db.query(SalesOrder).filter_by(id=shipment.sales_order_id).with_for_update().one()
        # Order-level invoices cannot safely be split without an explicit financial reconciliation.
        if db.query(Shipment.id).filter(Shipment.sales_order_id == order.id, Shipment.id != sid,
                                       Shipment.status != "cancelled").first():
            _conflict("finance")
        if manual and (order.notes != f"Manual shipment {shipment.shipment_no}" or reservations):
            _conflict("finance")
        invoices = db.query(Invoice).filter_by(sales_order_id=order.id).order_by(Invoice.id).with_for_update().all()
        for invoice in invoices:
            if (invoice.status not in {"unpaid", "void", "cancelled"} or invoice.external_id
                    or invoice.external_source or db.query(Payment.id).filter_by(invoice_id=invoice.id).first()):
                _conflict("finance")
    before = jsonable_encoder({
        "status": shipment.status, "shipped_at": shipment.shipped_at, "delivered_at": shipment.delivered_at,
        "dispatch_snapshot": shipment.dispatch_snapshot, "sales_order_id": shipment.sales_order_id,
        "order": {"id": order.id, "status": order.status, "total_amount": str(order.total_amount)} if order else None,
        "invoices": [{"id": i.id, "status": i.status, "amount": str(i.amount)} for i in invoices],
        "packages": [{"id": p.id, "status": p.status, "shipped_at": p.shipped_at} for p in packages],
        "stocks": [{"id": s.id, "quantity": s.quantity, "sold_qty": s.sold_qty} for s in stocks],
    })
    for stock in stocks:
        stock.sold_qty = 0
        stock.reserved_qty = reserved[stock.id]
        stock.available_qty = stock.quantity - stock.reserved_qty
        stock.status = "reserved" if stock.reserved_qty else "available"
    for package in packages:
        package.status = "reserved" if any(reserved[s.id] for s in by_package[package.id]) else "received_in_storage"
        package.shipped_at = None
        db.add(PackageScanLog(package_id=package.id, scanned_by=user.id, scan_type="returned"))
        # Preserve the original scans, but invalidate them for the next dispatch.
        db.add(ShipmentScanLog(shipment_id=sid, package_id=package.id, scanned_code=package.barcode,
                              scan_result="detached", message=payload.reason.strip(), scanned_by=user.id))
    for invoice in invoices:
        invoice.status = "void"
        invoice.amount = 0
    if order:
        if manual:
            order.status = "cancelled"
            order.total_amount = 0
            shipment.sales_order_id = None
        else:
            order.status = "ready_to_ship"
    shipment.status = "created"
    shipment.shipped_at = None
    shipment.delivered_at = None
    shipment.dispatch_snapshot = {"manual": True} if manual else None
    # Old retries must fail instead of reporting a dispatch that has been reversed.
    for record in db.query(IdempotencyRecord).filter(IdempotencyRecord.scope.like("shipments.%")):
        response = record.response_json or {}
        if (response.get("shipment_id") == sid or response.get("id") == sid
                or (record.scope == "shipments.scan-package" and response.get("package_id") in ids)):
            record.request_hash = sha256(("shipment-reopened:" + record.request_hash).encode()).hexdigest()
    db.flush()
    for production_id in {p.production_order_id for p in packages if p.production_order_id}:
        _sync_package_production(db, production_id)
    log_action(db, user, "reopen_shipment", "Shipment", sid, old_value=before,
               new_value={"status": "created", "reason": payload.reason.strip(), "packages_returned": True,
                          "pieces_restored": sum(s.quantity for s in stocks), "rescan_required": True})
    db.flush()
    return shipment
