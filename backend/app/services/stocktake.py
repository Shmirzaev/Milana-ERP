"""Physical counts record evidence only; never change package or stock state."""

from datetime import timezone

from sqlalchemy import String, and_, case, cast, func, or_
from sqlalchemy.orm import load_only

from app.models import FinishedGoodsStock, Model, Package, PackageBarcodeAlias, PackageItem
from app.models.stocktake import WarehouseStocktakeRow


_STOCKTAKE_PAGE_CHUNK_SIZE = 400
_STOCKTAKE_SNAPSHOT_KEYS = (
    "package_no", "barcode", "model_code", "model_name", "color", "quantity",
    "available", "reserved", "status", "warehouse_id", "location", "items",
)

STORAGE_STATUSES = ("received_in_storage", "reserved", "damaged")


def package_snapshots(db, package_ids=None, *, expected_only=False, include_items=False):
    requested_ids = (
        None
        if package_ids is None
        else sorted({int(package_id) for package_id in package_ids if package_id is not None})
    )
    balance_query = (
        db.query(
            FinishedGoodsStock.package_id.label("package_id"),
            func.sum(FinishedGoodsStock.available_qty).label("available"),
            func.sum(FinishedGoodsStock.reserved_qty).label("reserved"),
        )
    )
    if requested_ids is not None:
        balance_query = balance_query.filter(FinishedGoodsStock.package_id.in_(requested_ids))
    balance = balance_query.group_by(FinishedGoodsStock.package_id).subquery()
    query = (
        db.query(Package, Model.code, Model.name, balance.c.available, balance.c.reserved)
        .options(load_only(
            Package.id,
            Package.package_no,
            Package.barcode,
            Package.color,
            Package.total_quantity,
            Package.status,
            Package.warehouse_id,
            Package.storage_cell,
            Package.storage_shelf,
        ))
        .outerjoin(
            Model,
            Model.id == Package.model_id,
        )
        .outerjoin(balance, balance.c.package_id == Package.id)
    )
    if expected_only:
        query = query.filter(Package.status.in_(STORAGE_STATUSES))
    if requested_ids is not None:
        query = query.filter(Package.id.in_(requested_ids))
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


def stocktake_summary(db, count):
    expected_found = and_(WarehouseStocktakeRow.expected.is_(True), WarehouseStocktakeRow.scanned_at.is_not(None))
    expected_missing = and_(WarehouseStocktakeRow.expected.is_(True), WarehouseStocktakeRow.scanned_at.is_(None))
    unexpected = WarehouseStocktakeRow.expected.is_(False)
    scanned_row = WarehouseStocktakeRow.scanned_at.is_not(None)
    aggregate = db.query(
        func.coalesce(func.sum(case((expected_found, 1), else_=0)), 0),
        func.coalesce(func.sum(case((expected_missing, 1), else_=0)), 0),
        func.coalesce(func.sum(case((and_(unexpected, WarehouseStocktakeRow.category == "unknown"), 1), else_=0)), 0),
        func.coalesce(func.sum(case((and_(unexpected, WarehouseStocktakeRow.category == "unexpected"), 1), else_=0)), 0),
        func.coalesce(func.sum(case((and_(unexpected, WarehouseStocktakeRow.category == "ambiguous"), 1), else_=0)), 0),
        func.coalesce(func.sum(case((WarehouseStocktakeRow.expected.is_(True), 1), else_=0)), 0),
        func.coalesce(func.sum(case((scanned_row, 1), else_=0)), 0),
    ).filter(WarehouseStocktakeRow.stocktake_id == count.id).one()

    scanned = int(aggregate[6] or 0)
    scanned_packages = 0
    scanned_pieces = 0
    estimated_packages = 0
    unquantified_packages = 0
    first_scanned_ids = db.query(
        WarehouseStocktakeRow.package_id.label("package_id"),
        func.min(WarehouseStocktakeRow.id).label("row_id"),
    ).filter(
        WarehouseStocktakeRow.stocktake_id == count.id,
        scanned_row,
        WarehouseStocktakeRow.package_id.is_not(None),
    ).group_by(WarehouseStocktakeRow.package_id).subquery()
    scanned_rows = db.query(
        WarehouseStocktakeRow.package_id,
        WarehouseStocktakeRow.scanned_at,
        WarehouseStocktakeRow.scan_snapshot,
        WarehouseStocktakeRow.snapshot,
        WarehouseStocktakeRow.expected,
    ).join(
        first_scanned_ids,
        first_scanned_ids.c.row_id == WarehouseStocktakeRow.id,
    ).order_by(WarehouseStocktakeRow.id.asc()).yield_per(_STOCKTAKE_PAGE_CHUNK_SIZE)
    for row in scanned_rows:
        fields = scan_fields(row)
        scanned_packages += 1
        scanned_pieces += fields["scanned_pieces"] or 0
        estimated_packages += fields["scan_evidence_source"] == "count_start"
        unquantified_packages += fields["scanned_pieces"] is None

    changed = 0
    if count.completed_at:
        completed_current: dict[int, dict | None] = {}
        completed_rows = db.query(
            WarehouseStocktakeRow.package_id,
            WarehouseStocktakeRow.final_snapshot,
        ).filter(
            WarehouseStocktakeRow.stocktake_id == count.id,
            WarehouseStocktakeRow.package_id.is_not(None),
        ).order_by(WarehouseStocktakeRow.id.asc()).yield_per(_STOCKTAKE_PAGE_CHUNK_SIZE)
        for row in completed_rows:
            completed_current[int(row.package_id)] = row.final_snapshot
        snapshot_rows = db.query(
            WarehouseStocktakeRow.package_id,
            WarehouseStocktakeRow.snapshot,
        ).filter(
            WarehouseStocktakeRow.stocktake_id == count.id,
            WarehouseStocktakeRow.package_id.is_not(None),
        ).yield_per(_STOCKTAKE_PAGE_CHUNK_SIZE)
        changed = sum(completed_current[int(row.package_id)] != row.snapshot for row in snapshot_rows)
    else:
        last_row_id = 0
        while True:
            snapshot_rows = db.query(
                WarehouseStocktakeRow.id,
                WarehouseStocktakeRow.package_id,
                WarehouseStocktakeRow.snapshot,
            ).filter(
                WarehouseStocktakeRow.stocktake_id == count.id,
                WarehouseStocktakeRow.package_id.is_not(None),
                WarehouseStocktakeRow.id > last_row_id,
            ).order_by(WarehouseStocktakeRow.id.asc()).limit(_STOCKTAKE_PAGE_CHUNK_SIZE).all()
            if not snapshot_rows:
                break
            current = package_snapshots(db, [int(row.package_id) for row in snapshot_rows])
            changed += sum(current.get(int(row.package_id), {}) != row.snapshot for row in snapshot_rows)
            last_row_id = int(snapshot_rows[-1].id)

    return {
        "found": int(aggregate[0] or 0),
        "missing": int(aggregate[1] or 0),
        "unknown": int(aggregate[2] or 0),
        "unexpected": int(aggregate[3] or 0),
        "ambiguous": int(aggregate[4] or 0),
        "expected": int(aggregate[5] or 0),
        "changed": int(changed),
        "scanned": scanned,
        "scanned_packages": scanned_packages,
        "scanned_pieces": scanned_pieces,
        "estimated_packages": estimated_packages,
        "unquantified_packages": unquantified_packages,
    }


def _stocktake_search_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def stocktake_detail_page(
    db,
    count,
    *,
    result: str,
    offset: int,
    limit: int,
    search: str = "",
) -> tuple[int, list[dict]]:
    query = db.query(WarehouseStocktakeRow).options(load_only(
        WarehouseStocktakeRow.id,
        WarehouseStocktakeRow.package_id,
        WarehouseStocktakeRow.scanned_at,
        WarehouseStocktakeRow.scan_snapshot,
        WarehouseStocktakeRow.snapshot,
        WarehouseStocktakeRow.expected,
        WarehouseStocktakeRow.category,
        WarehouseStocktakeRow.scan_code,
        WarehouseStocktakeRow.scanned_by,
    )).filter(WarehouseStocktakeRow.stocktake_id == count.id)
    if search:
        pattern = _stocktake_search_pattern(search)
        value_matches = [WarehouseStocktakeRow.scan_code.ilike(pattern, escape="\\")]
        for key in _STOCKTAKE_SNAPSHOT_KEYS:
            value_matches.extend((
                cast(WarehouseStocktakeRow.snapshot[key], String).ilike(pattern, escape="\\"),
                cast(WarehouseStocktakeRow.scan_snapshot[key], String).ilike(pattern, escape="\\"),
            ))
        query = query.filter(or_(*value_matches))
    if result == "scanned":
        query = query.filter(WarehouseStocktakeRow.scanned_at.is_not(None))
    elif result == "found":
        query = query.filter(
            WarehouseStocktakeRow.expected.is_(True),
            WarehouseStocktakeRow.scanned_at.is_not(None),
        )
    elif result == "missing":
        query = query.filter(
            WarehouseStocktakeRow.expected.is_(True),
            WarehouseStocktakeRow.scanned_at.is_(None),
        )
    elif result in {"unknown", "unexpected", "ambiguous"}:
        query = query.filter(
            WarehouseStocktakeRow.expected.is_(False),
            WarehouseStocktakeRow.category == result,
        )
    elif result != "all":
        raise ValueError(f"Unsupported SQL stocktake result filter: {result}")

    total = query.count()
    if result == "scanned":
        query = query.order_by(
            WarehouseStocktakeRow.scanned_at.desc(),
            WarehouseStocktakeRow.id.desc(),
        )
    else:
        query = query.order_by(WarehouseStocktakeRow.id.asc())
    rows = query.offset(offset).limit(limit).all()
    package_ids = sorted({int(row.package_id) for row in rows if row.package_id})
    if count.completed_at:
        completed_rows = db.query(
            WarehouseStocktakeRow.package_id,
            WarehouseStocktakeRow.final_snapshot,
        ).filter(
            WarehouseStocktakeRow.stocktake_id == count.id,
            WarehouseStocktakeRow.package_id.in_(package_ids),
        ).order_by(WarehouseStocktakeRow.id.asc()).all()
        current = {int(package_id): final_snapshot for package_id, final_snapshot in completed_rows}
    else:
        current = package_snapshots(db, package_ids)
    return total, [row_payload(row, current) for row in rows]
