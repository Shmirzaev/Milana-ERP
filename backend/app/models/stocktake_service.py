"""Physical counts record evidence only; never change package or stock state."""

import csv
import hashlib
import io
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import load_only

from app.libs.dto.inventory.warehouse_stocktake_input import (
    CreateCount, DeleteCounts, DeleteScans, ScanCount,
)
from app.models.audit_service import log_action
from app.schemas import FinishedGoodsStock, Model, Package, PackageItem, User
from app.schemas.inventory.stocktake import WarehouseStocktake, WarehouseStocktakeRow
from app.models.package_identity_service import resolve_warehouse_package

STORAGE_STATUSES = ("received_in_storage", "reserved", "damaged")

# Detail and export read a count's evidence and the live package state that evidence is
# compared against. At READ COMMITTED a scan committed between those two statements is
# visible to one and not the other, so a single row can show pre-scan evidence beside
# post-scan current state. Both reads therefore run in one MVCC snapshot.
DETAIL_ISOLATION = "REPEATABLE READ"
# Rows are walked in bounded batches so detail and export never hold a whole count.
EXPORT_BATCH_SIZE = 500


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
    rows = query.all()
    dispatched = {p.id: p.dispatched_quantities or {} for p, *_ in rows}
    snapshots = {
        p.id: {
            "package_no": p.package_no,
            "barcode": p.barcode,
            "model_code": code,
            "model_name": name,
            "color": p.color,
            "quantity": p.total_quantity - p.dispatched_quantity,
            "available": int(available or 0),
            "reserved": int(reserved or 0),
            "status": p.status,
            "warehouse_id": p.warehouse_id,
            "location": " / ".join(x for x in (p.storage_cell, p.storage_shelf) if x),
        }
        for p, code, name, available, reserved in rows
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
                "size": item.size, "quantity": item.quantity - dispatched[item.package_id].get(str(item.id), 0),
            })
    return snapshots


def resolve_package(db, code):
    return resolve_warehouse_package(db, code)


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


# ===== Counts =====
def get_count(db, count_id, *, lock=False):
    query = db.query(WarehouseStocktake).filter(WarehouseStocktake.id == count_id)
    if lock:
        query = query.with_for_update()
    count = query.first()
    if not count:
        raise HTTPException(404, "Inventory count not found")
    if lock and count.completed_at:
        raise HTTPException(409, "This inventory count is completed")
    return count


def count_info(count):
    def utc(value):
        return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value

    return {
        "id": count.id,
        "title": count.title,
        "created_at": utc(count.created_at),
        "completed_at": utc(count.completed_at),
        "created_by": count.created_by,
    }


@contextmanager
def consistent_read_snapshot(db):
    """Run a count's read in one MVCC snapshot on PostgreSQL.

    The session may already have autobegun a transaction while resolving the caller, so
    that transaction is discarded first: `SET TRANSACTION` is only accepted as the first
    statement of a transaction. Both endpoints are read-only, so discarding an in-flight
    read cannot lose work. SQLite has no snapshot isolation, so it is left alone.
    """
    if db.bind is None or db.bind.dialect.name != "postgresql":
        yield
        return
    db.rollback()
    db.execute(text(f"SET TRANSACTION ISOLATION LEVEL {DETAIL_ISOLATION} READ ONLY"))
    try:
        yield
    finally:
        # Release the snapshot; the session is closed by the request dependency.
        db.rollback()


def _batch_payloads(db, count, rows):
    """Materialize one batch of rows exactly as `results()` does for the whole count."""
    if not rows:
        return []
    if count.completed_at:
        current = {row.package_id: row.final_snapshot for row in rows if row.package_id}
    else:
        current = package_snapshots(db, [row.package_id for row in rows if row.package_id])
    return [row_payload(row, current) for row in rows]


def iter_result_batches(db, count, batch_size=EXPORT_BATCH_SIZE, *, newest_scanned_first=False):
    """Yield the count's row payloads in bounded batches.

    Rows come in id order, which is the order `results()` produced and therefore the order
    every caller depended on. The scanned view is newest-first, and its sort key is a
    column, so the ordering is expressed in SQL and walked with a keyset on
    `(scanned_at, id)` rather than by buffering the whole count to sort it in Python.
    """
    if not newest_scanned_first:
        last_id = 0
        while True:
            rows = (
                db.query(WarehouseStocktakeRow)
                .filter(WarehouseStocktakeRow.stocktake_id == count.id, WarehouseStocktakeRow.id > last_id)
                .order_by(WarehouseStocktakeRow.id)
                .limit(batch_size)
                .all()
            )
            if not rows:
                return
            last_id = rows[-1].id
            batch = _batch_payloads(db, count, rows)
            if batch:
                yield batch
        return

    last_scanned_at = None
    last_id = 0
    while True:
        query = db.query(WarehouseStocktakeRow).filter(
            WarehouseStocktakeRow.stocktake_id == count.id,
            WarehouseStocktakeRow.scanned_at.is_not(None),
        )
        if last_scanned_at is not None:
            query = query.filter(
                (WarehouseStocktakeRow.scanned_at < last_scanned_at)
                | (
                    (WarehouseStocktakeRow.scanned_at == last_scanned_at)
                    & (WarehouseStocktakeRow.id < last_id)
                )
            )
        rows = query.order_by(
            WarehouseStocktakeRow.scanned_at.desc(), WarehouseStocktakeRow.id.desc()
        ).limit(batch_size).all()
        if not rows:
            return
        last_scanned_at, last_id = rows[-1].scanned_at, rows[-1].id
        batch = _batch_payloads(db, count, rows)
        if batch:
            yield batch


def results(db, count):
    """Every row of a count, in id order. Prefer `iter_result_batches` for large counts."""
    rows = (
        db.query(WarehouseStocktakeRow)
        .filter_by(stocktake_id=count.id)
        .order_by(
            WarehouseStocktakeRow.id,
        )
        .all()
    )
    current = (
        {row.package_id: row.final_snapshot for row in rows if row.package_id}
        if count.completed_at
        else package_snapshots(db, [row.package_id for row in rows if row.package_id])
    )
    return [row_payload(row, current) for row in rows]


def _matches_search(row, needle):
    return not needle or needle in " ".join(
        str(v or "")
        for v in [
            row["scan_code"],
            *row["snapshot"].values(),
            *(row["scan_snapshot"] or {}).values(),
        ]
    ).casefold()


def _empty_summary():
    summary = {key: 0 for key in ("found", "missing", "unknown", "unexpected", "ambiguous")}
    summary["expected"] = 0
    summary["changed"] = 0
    return summary


def _scan_totals(seen_scans, scanned_rows):
    """`scan_summary` over a streamed count.

    `scan_summary` counts `scanned` across every row it is given but derives the package
    totals from the first recorded row per package, so it is handed that deduplicated set
    and the raw scanned-row count is restored afterwards.
    """
    totals = scan_summary(list(seen_scans.values()))
    totals["scanned"] = scanned_rows
    return totals


def detail_rows(db, count, *, result="all", q="", offset=0, limit=100):
    """One bounded page of a count's rows plus the exact whole-count summary.

    The summary always describes the whole count, not the filtered page, so it is
    accumulated while streaming rather than recomputed from the returned window. The
    total is the number of rows matching the filter across the count, so the page is
    chosen while streaming instead of after a full hydration.
    """
    needle = q.strip().casefold()
    summary = _empty_summary()
    # The package totals need the first recorded row per scanned package, so only those
    # are kept; `scanned` itself is a plain row count.
    seen_scans = {}
    scanned_rows = 0
    matched = 0
    page = []

    def _observe(row):
        nonlocal scanned_rows
        summary[row["result"]] = summary.get(row["result"], 0) + 1
        summary["expected"] += row["expected"]
        summary["changed"] += bool(row["changed"])
        if row["scanned_at"] is not None:
            scanned_rows += 1
            if row["package_id"] is not None:
                seen_scans.setdefault(row["package_id"], row)

    # The summary describes the whole count, so it is always accumulated in id order --
    # the order `results()` produced, which decides which row represents a package
    # scanned more than once.
    for batch in iter_result_batches(db, count):
        for row in batch:
            _observe(row)

    # The page is a separate walk in the caller's order, so `changed`/search filtering
    # still happens before the offset/limit window, as it did when the whole count was
    # filtered and sorted in memory first.
    for batch in iter_result_batches(db, count, newest_scanned_first=result == "scanned"):
        for row in batch:
            if not _row_selected(row, result, needle):
                continue
            if matched >= offset and len(page) < limit:
                page.append(row)
            matched += 1

    summary.update(_scan_totals(seen_scans, scanned_rows))
    return {"summary": summary, "total": matched, "rows": page}


def _row_selected(row, result, needle):
    if result == "all":
        pass
    elif result == "scanned":
        if row["scanned_at"] is None:
            return False
    elif result == "changed":
        if not row["changed"]:
            return False
    elif row["result"] != result:
        return False
    return _matches_search(row, needle)


def list_counts(db, offset: int = 0) -> dict:
    query = db.query(WarehouseStocktake)
    counts = query.order_by(WarehouseStocktake.id.desc()).offset(offset).limit(50).all()
    scans = {count.id: [] for count in counts}
    if scans:
        recorded = db.query(WarehouseStocktakeRow).options(load_only(
            WarehouseStocktakeRow.stocktake_id, WarehouseStocktakeRow.package_id, WarehouseStocktakeRow.expected,
            WarehouseStocktakeRow.snapshot, WarehouseStocktakeRow.scan_snapshot, WarehouseStocktakeRow.scanned_at,
        )).filter(WarehouseStocktakeRow.stocktake_id.in_(scans), WarehouseStocktakeRow.scanned_at.is_not(None)).all()
        for row in recorded:
            scans[row.stocktake_id].append(scan_fields(row))
    return {
        "total": query.count(),
        "items": [{**count_info(c), "summary": scan_summary(scans[c.id])} for c in counts],
    }


def create_count(db, body: CreateCount, current: User) -> dict:
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "Count name is required")
    key = str(body.request_key)
    existing = db.query(WarehouseStocktake).filter_by(request_key=key).first()
    if existing:
        return count_info(existing)
    count = WarehouseStocktake(request_key=key, title=title, created_by=current.id)
    db.add(count)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.query(WarehouseStocktake).filter_by(request_key=key).first()
        if existing:
            return count_info(existing)
        raise
    for pid, snapshot in package_snapshots(db, expected_only=True).items():
        db.add(
            WarehouseStocktakeRow(
                stocktake_id=count.id,
                identity=f"package:{pid}",
                package_id=pid,
                expected=True,
                category="expected",
                snapshot=snapshot,
            )
        )
    log_action(db, current, "start", "WarehouseStocktake", count.id, new_value={"title": title})
    db.commit()
    return count_info(count)


def delete_counts(db, body: DeleteCounts, current: User) -> dict:
    ids = sorted(set(body.count_ids))
    # Use the same parent locks as scanning/completion; a bulk request is atomic.
    counts = db.query(WarehouseStocktake).filter(WarehouseStocktake.id.in_(ids)).order_by(
        WarehouseStocktake.id
    ).with_for_update().all()
    if len(counts) != len(ids):
        raise HTTPException(404, "Inventory count not found")
    for count in counts:
        rows = db.query(WarehouseStocktakeRow).filter_by(stocktake_id=count.id)
        log_action(db, current, "delete", "WarehouseStocktake", count.id, old_value={
            **count_info(count), "rows": rows.count(),
            "recorded_scans": rows.filter(WarehouseStocktakeRow.scanned_at.is_not(None)).count(),
        })
        rows.delete(synchronize_session=False)
        db.delete(count)
    db.commit()
    return {"deleted": ids}


def count_detail(db, count_id: int, *, result="all", q="", offset=0, limit=100) -> dict:
    count = get_count(db, count_id)
    with consistent_read_snapshot(db):
        # The header is read inside the snapshot too: after it closes the session rolls
        # back and `count` would be refreshed outside the snapshot the rows came from.
        return {**count_info(count), **detail_rows(db, count, result=result, q=q, offset=offset, limit=limit)}


def scan_count(db, count_id: int, body: ScanCount, current: User) -> dict:
    get_count(db, count_id, lock=True)  # Serialize scans, undo and completion across scanners.
    code = body.code.strip()
    if not code:
        raise HTTPException(422, "Scan a package label")
    pid, ambiguous = resolve_package(db, code)
    if pid is not None:
        # Package edits and shipment transitions lock/update this same row. Hold
        # it while reading parent quantity and item sizes into one scan record.
        package = db.query(Package).filter(Package.id == pid).with_for_update().first()
        if package is None:  # Deleted after resolution; do not count a stale ID.
            pid = None
    identity = f"package:{pid}" if pid else "code:" + hashlib.sha256(code.encode()).hexdigest()
    row = db.query(WarehouseStocktakeRow).filter_by(stocktake_id=count_id, identity=identity).first()
    duplicate = bool(row and row.scanned_at)
    observed = package_snapshots(db, [pid], include_items=True).get(pid, {}) if pid else {}
    if not row:
        snapshot = {key: value for key, value in observed.items() if key != "items"}
        row = WarehouseStocktakeRow(
            stocktake_id=count_id,
            identity=identity,
            package_id=pid,
            expected=False,
            category="ambiguous" if ambiguous else "unexpected" if pid else "unknown",
            snapshot=snapshot,
        )
        db.add(row)
    if not duplicate:
        row.scan_snapshot = observed if pid else None
        row.scan_code = code
        row.scanned_at = datetime.now(timezone.utc)
        row.scanned_by = current.id
        db.flush()
        log_action(
            db,
            current,
            "scan",
            "WarehouseStocktake",
            count_id,
            new_value={"row_id": row.id, "code": code, "package_id": pid, "category": row.category},
        )
    else:
        log_action(
            db, current, "scan_duplicate", "WarehouseStocktake", count_id,
            new_value={"row_id": row.id, "code": code, "package_id": pid, "category": row.category},
        )
    db.commit()
    return {"duplicate": duplicate, "row": row_payload(row, package_snapshots(db, [pid]) if pid else {})}


def remove_recorded_scan(db, current, count_id, row):
    log_action(
        db,
        current,
        "undo_scan",
        "WarehouseStocktake",
        count_id,
        old_value={"row_id": row.id, "code": row.scan_code, "package_id": row.package_id},
    )
    if row.expected:
        row.scan_code = row.scanned_at = row.scanned_by = None
        row.scan_snapshot = None
    else:
        db.delete(row)


def delete_scans(db, count_id: int, body: DeleteScans, current: User) -> dict:
    get_count(db, count_id, lock=True)
    ids = sorted(set(body.row_ids))
    rows = db.query(WarehouseStocktakeRow).filter(
        WarehouseStocktakeRow.stocktake_id == count_id,
        WarehouseStocktakeRow.id.in_(ids),
        WarehouseStocktakeRow.scanned_at.is_not(None),
    ).order_by(WarehouseStocktakeRow.id).all()
    # Validate the entire selection before undoing anything, under the count lock.
    if len(rows) != len(ids):
        raise HTTPException(404, "Recorded scan not found; refresh the count and select again")
    for row in rows:
        remove_recorded_scan(db, current, count_id, row)
    db.commit()
    return {"deleted": ids}


def undo_scan(db, count_id: int, row_id: int, current: User) -> dict:
    get_count(db, count_id, lock=True)
    row = db.query(WarehouseStocktakeRow).filter_by(stocktake_id=count_id, id=row_id).first()
    if not row or not row.scanned_at:
        raise HTTPException(404, "Recorded scan not found")
    remove_recorded_scan(db, current, count_id, row)
    db.commit()
    return {"ok": True}


def complete_count(db, count_id: int, current: User) -> dict:
    # Lock also on repeat completion; retry returns the already frozen report.
    count = db.query(WarehouseStocktake).filter_by(id=count_id).with_for_update().first()
    if not count:
        raise HTTPException(404, "Inventory count not found")
    if not count.completed_at:
        rows = db.query(WarehouseStocktakeRow).filter_by(stocktake_id=count_id).all()
        snapshots = package_snapshots(db, [row.package_id for row in rows if row.package_id])
        for row in rows:
            row.final_snapshot = snapshots.get(row.package_id, {})
        count.completed_at = datetime.now(timezone.utc)
        log_action(db, current, "complete", "WarehouseStocktake", count_id)
        db.commit()
    return count_info(count)


EXPORT_HEADERS = [
        "Count",
        "Completed",
        "Result",
        "Changed during count",
        "Package",
        "Barcode",
        "Model",
        "Color",
        "Expected pieces",
        "Available",
        "Reserved",
        "Location",
        "Scan",
        "Scanned at",
        "Current status",
        "Current pieces",
        "Current available",
        "Current reserved",
        "Current location",
        "Scanned pieces",
        "Scan quantity basis",
        "Scanned model / color / size breakdown",
        "Scanned packages total",
        "Scanned pieces total",
        "Count-start fallback packages",
        "Scanned packages without quantity evidence",
        "Unknown labels total",
        "Ambiguous labels total",
        "Row type",
]


def export_count(db, count_id: int) -> str:
    """Render one count as CSV. The caller wraps the text in the download response."""
    count = get_count(db, count_id)
    stream = io.StringIO()
    writer = csv.writer(stream)
    headers = EXPORT_HEADERS
    writer.writerow(headers)

    def write_safe(values):
        writer.writerow([
            "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else v
            for v in values
        ])

    # Rows are written as they are read, so a large count is never held in memory. The
    # footer only needs the first recorded row per scanned package plus two counters, so
    # those are accumulated instead of every payload.
    seen_scans = {}
    scanned_rows = 0
    unknown_total = 0
    ambiguous_total = 0
    with consistent_read_snapshot(db):
        for batch in iter_result_batches(db, count):
            for row in batch:
                if row["scanned_at"] is not None:
                    scanned_rows += 1
                    if row["package_id"] is not None:
                        seen_scans.setdefault(row["package_id"], row)
                unknown_total += row["result"] == "unknown"
                ambiguous_total += row["result"] == "ambiguous"
                s = row["snapshot"]
                now = row["current"] or {}
                observed = row["scan_snapshot"] or (s if row["scanned_at"] and row["package_id"] else {})
                items = observed.get("items") or ([observed] if observed else [])
                breakdown = "; ".join(
                    " / ".join(str(item.get(key) or "") for key in ("model_code", "model_name", "color", "size"))
                    + f" : {item.get('quantity', '')}"
                    for item in items
                )
                values = [
                    count.title,
                    count.completed_at or "",
                    row["result"],
                    row["changed"],
                    s.get("package_no"),
                    s.get("barcode"),
                    s.get("model_code"),
                    s.get("color"),
                    s.get("quantity"),
                    s.get("available"),
                    s.get("reserved"),
                    s.get("location"),
                    row["scan_code"],
                    row["scanned_at"],
                    now.get("status"),
                    now.get("quantity"),
                    now.get("available"),
                    now.get("reserved"),
                    now.get("location"),
                    row["scanned_pieces"],
                    row["scan_evidence_source"] if row["scanned_at"] else "",
                    breakdown,
                    "", "", "", "", "", "", "package",
                ]
                write_safe(values)
    totals = _scan_totals(seen_scans, scanned_rows)
    footer = {"Count": count.title, "Completed": count.completed_at or "", "Result": "TOTAL", "Row type": "totals",
              "Scanned packages total": totals["scanned_packages"], "Scanned pieces total": totals["scanned_pieces"],
              "Count-start fallback packages": totals["estimated_packages"],
              "Scanned packages without quantity evidence": totals["unquantified_packages"],
              "Unknown labels total": unknown_total,
              "Ambiguous labels total": ambiguous_total}
    write_safe([footer.get(header, "") for header in headers])
    return stream.getvalue()
