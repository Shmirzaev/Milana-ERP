"""Offline, fingerprint-bound cleanup of explicitly reviewed manual shipments.

Dry-run by default. Apply only after a verified PostgreSQL backup. Existing audit,
receipt and package scan evidence remains; never resets sequences or creates stock.
"""
import argparse
import hashlib
import json
from decimal import Decimal

from sqlalchemy import inspect, text
from app.db.session import SessionLocal
from app.models import (Shipment, ShipmentPackage, ShipmentScanLog, Package,
                        FinishedGoodsStock, StockReservation, Invoice, Payment,
                        SalesOrder, IdempotencyRecord, PackageScanLog)
from app.models.shipment_review import PackageQuantityAdjustment
from app.services.audit import log_action


def rows_json(rows):
    return [{column.key: getattr(row, column.key) for column in inspect(type(row)).columns} for row in rows]


def prepare(db, ids):
    shipments = db.query(Shipment).filter(Shipment.id.in_(ids)).order_by(Shipment.id).with_for_update(of=Shipment).all()
    if [row.id for row in shipments] != sorted(ids):
        raise ValueError("Reviewed shipment selection changed")
    if any(not (row.dispatch_snapshot or {}).get("manual") or row.status not in {"created", "draft", "shipped"} for row in shipments):
        raise ValueError("Only reviewed open/shipped manual shipments are supported")
    links = db.query(ShipmentPackage).filter(ShipmentPackage.shipment_id.in_(ids)).order_by(ShipmentPackage.id).with_for_update().all()
    pids = sorted({row.package_id for row in links})
    if len(pids) != len(links) or db.query(ShipmentPackage.id).filter(ShipmentPackage.package_id.in_(pids), ~ShipmentPackage.shipment_id.in_(ids)).first():
        raise ValueError("Package is linked outside the selection")
    if db.query(PackageQuantityAdjustment.id).filter(PackageQuantityAdjustment.shipment_id.in_(ids)).first():
        raise ValueError("Immutable quantity adjustment requires separate reconciliation")
    packages = db.query(Package).filter(Package.id.in_(pids)).order_by(Package.id).with_for_update(of=Package).all()
    stocks = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(pids)).order_by(FinishedGoodsStock.id).with_for_update().all()
    if db.query(StockReservation.id).filter(StockReservation.package_id.in_(pids)).first():
        raise ValueError("A reserved package requires separate reconciliation")
    for package in packages:
        own = [row for row in stocks if row.package_id == package.id]
        if not package.legacy_receipt_id or package.sales_order_id or package.production_order_id:
            raise ValueError("Only the reviewed receipt-backed warehouse packages are supported")
        if not own or sum(row.quantity for row in own) != package.total_quantity:
            raise ValueError("Package and stock evidence do not balance")
        if package.status not in {"shipped", "received_in_storage"}:
            raise ValueError("Unexpected package state")
        for row in own:
            if row.reserved_qty or row.quantity != row.available_qty + row.sold_qty:
                raise ValueError("Stock quantities do not balance")
            if package.status == "shipped" and (row.available_qty or row.sold_qty != row.quantity):
                raise ValueError("Shipped stock was changed")
            if package.status == "received_in_storage" and row.sold_qty:
                raise ValueError("Available stock was changed")
    order_ids = sorted({row.sales_order_id for row in shipments if row.sales_order_id})
    orders = db.query(SalesOrder).filter(SalesOrder.id.in_(order_ids)).order_by(SalesOrder.id).with_for_update(of=SalesOrder).all()
    invoices = db.query(Invoice).filter(Invoice.sales_order_id.in_(order_ids)).order_by(Invoice.id).with_for_update().all()
    for order in orders:
        linked = [row for row in shipments if row.sales_order_id == order.id]
        if len(linked) != 1 or order.notes != f"Manual shipment {linked[0].shipment_no}" or order.status != "shipped":
            raise ValueError("Unexpected order linkage")
        if db.query(Shipment.id).filter(Shipment.sales_order_id == order.id, ~Shipment.id.in_(ids)).first():
            raise ValueError("Order has another shipment")
    for invoice in invoices:
        if invoice.status != "unpaid" or invoice.external_id or invoice.external_source or db.query(Payment.id).filter(Payment.invoice_id == invoice.id).first():
            raise ValueError("Posted or paid invoice requires separate reconciliation")
    scans = db.query(ShipmentScanLog).filter(ShipmentScanLog.shipment_id.in_(ids)).order_by(ShipmentScanLog.id).with_for_update().all()
    retries = [row for row in db.query(IdempotencyRecord).filter(IdempotencyRecord.scope.like("shipments.%")).order_by(IdempotencyRecord.id).with_for_update().all()
               if (row.response_json or {}).get("shipment_id", (row.response_json or {}).get("id")) in ids]
    snapshot = {"shipments": rows_json(shipments), "links": rows_json(links), "packages": rows_json(packages),
                "stocks": rows_json(stocks), "orders": rows_json(orders), "invoices": rows_json(invoices),
                "scans": rows_json(scans), "retries": rows_json(retries)}
    encoded = json.dumps(snapshot, sort_keys=True, default=str, separators=(",", ":"))
    fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
    return snapshot, fingerprint, (shipments, packages, stocks, orders, invoices, retries)


def apply_reviewed(db, ids, expected):
    snapshot, fingerprint, entities = prepare(db, ids)
    if fingerprint != expected:
        raise ValueError("Reviewed fingerprint changed; no mutation allowed")
    shipments, packages, stocks, orders, invoices, retries = entities
    returned = sum(row.sold_qty for row in stocks)
    for row in stocks:
        row.available_qty += row.sold_qty
        row.sold_qty = 0
        row.status = "available"
    for package in packages:
        if package.status == "shipped":
            package.status = "received_in_storage"
            package.shipped_at = None
            db.add(PackageScanLog(package_id=package.id, scan_type="returned", location="Shipment cleanup 2026-09-19"))
    # Retain accounting identities and the original amounts in audit. Zero the
    # void invoice because legacy totals sum invoices regardless of their status.
    for invoice in invoices:
        invoice.status = "void"
        invoice.amount = Decimal("0")
    for order in orders:
        order.status = "cancelled"
        order.total_amount = Decimal("0")
    for retry in retries:
        retry.request_hash = hashlib.sha256(("shipment-cleanup-20260919:" + retry.request_hash).encode()).hexdigest()
    db.query(ShipmentScanLog).filter(ShipmentScanLog.shipment_id.in_(ids)).delete(synchronize_session=False)
    db.query(ShipmentPackage).filter(ShipmentPackage.shipment_id.in_(ids)).delete(synchronize_session=False)
    db.query(Shipment).filter(Shipment.id.in_(ids)).delete(synchronize_session=False)
    summary = {"shipment_ids": ids, "shipments_deleted": len(shipments), "packages_available": len(packages),
               "pieces_restored": returned, "void_invoice_ids": [row.id for row in invoices],
               "cancelled_manual_order_ids": [row.id for row in orders], "invalidated_retries": len(retries)}
    log_action(db, None, "reviewed_shipment_cleanup_20260919", "Shipment", None, old_value=snapshot,
               new_value={**summary, "reason": "User requested removal of all existing shipments and return of scanned packages"})
    db.flush()
    if db.query(Shipment.id).filter(Shipment.id.in_(ids)).first():
        raise ValueError("Shipment deletion did not complete")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", required=True, help="Comma-separated, explicitly reviewed shipment IDs")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--fingerprint")
    args = parser.parse_args()
    ids = sorted({int(value) for value in args.ids.split(",")})
    with SessionLocal() as db:
        if db.bind.dialect.name == "postgresql":
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            db.execute(text("SET LOCAL statement_timeout = '30s'"))
            db.execute(text("LOCK TABLE shipments, shipment_packages, shipment_scan_logs, packages, finished_goods_stock, stock_reservations, invoices, payments, sales_orders, idempotency_records, audit_logs IN SHARE ROW EXCLUSIVE MODE"))
        if args.apply:
            if not args.fingerprint:
                parser.error("--apply requires the reviewed --fingerprint")
            result = apply_reviewed(db, ids, args.fingerprint)
            db.commit()
            print(json.dumps(result, sort_keys=True))
        else:
            snapshot, fingerprint, _ = prepare(db, ids)
            print(json.dumps({"fingerprint": fingerprint, "shipment_ids": ids, "package_ids": [row["id"] for row in snapshot["packages"]],
                              "pieces_to_restore": sum(row["sold_qty"] for row in snapshot["stocks"]),
                              "invoice_ids": [row["id"] for row in snapshot["invoices"]]}, sort_keys=True))
            db.rollback()


if __name__ == "__main__":
    main()
