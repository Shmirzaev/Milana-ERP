"""Explicit physical receipts; label operations never mint stock."""
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text, or_

from app.models import (
    FinishedGoodsStock, Model, Package, PackageItem, PackageScanLog,
    Warehouse, ManualPackageReceipt, PackagePrintRun, PackagePrintRunMember, PackageBarcodeAlias,
)
from app.services.audit import log_action
from app.services.barcode import generate_barcode_value, save_qr_image
from app.services.idempotency import request_fingerprint
from app.services.numbering import _next, next_package_no
from app.services.packages import (
    _require_warehouse_package, receive_at_storage, validate_storage_location,
    _packaging_record_totals_by_batch, _existing_package_totals_by_batch,
)


def lock_request(db, user_id, operation, key):
    # Same-user retries serialize before reading the idempotency record.
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(1297107634, hashtext(:key))"),
                   {"key": f"{user_id}:{operation}:{key}"})


def contents(pkg):
    return {
        "package_no": pkg.package_no, "barcode": pkg.barcode,
        "model_id": pkg.model_id, "color": pkg.color,
        "production_order_id": pkg.production_order_id, "production_batch_id": pkg.production_batch_id,
        "manual_receipt_id": pkg.manual_receipt_id, "legacy_receipt_id": pkg.legacy_receipt_id,
        "batch_allocations": sorted([{"production_batch_id": a.production_batch_id, "quantity": a.quantity}
                                     for a in pkg.batch_allocations], key=lambda a: a["production_batch_id"]),
        "quantity": pkg.total_quantity, "weight_kg": float(pkg.weight_kg) if pkg.weight_kg is not None else None,
        "items": sorted([{"model_id": item.model_id, "color": item.color, "size": item.size,
                          "quantity": item.quantity} for item in pkg.items], key=lambda x: (x["model_id"], x["color"], x["size"])),
    }


def create_run(db, current, packages, *, received=False):
    if not packages or len({p.id for p in packages}) != len(packages):
        raise HTTPException(400, "Select distinct packages")
    owners = {p.packaging_department_code for p in packages}
    if len(owners) != 1:
        raise HTTPException(400, "A print run must belong to one packaging department")
    if db.query(PackagePrintRunMember.id).filter(PackagePrintRunMember.package_id.in_([p.id for p in packages])).first():
        raise HTTPException(409, "Package already belongs to a print run; reprint its existing run")
    checked_orders = set()
    for pkg in packages:
        _require_warehouse_package(db, pkg)
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
    for pkg in packages:
        db.add(PackagePrintRunMember(run_id=run.id, package_id=pkg.id, snapshot=contents(pkg)))
    db.flush()
    log_action(db, current, "create_print_run", "PackagePrintRun", run.id,
               new_value={"run_no": run.run_no, "package_ids": [p.id for p in packages]})
    return run


def run_members(db, run):
    members = db.query(PackagePrintRunMember).filter(PackagePrintRunMember.run_id == run.id).order_by(PackagePrintRunMember.id).all()
    if [m.package_id for m in members] != run.package_ids:
        raise HTTPException(409, "Print run membership does not match its immutable manifest")
    return members


def run_payload(db, run):
    members = run_members(db, run)
    return {"id": run.id, "run_no": run.run_no, "code": run.code,
            "created_at": run.created_at.isoformat(), "received_at": run.received_at.isoformat() if run.received_at else None,
            "count": len(members), "quantity": sum(m.snapshot["quantity"] for m in members),
            "package_ids": [m.package_id for m in members],
            "packages": [{"id": m.package_id, **m.snapshot} for m in members]}


def manual_receipt(db, current, payload):
    model = db.get(Model, payload.model_id)
    if not model or model.catalog_scope != "standard" or model.status != "approved":
        raise HTTPException(400, "Select an approved standard model/variant")
    if model.code.startswith("LEGACY-"):
        raise HTTPException(400, "Select a catalog model, not a legacy warehouse identity")
    if payload.warehouse_id and not db.get(Warehouse, payload.warehouse_id):
        raise HTTPException(404, "Warehouse not found")
    cell, shelf = validate_storage_location(payload.storage_cell, payload.storage_shelf, require_cell=False)
    sizes = [row.size for row in payload.sizes]
    if len(set(sizes)) != len(sizes):
        raise HTTPException(400, "Each size must appear once")
    configured = {s.size for s in model.sizes}
    if not configured or not set(sizes).issubset(configured):
        raise HTTPException(400, "Use sizes configured on the selected model")
    total = sum(row.quantity for row in payload.sizes)
    if total > 10000:
        raise HTTPException(400, "Package quantity exceeds 10000")
    weight = round(payload.weight_kg, 4)
    evidence = {**payload.model_dump(mode="json"), "weight_kg": weight, "model_code": model.code, "model_name": model.name,
                "quantity_per_package": total, "total_quantity": total * payload.count}
    receipt = ManualPackageReceipt(receipt_no=_next(db, ManualPackageReceipt, "receipt_no", "WMR"),
                                   created_by=current.id, evidence=evidence, evidence_hash=request_fingerprint(evidence))
    db.add(receipt)
    db.flush()
    now = datetime.now(timezone.utc)
    packages = []
    for _ in range(payload.count):
        pkg = Package(package_no=next_package_no(db), barcode=generate_barcode_value("PKG"),
                      manual_receipt_id=receipt.id, model_id=model.id, color=payload.color,
                      brand_id=model.brand_id, collection_id=model.collection_id,
                      total_quantity=total, capacity=total, weight_kg=weight,
                      warehouse_id=payload.warehouse_id, storage_cell=cell, storage_shelf=shelf,
                      storage_placed_at=now if cell else None, packed_by=current.id,
                      received_by=current.id, received_at=now, status="received_in_storage",
                      packaging_department_code="PKG", notes=payload.reason)
        pkg.items = [PackageItem(model_id=model.id, color=payload.color, size=row.size, quantity=row.quantity) for row in payload.sizes]
        db.add(pkg)
        db.flush()
        pkg.qr_code_url = save_qr_image(f"PACKAGE:{pkg.package_no}|{pkg.barcode}", f"package_qr_{pkg.package_no}")
        for row in payload.sizes:
            db.add(FinishedGoodsStock(package_id=pkg.id, model_id=model.id, color=payload.color,
                                     size=row.size, quantity=row.quantity, available_qty=row.quantity,
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
    member = db.query(PackagePrintRunMember).filter(PackagePrintRunMember.package_id == next(iter(ids))).first()
    return db.get(PackagePrintRun, member.run_id) if member else None


def receive_run(db, current, payload):
    found = resolve_run(db, payload.code)
    run = db.query(PackagePrintRun).filter(PackagePrintRun.id == found.id).with_for_update().populate_existing().first() if found else None
    if not run:
        raise HTTPException(404, "Print run not found")
    # One persistent receipt per group; a retried scan returns that same receipt.
    if run.received_at:
        return run, []
    members = run_members(db, run)
    ids = [m.package_id for m in members]
    packages = db.query(Package).filter(Package.id.in_(ids)).order_by(Package.id).with_for_update().populate_existing().all()
    if len(packages) != len(members) or not packages:
        raise HTTPException(409, "Print run membership is incomplete")
    by_id = {p.id: p for p in packages}
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
        stocks = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id == pkg.id).order_by(FinishedGoodsStock.id).with_for_update().all()
        expected = {}
        actual = {}
        for item in pkg.items:
            key = (item.model_id, item.color, item.size)
            expected[key] = expected.get(key, 0) + item.quantity
        for stock in stocks:
            key = (stock.model_id, stock.color, stock.size)
            actual[key] = actual.get(key, 0) + stock.quantity
        if (actual != expected or sum(s.quantity for s in stocks) != pkg.total_quantity
                or any(s.reserved_qty or s.sold_qty or s.available_qty != s.quantity or s.status != "available" for s in stocks)):
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
