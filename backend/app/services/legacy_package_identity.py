"""Guarded restoration of consolidated physical sticker identities.

Dry-run first. Only immutable, approved sticker receipts authorize stock;
shipment/reservation history is never inferred or reversed.
"""

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json

from sqlalchemy import text

from app.models import (
    FinishedGoodsStock, LegacyStockReceipt, Package, PackageBarcodeAlias,
    PackageBatchAllocation, PackageChangeRequest, PackageItem, PackageScanLog,
    ShipmentPackage, ShipmentScanLog, StockReservation,
)
from app.models.stocktake import WarehouseStocktake, WarehouseStocktakeRow
from app.services.audit import log_action
from app.services.package_identity import physical_legacy_qr
from app.services.stocktake import package_snapshots


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def record(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def build_plan(db):
    aliases = db.query(PackageBarcodeAlias).filter(
        PackageBarcodeAlias.code_type == "legacy_package_qr",
    ).order_by(PackageBarcodeAlias.id).all()
    packages = {p.id: p for p in db.query(Package).all()}
    barcode_packages = {p.barcode: p for p in packages.values()}
    names = {p.package_no for p in packages.values()}
    candidates = [a for a in aliases if a.package_id in packages and a.code != packages[a.package_id].barcode]
    receipts = defaultdict(list)
    all_receipts = {r.id: r for r in db.query(LegacyStockReceipt).all()}
    for receipt in all_receipts.values():
        receipts[receipt.source_record_id].append(receipt)
    used_receipts = {p.legacy_receipt_id for p in packages.values() if p.legacy_receipt_id}
    stocks = defaultdict(list)
    for stock in db.query(FinishedGoodsStock).order_by(FinishedGoodsStock.id).all():
        stocks[stock.package_id].append(stock)
    protected = set()
    for model in (ShipmentPackage, ShipmentScanLog, StockReservation, PackageBatchAllocation):
        protected.update(pid for (pid,) in db.query(model.package_id).distinct().all() if pid)
    protected.update(pid for (pid,) in db.query(PackageChangeRequest.package_id).filter(
        PackageChangeRequest.status == "pending",
    ).all())
    by_code = defaultdict(list)
    for alias in candidates:
        by_code[alias.code].append(alias)
    operations, excluded = [], []
    for code, group in sorted(by_code.items()):
        parent_ids = {a.package_id for a in group}
        parent = packages[group[0].package_id]
        source = receipts[code]
        target = barcode_packages.get(code)
        reason = None
        if not physical_legacy_qr(code):
            reason = "not_an_individual_sticker"
        elif len(source) != 1:
            reason = "missing_or_ambiguous_receipt"
        elif target and target.legacy_receipt_id == source[0].id:
            operations.append({"kind": "unlink", "code": code, "alias_ids": [a.id for a in group],
                               "target_id": target.id, "guard": digest([record(a) for a in group] + [record(target), record(source[0])])})
            continue
        elif target:
            reason = "barcode_receipt_conflict"
        elif len(parent_ids) != 1:
            reason = "multiple_parent_packages"
        elif source[0].id in used_receipts:
            reason = "receipt_already_linked"
        elif parent.status != "received_in_storage" or parent.id in protected:
            reason = "parent_has_downstream_history"
        elif not stocks[parent.id] or any(s.reserved_qty or s.sold_qty or s.quantity != s.available_qty for s in stocks[parent.id]):
            reason = "parent_has_committed_stock"
        elif sum(s.quantity for s in stocks[parent.id]) != parent.total_quantity or any(
            s.model_id != parent.model_id or s.warehouse_id != parent.warehouse_id or s.status != "available"
            for s in stocks[parent.id]
        ):
            reason = "inconsistent_parent_stock"
        else:
            receipt = source[0]
            payload = receipt.source_payload or {}
            parent_receipt = all_receipts.get(parent.legacy_receipt_id)
            parent_payload = parent_receipt.source_payload if parent_receipt else {}
            qty = payload.get("quantity")
            expected_name = "OLD-" + code.removeprefix("uzerp_ii_").replace("_", "-")
            if receipt.source_system != "UZERP_STICKER_PHOTO" or str(payload.get("review_status", "")).lower() != "approved":
                reason = "receipt_not_approved_sticker"
            elif payload.get("qr_code") != code or not payload.get("source_photo_sha256"):
                reason = "incomplete_receipt_evidence"
            elif not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0 or payload.get("quantity_defaulted"):
                reason = "unverified_quantity"
            elif any(not payload.get(key) or payload.get(key) != parent_payload.get(key) for key in ("model_number", "article")):
                reason = "receipt_model_mismatch"
            elif expected_name in names:
                reason = "package_number_conflict"
            elif len({(str(s.cost_per_piece), str(s.selling_price)) for s in stocks[parent.id]}) != 1:
                reason = "mixed_stock_prices"
            elif parent.model_id is None or parent.warehouse_id is None:
                reason = "missing_model_or_warehouse"
            else:
                operations.append({"kind": "restore", "code": code, "alias_ids": [a.id for a in group],
                                   "parent_id": parent.id, "receipt_id": receipt.id, "package_no": expected_name,
                                   "quantity": qty,
                                   "guard": digest([record(a) for a in group] + [record(parent), record(receipt)]
                                                   + [record(s) for s in stocks[parent.id]])})
        if reason:
            excluded.append({"code": code, "parent": parent.package_no, "reason": reason})
    body = {"operations": operations, "excluded": excluded}
    return {**body, "sha256": digest(body), "summary": {
        "candidate_codes": len(by_code), "restore_packages": sum(o["kind"] == "restore" for o in operations),
        "restore_pieces": sum(o.get("quantity", 0) for o in operations),
        "unlink_existing": sum(o["kind"] == "unlink" for o in operations), "excluded": len(excluded),
    }}


def apply_plan(db, expected_sha256, actor):
    # Block concurrent source, stock and shipment changes during the short repair
    # transaction. READ COMMITTED is required so the plan is read after the locks.
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SET LOCAL lock_timeout = '10s'"))
        db.execute(text("LOCK TABLE packages, legacy_stock_receipts, package_barcode_aliases, "
                        "package_items, finished_goods_stock, shipment_packages, shipment_scan_logs, "
                        "stock_reservations, package_batch_allocations, package_change_requests, "
                        "warehouse_stocktakes, warehouse_stocktake_rows IN SHARE ROW EXCLUSIVE MODE"))
    plan = build_plan(db)
    if plan["sha256"] != expected_sha256:
        raise ValueError("Reconciliation evidence changed; review a fresh dry run")
    operations = plan["operations"]
    created, targets = [], {}
    for operation in operations:
        if operation["kind"] == "unlink":
            targets[operation["code"]] = db.get(Package, operation["target_id"])
            continue
        parent = db.get(Package, operation["parent_id"])
        receipt = db.get(LegacyStockReceipt, operation["receipt_id"])
        payload = receipt.source_payload
        weight = payload.get("weight_kg")
        weight = Decimal(str(weight)) if weight is not None else None
        if weight is not None and (not weight.is_finite() or weight < 0):
            raise ValueError("Invalid receipt weight")
        package = Package(
            package_no=operation["package_no"], barcode=operation["code"], legacy_receipt_id=receipt.id,
            model_id=parent.model_id, brand_id=parent.brand_id, collection_id=parent.collection_id,
            color=parent.color, package_type="legacy_stock", total_quantity=operation["quantity"],
            capacity=operation["quantity"], weight_kg=weight, warehouse_id=parent.warehouse_id,
            status="received_in_storage", received_by=receipt.imported_by, received_at=receipt.imported_at,
            notes="Physical sticker restored from immutable receipt; size quantities require verification.",
        )
        db.add(package)
        created.append(package)
        targets[operation["code"]] = package
    db.flush()
    parent_for_code = {o["code"]: o.get("parent_id") for o in operations}
    for package in created:
        template = db.query(FinishedGoodsStock).filter_by(package_id=parent_for_code[package.barcode]).first()
        # The old sticker lists sizes but no quantities per size. Do not invent
        # equal splits; preserve its verified total as ASSORTED, like the import.
        db.add(PackageItem(package_id=package.id, model_id=package.model_id, color=package.color,
                           size="ASSORTED", quantity=package.total_quantity))
        db.add(FinishedGoodsStock(
            package_id=package.id, model_id=package.model_id, brand_id=package.brand_id,
            collection_id=package.collection_id, color=package.color, size="ASSORTED",
            quantity=package.total_quantity, available_qty=package.total_quantity, reserved_qty=0, sold_qty=0,
            cost_per_piece=template.cost_per_piece, selling_price=template.selling_price, warehouse_id=package.warehouse_id, status="available",
        ))
        db.add(PackageScanLog(package_id=package.id, scanned_by=actor.id,
                              scan_type="legacy_identity_restore", location="Receipt-backed reconciliation"))
    alias_ids = [aid for operation in operations for aid in operation["alias_ids"]]
    for index in range(0, len(alias_ids), 500):
        db.query(PackageBarcodeAlias).filter(PackageBarcodeAlias.id.in_(alias_ids[index:index + 500])).delete(synchronize_session=False)
    db.flush()
    corrected_scans = correct_open_scans(db, targets, actor)
    for package in created:
        total = sum(s.quantity for s in db.query(FinishedGoodsStock).filter_by(package_id=package.id))
        if total != package.total_quantity:
            raise ValueError("Restored stock total did not match receipt")
    log_action(db, actor, "restore_physical_qr", "LegacyStockReceipt", new_value={
        "plan_sha256": plan["sha256"], **plan["summary"], "corrected_open_scans": corrected_scans,
        "restored": [{"code": p.barcode, "package_id": p.id, "receipt_id": p.legacy_receipt_id,
                      "quantity": p.total_quantity} for p in created],
    })
    db.flush()
    return {"plan_sha256": plan["sha256"], **plan["summary"], "corrected_open_scans": corrected_scans}


def correct_open_scans(db, targets, actor):
    rows = db.query(WarehouseStocktakeRow).join(WarehouseStocktake).filter(
        WarehouseStocktake.completed_at.is_(None), WarehouseStocktakeRow.scanned_at.is_not(None),
    ).all()
    corrected = 0
    snapshots = package_snapshots(db, [p.id for p in targets.values()], include_items=True) if targets else {}
    for row in rows:
        target = targets.get(row.scan_code)
        if not target or row.package_id == target.id:
            continue
        replacement = db.query(WarehouseStocktakeRow).filter_by(
            stocktake_id=row.stocktake_id, identity=f"package:{target.id}",
        ).first()
        old = {"row_id": row.id, "package_id": row.package_id, "scan_code": row.scan_code,
               "scanned_at": row.scanned_at, "scan_snapshot": row.scan_snapshot}
        if replacement is None:
            replacement = WarehouseStocktakeRow(
                stocktake_id=row.stocktake_id, identity=f"package:{target.id}", package_id=target.id,
                expected=False, category="unexpected",
                snapshot={key: value for key, value in snapshots[target.id].items() if key != "items"},
            )
            db.add(replacement)
        if replacement.scanned_at is None:
            replacement.scan_code, replacement.scanned_at, replacement.scanned_by = row.scan_code, row.scanned_at, row.scanned_by
            replacement.scan_snapshot = snapshots[target.id]
        if row.expected:
            row.scan_code = row.scanned_at = row.scanned_by = row.scan_snapshot = None
        else:
            db.delete(row)
        db.flush()
        log_action(db, actor, "correct_scan_identity", "WarehouseStocktake", row.stocktake_id,
                   old_value=old, new_value={"row_id": replacement.id, "package_id": target.id,
                                            "code": replacement.scan_code, "corrected_at": datetime.now(timezone.utc)})
        db.flush()
        corrected += 1
    return corrected
