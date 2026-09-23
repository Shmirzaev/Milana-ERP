"""Explicit physical receipts; label operations never mint stock."""
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text, or_

from app.models import (
    FinishedGoodsStock, Model, Package, PackageBatchAllocation, PackageItem, PackageScanLog,
    Warehouse, ManualPackageReceipt, PackagePrintRun, PackagePrintRunMember, PackageBarcodeAlias,
)
from app.services.audit import log_action
from app.services.barcode import generate_barcode_value, save_qr_image
from app.services.idempotency import request_fingerprint
from app.services.numbering import _next, next_package_nos
from app.services.packages import (
    _require_warehouse_package, _warehouse_source_types, receive_at_storage, validate_storage_location,
    _packaging_record_totals_by_batch, _existing_package_totals_by_batch,
)


_CANCELLED_REQUEST_RESPONSE = {"_package_workflow_status": "cancelled"}


def cancelled_request_response():
    return dict(_CANCELLED_REQUEST_RESPONSE)


def is_cancelled_request(response) -> bool:
    return response == _CANCELLED_REQUEST_RESPONSE


def lock_request(db, user_id, operation, key):
    # Same-user retries serialize before reading the idempotency record.
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(1297107634, hashtext(:key))"),
                   {"key": f"{user_id}:{operation}:{key}"})


def contents(pkg, *, items=None, batch_allocations=None):
    package_items = pkg.items if items is None else items
    allocations = pkg.batch_allocations if batch_allocations is None else batch_allocations
    return {
        "package_no": pkg.package_no, "barcode": pkg.barcode,
        "model_id": pkg.model_id, "color": pkg.color,
        "production_order_id": pkg.production_order_id, "production_batch_id": pkg.production_batch_id,
        "manual_receipt_id": pkg.manual_receipt_id, "legacy_receipt_id": pkg.legacy_receipt_id,
        "batch_allocations": sorted([{"production_batch_id": a.production_batch_id, "quantity": a.quantity}
                                     for a in allocations], key=lambda a: a["production_batch_id"]),
        "quantity": pkg.total_quantity, "weight_kg": float(pkg.weight_kg) if pkg.weight_kg is not None else None,
        "items": sorted([{"model_id": item.model_id, "color": item.color, "size": item.size,
                          "quantity": item.quantity} for item in package_items], key=lambda x: (x["model_id"], x["color"], x["size"])),
    }


def _package_children(db, packages):
    package_ids = [int(package.id) for package in packages]
    items_by_package = {package_id: [] for package_id in package_ids}
    allocations_by_package = {package_id: [] for package_id in package_ids}
    for offset in range(0, len(package_ids), 400):
        chunk = package_ids[offset:offset + 400]
        for item in db.query(PackageItem).filter(PackageItem.package_id.in_(chunk)).all():
            items_by_package[int(item.package_id)].append(item)
        for allocation in db.query(PackageBatchAllocation).filter(
            PackageBatchAllocation.package_id.in_(chunk),
        ).all():
            allocations_by_package[int(allocation.package_id)].append(allocation)
    return items_by_package, allocations_by_package


def create_run(db, current, packages, *, received=False):
    if not packages or len({p.id for p in packages}) != len(packages):
        raise HTTPException(400, "Select distinct packages")
    owners = {p.packaging_department_code for p in packages}
    if len(owners) != 1:
        raise HTTPException(400, "A print run must belong to one packaging department")
    if db.query(PackagePrintRunMember.id).filter(PackagePrintRunMember.package_id.in_([p.id for p in packages])).first():
        raise HTTPException(409, "Package already belongs to a print run; reprint its existing run")
    source_types = _warehouse_source_types(db, packages)
    checked_orders = set()
    for pkg in packages:
        if pkg.production_order_id and source_types.get(int(pkg.production_order_id)) == "usluga":
            raise HTTPException(400, "Usluga packages are handed directly to the customer and cannot enter warehouse flow")
        if pkg.production_order_id and pkg.production_order_id not in checked_orders:
            checked_orders.add(pkg.production_order_id)
            packed = _packaging_record_totals_by_batch(db, pkg.production_order_id)
            consumed = _existing_package_totals_by_batch(db, pkg.production_order_id)
            if not packed or any(qty > packed.get(batch, 0) for batch, qty in consumed.items()):
                raise HTTPException(409, "Package needs validated Packaging output before entering a receiving print run")
        if pkg.status != ("received_in_storage" if received else "packed"):
            raise HTTPException(409, "Only unreceived packed packages can enter a new receiving print run")
    run = PackagePrintRun(run_no=_next(db, PackagePrintRun, "run_no", "PRN"),
                          code=f"PACKRUN:{uuid4().hex}", packaging_department_code=next(iter(owners)),
                          created_by=current.id, package_ids=[p.id for p in packages])
    if received:
        run.received_by = current.id
        run.received_at = datetime.now(timezone.utc)
    db.add(run)
    db.flush()
    items_by_package, allocations_by_package = _package_children(db, packages)
    for pkg in packages:
        db.add(PackagePrintRunMember(
            run_id=run.id,
            package_id=pkg.id,
            snapshot=contents(
                pkg,
                items=items_by_package[int(pkg.id)],
                batch_allocations=allocations_by_package[int(pkg.id)],
            ),
        ))
    db.flush()
    log_action(db, current, "create_print_run", "PackagePrintRun", run.id,
               new_value={"run_no": run.run_no, "package_ids": [p.id for p in packages]})
    return run


def run_members(db, run, *, members=None):
    if members is None:
        members = db.query(PackagePrintRunMember).filter(PackagePrintRunMember.run_id == run.id).order_by(PackagePrintRunMember.id).all()
    if [m.package_id for m in members] != run.package_ids:
        raise HTTPException(409, "Print run membership does not match its immutable manifest")
    return members


def require_active_run(run):
    if run.deleted_at is not None:
        raise HTTPException(410, "This mistaken manual receipt was deleted")


def active_run_members(db, run, *, members=None):
    deleted = set(run.deleted_package_ids or [])
    return [member for member in run_members(db, run, members=members) if member.package_id not in deleted]


def require_active_label(db, package_id):
    require_active_labels(db, [package_id])


def require_active_labels(db, package_ids):
    ordered_ids = [int(package_id) for package_id in package_ids]
    members_by_package = {}
    for offset in range(0, len(ordered_ids), 400):
        chunk = ordered_ids[offset:offset + 400]
        members_by_package.update({
            int(member.package_id): member
            for member in db.query(PackagePrintRunMember).filter(
                PackagePrintRunMember.package_id.in_(chunk),
            ).all()
        })
    run_ids = sorted({int(member.run_id) for member in members_by_package.values()})
    runs_by_id = {}
    for offset in range(0, len(run_ids), 400):
        chunk = run_ids[offset:offset + 400]
        runs_by_id.update({
            int(run.id): run
            for run in db.query(PackagePrintRun).filter(PackagePrintRun.id.in_(chunk)).all()
        })
    deleted_package_ids_by_run = {
        run_id: set(run.deleted_package_ids or [])
        for run_id, run in runs_by_id.items()
    }
    for package_id in ordered_ids:
        member = members_by_package.get(package_id)
        if member:
            run = runs_by_id.get(int(member.run_id))
            if run is None or run.deleted_at is not None or package_id in deleted_package_ids_by_run[int(run.id)]:
                raise HTTPException(410, "This manual package label was deleted")


def run_payload(db, run, *, members=None):
    require_active_run(run)
    members = active_run_members(db, run, members=members)
    return {"id": run.id, "run_no": run.run_no, "code": run.code,
            "created_at": run.created_at.isoformat(), "received_at": run.received_at.isoformat() if run.received_at else None,
            "manual_receipt": bool(members) and all(m.snapshot.get("manual_receipt_id") for m in members),
            "count": len(members), "quantity": sum(m.snapshot["quantity"] for m in members),
            "package_ids": [m.package_id for m in members],
            "packages": [{"id": m.package_id, **m.snapshot} for m in members]}


def run_list_payload(db, runs):
    """Load members together for the route's bounded 100-run page."""
    if not runs:
        return []
    grouped = {run.id: [] for run in runs}
    members = db.query(PackagePrintRunMember).filter(
        PackagePrintRunMember.run_id.in_(grouped),
    ).order_by(PackagePrintRunMember.id).all()
    for member in members:
        grouped[member.run_id].append(member)
    # Pass all members, including deleted identities, through manifest validation.
    return [run_payload(db, run, members=grouped[run.id]) for run in runs]


def manual_receipt(db, current, payload):
    model = db.get(Model, payload.model_id)
    if not model or model.catalog_scope != "standard" or model.status != "approved":
        raise HTTPException(400, "Select an approved standard model/variant")
    if model.code.startswith("LEGACY-"):
        raise HTTPException(400, "Select a catalog model, not a legacy warehouse identity")
    if payload.warehouse_id and not db.get(Warehouse, payload.warehouse_id):
        raise HTTPException(404, "Warehouse not found")
    cell, shelf = validate_storage_location(payload.storage_cell, payload.storage_shelf, require_cell=False)
    configured = [s.size for s in model.sizes]
    if payload.pack_quantities is not None:
        # Total-only receipts do not invent a per-size distribution.
        size_label = configured[0] if len(configured) == 1 else "Mixed"
        pack_items = [[{"size": size_label, "quantity": qty}] for qty in payload.pack_quantities]
    else:
        sizes = [row.size for row in payload.sizes]
        if len(set(sizes)) != len(sizes):
            raise HTTPException(400, "Each size must appear once")
        if not configured or not set(sizes).issubset(configured):
            raise HTTPException(400, "Use sizes configured on the selected model")
        pack_items = [[row.model_dump() for row in payload.sizes] for _ in range(payload.count)]
    quantities = [sum(row["quantity"] for row in items) for items in pack_items]
    if any(total > 10000 for total in quantities):
        raise HTTPException(400, "Package quantity exceeds 10000")
    weight = round(payload.weight_kg, 4)
    evidence = {**payload.model_dump(mode="json"), "weight_kg": weight, "model_code": model.code, "model_name": model.name,
                "configured_sizes": configured, "quantity_per_package": quantities[0] if len(set(quantities)) == 1 else None,
                "total_quantity": sum(quantities)}
    receipt = ManualPackageReceipt(receipt_no=_next(db, ManualPackageReceipt, "receipt_no", "WMR"),
                                   created_by=current.id, evidence=evidence, evidence_hash=request_fingerprint(evidence))
    db.add(receipt)
    db.flush()
    now = datetime.now(timezone.utc)
    packages = []
    package_numbers = next_package_nos(db, len(pack_items))
    for package_no, items, total in zip(package_numbers, pack_items, quantities):
        pkg = Package(package_no=package_no, barcode=generate_barcode_value("PKG"),
                      manual_receipt_id=receipt.id, model_id=model.id, color=payload.color,
                      brand_id=model.brand_id, collection_id=model.collection_id,
                      total_quantity=total, capacity=total, weight_kg=weight,
                      warehouse_id=payload.warehouse_id, storage_cell=cell, storage_shelf=shelf,
                      storage_placed_at=now if cell else None, packed_by=current.id,
                      received_by=current.id, received_at=now, status="received_in_storage",
                      packaging_department_code="PKG", notes=payload.reason)
        pkg.items = [PackageItem(model_id=model.id, color=payload.color, size=row["size"], quantity=row["quantity"]) for row in items]
        db.add(pkg)
        db.flush()
        pkg.qr_code_url = save_qr_image(f"PACKAGE:{pkg.package_no}|{pkg.barcode}", f"package_qr_{pkg.package_no}")
        for row in items:
            db.add(FinishedGoodsStock(package_id=pkg.id, model_id=model.id, color=payload.color,
                                     size=row["size"], quantity=row["quantity"], available_qty=row["quantity"],
                                     warehouse_id=payload.warehouse_id, brand_id=model.brand_id,
                                     collection_id=model.collection_id))
        db.add(PackageScanLog(package_id=pkg.id, scanned_by=current.id, scan_type="manual_receipt"))
        packages.append(pkg)
    run = create_run(db, current, packages, received=True)
    log_action(db, current, "manual_receipt", "ManualPackageReceipt", receipt.id,
               new_value={"receipt_no": receipt.receipt_no, "evidence": evidence,
                          "package_ids": [p.id for p in packages], "print_run_id": run.id})
    return {"receipt_id": receipt.id, "receipt_no": receipt.receipt_no, "print_run": run_payload(db, run)}


def resolve_run(db, code):
    from app.api.routes.packages import _package_lookup_candidates
    code = code.strip()
    if code.startswith("PACKRUN:"):
        return db.query(PackagePrintRun).filter(PackagePrintRun.code == code).first()
    candidates = _package_lookup_candidates(code)
    ids = {pid for (pid,) in db.query(Package.id).filter(or_(Package.barcode.in_(candidates), Package.package_no.in_(candidates))).all()}
    ids.update(pid for (pid,) in db.query(PackageBarcodeAlias.package_id).filter(PackageBarcodeAlias.code.in_(candidates)).all())
    if len(ids) > 1:
        raise HTTPException(409, "Ambiguous package code; scan the unique package QR")
    if not ids:
        raise HTTPException(404, "Package not found")
    require_active_label(db, next(iter(ids)))
    member = db.query(PackagePrintRunMember).filter(PackagePrintRunMember.package_id == next(iter(ids))).first()
    return db.get(PackagePrintRun, member.run_id) if member else None


def receive_run(db, current, payload):
    found = resolve_run(db, payload.code)
    run = db.query(PackagePrintRun).filter(PackagePrintRun.id == found.id).with_for_update().populate_existing().first() if found else None
    if not run:
        raise HTTPException(404, "Print run not found")
    require_active_run(run)
    # One persistent receipt per group; a retried scan returns that same receipt.
    if run.received_at:
        return run, []
    members = run_members(db, run)
    ids = [m.package_id for m in members]
    packages = db.query(Package).filter(Package.id.in_(ids)).order_by(Package.id).with_for_update().populate_existing().all()
    if len(packages) != len(members) or not packages:
        raise HTTPException(409, "Print run membership is incomplete")
    by_id = {p.id: p for p in packages}
    stocks_by_package = {package_id: [] for package_id in ids}
    stocks = (
        db.query(FinishedGoodsStock)
        .filter(FinishedGoodsStock.package_id.in_(ids))
        .order_by(FinishedGoodsStock.package_id, FinishedGoodsStock.id)
        .with_for_update()
        .all()
    )
    for stock in stocks:
        stocks_by_package[stock.package_id].append(stock)
    for member in members:
        pkg = by_id[member.package_id]
        if contents(pkg) != member.snapshot:
            raise HTTPException(409, f"Package {pkg.package_no} changed since printing; review required")
        if pkg.status != "packed":
            raise HTTPException(409, f"Package {pkg.package_no} is already received or unavailable")
        _require_warehouse_package(db, pkg)
        if not (pkg.production_order_id or pkg.manual_receipt_id or pkg.legacy_receipt_id):
            raise HTTPException(409, "Package has no source evidence")
        # Existing stock must already be complete; receiving must never create it.
        package_stocks = stocks_by_package[pkg.id]
        expected = {}
        actual = {}
        for item in pkg.items:
            key = (item.model_id, item.color, item.size)
            expected[key] = expected.get(key, 0) + item.quantity
        for stock in package_stocks:
            key = (stock.model_id, stock.color, stock.size)
            actual[key] = actual.get(key, 0) + stock.quantity
        if (actual != expected or sum(s.quantity for s in package_stocks) != pkg.total_quantity
                or any(s.reserved_qty or s.sold_qty or s.available_qty != s.quantity or s.status != "available" for s in package_stocks)):
            raise HTTPException(409, f"Package {pkg.package_no} stock evidence is inconsistent")
    if payload.warehouse_id and not db.get(Warehouse, payload.warehouse_id):
        raise HTTPException(404, "Warehouse not found")
    for pkg in packages:
        receive_at_storage(db, pkg, payload.warehouse_id, current.id,
                           storage_cell=payload.storage_cell, storage_shelf=payload.storage_shelf, print_run_id=run.id)
    run.received_at = datetime.now(timezone.utc)
    run.received_by = current.id
    run.receipt_location = payload.model_dump(exclude={"code"})
    log_action(db, current, "receive_print_run", "PackagePrintRun", run.id,
               new_value={"run_no": run.run_no, "package_ids": ids, **run.receipt_location})
    return run, packages


def delete_manual_run(db, current, run, package_ids=None):
    """Delete selected unused packs, or retire shipped labels with history intact."""
    from app.models import Shipment, ShipmentPackage, ShipmentScanLog, StockReservation
    from app.models.shipment_review import PackageQuantityAdjustment
    from app.models.stocktake import WarehouseStocktakeRow
    requested = set(run.package_ids if package_ids is None else package_ids)
    if not requested or not requested.issubset(set(run.package_ids)):
        raise HTTPException(422, "Select packages from this print run")
    if run.deleted_at is not None:
        return {"deleted_count": len(requested)}
    members = run_members(db, run)
    if any(not m.snapshot.get("manual_receipt_id") for m in members):
        raise HTTPException(409, "Only manually created warehouse packs can be deleted here")
    ids = sorted(requested - set(run.deleted_package_ids or []))
    if not ids:
        return {"deleted_count": len(requested)}
    packages = db.query(Package).filter(Package.id.in_(ids)).order_by(Package.id).with_for_update().populate_existing().all()
    if len(packages) != len(ids) or any(not p.manual_receipt_id for p in packages):
        raise HTTPException(409, "Manual package evidence is incomplete")
    shipped = []
    unused = []
    for pkg in packages:
        if pkg.status in {"shipped", "delivered"}:
            links = db.query(Shipment).join(ShipmentPackage, ShipmentPackage.shipment_id == Shipment.id).filter(ShipmentPackage.package_id == pkg.id).all()
            if not links or any(sh.status not in {"shipped", "delivered"} for sh in links):
                raise HTTPException(409, "Package shipment evidence is incomplete")
            shipped.append(pkg)
        else:
            unused.append(pkg)
    unused_ids = [p.id for p in unused]
    if any(p.status != "received_in_storage" or p.sales_order_id or p.quantity_shortfall for p in unused):
        raise HTTPException(409, "Reserved or adjusted packages cannot be deleted")
    for cls in (ShipmentPackage, ShipmentScanLog, StockReservation, PackageQuantityAdjustment, WarehouseStocktakeRow):
        if unused_ids and db.query(cls).filter(cls.package_id.in_(unused_ids)).first():
            raise HTTPException(409, "Package is linked to a pending shipment, reservation, correction or inventory count")
    stocks = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(unused_ids)).with_for_update().all()
    if stocks and db.query(StockReservation).filter(StockReservation.finished_goods_stock_id.in_([s.id for s in stocks])).first():
        raise HTTPException(409, "Package stock is reserved")
    for pkg in unused:
        rows = [row for row in stocks if row.package_id == pkg.id]
        if (not rows or sum(row.quantity for row in rows) != pkg.total_quantity or
                any(row.status != "available" or row.available_qty != row.quantity or row.reserved_qty or row.sold_qty or row.sales_order_id for row in rows)):
            raise HTTPException(409, "Package stock has been used or changed")
    log_action(db, current, "delete_manual_packages", "PackagePrintRun", run.id,
               old_value={"run_no": run.run_no, "packages": [contents(p) for p in packages]},
               new_value={"removed_stock_package_ids": unused_ids, "retired_shipped_label_ids": [p.id for p in shipped]})
    from app.services.numbering import retire_label_numbers
    retire_label_numbers(db, [p.package_no for p in packages], run.run_no)
    run.deleted_package_ids = sorted(set(run.deleted_package_ids or []) | set(ids))
    if set(run.deleted_package_ids) == set(run.package_ids):
        run.deleted_at = datetime.now(timezone.utc)
    db.flush()
    for row in stocks:
        db.delete(row)
    for pkg in unused:
        db.delete(pkg)
    db.flush()
    return {"deleted_count": len(requested)}
