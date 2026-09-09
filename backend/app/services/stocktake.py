"""Physical counts record evidence only; never change package or stock state."""

from datetime import timezone

from sqlalchemy import func, or_

from app.models import FinishedGoodsStock, Model, Package, PackageBarcodeAlias, PackageItem

STORAGE_STATUSES = ("received_in_storage", "reserved", "damaged")


def package_snapshots(db, package_ids=None, *, expected_only=False, include_items=False):
    balance = (
        db.query(
            FinishedGoodsStock.package_id.label("package_id"),
            func.sum(FinishedGoodsStock.available_qty).label("available"),
            func.sum(FinishedGoodsStock.reserved_qty).label("reserved"),
        )
        .group_by(FinishedGoodsStock.package_id)
        .subquery()
    )
    query = (
        db.query(Package, Model.code, Model.name, balance.c.available, balance.c.reserved)
        .outerjoin(
            Model,
            Model.id == Package.model_id,
        )
        .outerjoin(balance, balance.c.package_id == Package.id)
    )
    if expected_only:
        query = query.filter(Package.status.in_(STORAGE_STATUSES))
    if package_ids is not None:
        query = query.filter(Package.id.in_(package_ids))
    snapshots = {
        p.id: {
            "package_no": p.package_no,
            "barcode": p.barcode,
            "model_code": code,
            "model_name": name,
            "color": p.color,
            "quantity": p.total_quantity,
            "available": int(available or 0),
            "reserved": int(reserved or 0),
            "status": p.status,
            "warehouse_id": p.warehouse_id,
            "location": " / ".join(x for x in (p.storage_cell, p.storage_shelf) if x),
        }
        for p, code, name, available, reserved in query.all()
    }
    if include_items and snapshots:
        for snapshot in snapshots.values():
            snapshot["items"] = []
        items = db.query(PackageItem, Model.code, Model.name).outerjoin(Model, Model.id == PackageItem.model_id).filter(
            PackageItem.package_id.in_(snapshots)
        ).order_by(PackageItem.package_id, PackageItem.id).all()
        for item, code, name in items:
            snapshots[item.package_id]["items"].append({
                "model_code": code, "model_name": name, "color": item.color,
                "size": item.size, "quantity": item.quantity,
            })
    return snapshots


def resolve_package(db, code):
    # Resolve the whole QR consistently; conflicting tokens must never pick a random pack.
    payload = code.split(":", 1)[1] if code.upper().startswith("PACKAGE:") else code
    candidates = list(dict.fromkeys([code, *(part.strip() for part in payload.split("|") if part.strip())]))
    direct = {
        pid
        for (pid,) in db.query(Package.id)
        .filter(
            or_(Package.barcode.in_(candidates), Package.package_no.in_(candidates)),
        )
        .all()
    }
    aliases = {
        pid
        for (pid,) in db.query(PackageBarcodeAlias.package_id)
        .join(Package, Package.id == PackageBarcodeAlias.package_id)
        .filter(
            PackageBarcodeAlias.code.in_(candidates),
        )
        .all()
    }
    matches = direct | aliases
    return next(iter(matches)) if len(matches) == 1 else None, len(matches) > 1


def scan_fields(row):
    evidence = None
    source = "unresolved"
    if row.scanned_at and row.package_id is not None:
        if isinstance(row.scan_snapshot, dict):
            evidence, source = row.scan_snapshot, "scan"
        else:
            # Unexpected legacy rows were created at their first scan. Expected
            # rows only saved the earlier count-start state; disclose that basis.
            evidence, source = row.snapshot, "count_start" if row.expected else "scan"
    quantity = evidence.get("quantity") if isinstance(evidence, dict) else None
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0:
        quantity = None
    return {
        "package_id": row.package_id,
        "scanned_at": (
            row.scanned_at.replace(tzinfo=timezone.utc)
            if row.scanned_at and row.scanned_at.tzinfo is None else row.scanned_at
        ),
        "scan_snapshot": row.scan_snapshot if row.scanned_at else None,
        "scanned_pieces": quantity,
        "scan_evidence_source": source,
    }


def scan_summary(rows):
    scanned = [row for row in rows if row["scanned_at"] is not None]
    unique_packages = {}
    for row in scanned:
        if row["package_id"] is not None:
            unique_packages.setdefault(row["package_id"], row)
    resolved = list(unique_packages.values())
    return {
        "scanned": len(scanned),
        "scanned_packages": len(resolved),
        "scanned_pieces": sum(row["scanned_pieces"] or 0 for row in resolved),
        "estimated_packages": sum(row["scan_evidence_source"] == "count_start" for row in resolved),
        "unquantified_packages": sum(row["scanned_pieces"] is None for row in resolved),
    }


def row_payload(row, current):
    now = current.get(row.package_id, {}) if row.package_id else None
    changed = row.package_id is not None and now != row.snapshot
    result = ("found" if row.scanned_at else "missing") if row.expected else row.category
    return {
        **scan_fields(row),
        "id": row.id,
        "package_id": row.package_id,
        "expected": row.expected,
        "result": result,
        "snapshot": row.snapshot,
        "current": now,
        "changed": changed,
        "scan_code": row.scan_code,
        "scanned_by": row.scanned_by,
    }
