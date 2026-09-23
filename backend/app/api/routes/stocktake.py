import csv
import hashlib
import io
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import load_only

from app.core.deps import DbSession, require_permissions
from app.models import Package, User
from app.models.stocktake import WarehouseStocktake, WarehouseStocktakeRow
from app.services.audit import log_action
from app.services.stocktake import (
    package_snapshots,
    resolve_package,
    row_payload,
    scan_fields,
    scan_summary,
    stocktake_detail_page,
    stocktake_summary,
)

router = APIRouter(prefix="/warehouse-stocktakes", tags=["warehouse_stocktakes"])
access = require_permissions("storage.packages", "storage.shipment")
_STOCKTAKE_EXPORT_CHUNK_SIZE = 400
_DB_INTEGER_MAX = 2_147_483_647


class CreateCount(BaseModel):
    request_key: UUID
    title: str = Field(min_length=1, max_length=120)


class ScanCount(BaseModel):
    code: str = Field(min_length=1, max_length=512)


class StocktakeScanSummaryOut(BaseModel):
    scanned: int
    scanned_packages: int
    scanned_pieces: int
    estimated_packages: int
    unquantified_packages: int


class StocktakeListItemOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    completed_at: datetime | None
    created_by: int
    summary: StocktakeScanSummaryOut


class StocktakeListOut(BaseModel):
    total: int
    items: list[StocktakeListItemOut]


class StocktakePageOut(StocktakeListOut):
    page: int
    page_size: int
    has_more: bool


def get_count(db, count_id, *, lock=False):
    if count_id < 1 or count_id > _DB_INTEGER_MAX:
        raise HTTPException(404, "Inventory count not found")
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


def results(db, count):
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


@router.get("", response_model=StocktakePageOut | StocktakeListOut)
def list_counts(
    db: DbSession,
    _: User = Depends(access),
    offset: Annotated[int, Query(ge=0)] = 0,
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=500)] = None,
):
    query = db.query(WarehouseStocktake)
    paginated = page is not None or page_size is not None
    current_page = page or 1
    current_page_size = page_size or 50
    current_offset = (current_page - 1) * current_page_size if paginated else offset
    counts = (
        query.order_by(WarehouseStocktake.id.desc())
        .offset(current_offset)
        .limit(current_page_size if paginated else 50)
        .all()
    )
    scans = {count.id: [] for count in counts}
    if scans:
        recorded = db.query(WarehouseStocktakeRow).options(load_only(
            WarehouseStocktakeRow.stocktake_id, WarehouseStocktakeRow.package_id, WarehouseStocktakeRow.expected,
            WarehouseStocktakeRow.snapshot, WarehouseStocktakeRow.scan_snapshot, WarehouseStocktakeRow.scanned_at,
        )).filter(WarehouseStocktakeRow.stocktake_id.in_(scans), WarehouseStocktakeRow.scanned_at.is_not(None)).all()
        for row in recorded:
            scans[row.stocktake_id].append(scan_fields(row))
    result = {
        "total": query.count(),
        "items": [{**count_info(c), "summary": scan_summary(scans[c.id])} for c in counts],
    }
    if paginated:
        result.update({
            "page": current_page,
            "page_size": current_page_size,
            "has_more": current_page * current_page_size < result["total"],
        })
    return result


@router.post("")
def create_count(body: CreateCount, db: DbSession, current: User = Depends(access)):
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


@router.get("/{count_id}")
def detail(
    count_id: int,
    db: DbSession,
    _: User = Depends(access),
    result: Literal["all", "scanned", "found", "missing", "unknown", "unexpected", "ambiguous", "changed"] = "all",
    q: str = Query("", max_length=120),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
):
    count = get_count(db, count_id)
    needle = q.strip().casefold()
    if result != "changed":
        summary = stocktake_summary(db, count)
        total, page_rows = stocktake_detail_page(
            db,
            count,
            result=result,
            offset=offset,
            limit=limit,
            search=needle,
        )
        return {**count_info(count), "summary": summary, "total": total, "rows": page_rows}

    rows = results(db, count)
    summary = {
        key: sum(row["result"] == key for row in rows)
        for key in ("found", "missing", "unknown", "unexpected", "ambiguous")
    }
    summary["expected"] = sum(row["expected"] for row in rows)
    summary["changed"] = sum(row["changed"] for row in rows)
    summary.update(scan_summary(rows))
    filtered = [
        r
        for r in rows
        if r["changed"]
        and (
            not needle
            or needle
            in " ".join(
                str(value or "")
                for value in [
                    r["scan_code"],
                    *r["snapshot"].values(),
                    *(r["scan_snapshot"] or {}).values(),
                ]
            ).casefold()
        )
    ]
    return {**count_info(count), "summary": summary, "total": len(filtered), "rows": filtered[offset : offset + limit]}


@router.post("/{count_id}/scan")
def scan(count_id: int, body: ScanCount, db: DbSession, current: User = Depends(access)):
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
    db.commit()
    return {"duplicate": duplicate, "row": row_payload(row, package_snapshots(db, [pid]) if pid else {})}


@router.delete("/{count_id}/scans/{row_id}")
def undo_scan(count_id: int, row_id: int, db: DbSession, current: User = Depends(access)):
    get_count(db, count_id, lock=True)
    row = db.query(WarehouseStocktakeRow).filter_by(stocktake_id=count_id, id=row_id).first()
    if not row or not row.scanned_at:
        raise HTTPException(404, "Recorded scan not found")
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
    db.commit()
    return {"ok": True}


@router.post("/{count_id}/complete")
def complete(count_id: int, db: DbSession, current: User = Depends(access)):
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


def _csv_line(values) -> str:
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow([
        "'" + value
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n"))
        else value
        for value in values
    ])
    return stream.getvalue()


def _stocktake_export_rows(db, count):
    last_row_id = 0
    while True:
        rows = (
            db.query(WarehouseStocktakeRow)
            .filter(
                WarehouseStocktakeRow.stocktake_id == count.id,
                WarehouseStocktakeRow.id > last_row_id,
            )
            .order_by(WarehouseStocktakeRow.id.asc())
            .limit(_STOCKTAKE_EXPORT_CHUNK_SIZE)
            .all()
        )
        if not rows:
            return
        package_ids = sorted({int(row.package_id) for row in rows if row.package_id})
        if count.completed_at and package_ids:
            latest_completed = (
                db.query(
                    WarehouseStocktakeRow.package_id.label("package_id"),
                    func.max(WarehouseStocktakeRow.id).label("row_id"),
                )
                .filter(
                    WarehouseStocktakeRow.stocktake_id == count.id,
                    WarehouseStocktakeRow.package_id.in_(package_ids),
                )
                .group_by(WarehouseStocktakeRow.package_id)
                .subquery()
            )
            completed_rows = (
                db.query(
                    WarehouseStocktakeRow.package_id,
                    WarehouseStocktakeRow.final_snapshot,
                )
                .join(
                    latest_completed,
                    latest_completed.c.row_id == WarehouseStocktakeRow.id,
                )
                .all()
            )
            current = {
                int(package_id): final_snapshot
                for package_id, final_snapshot in completed_rows
            }
        else:
            current = package_snapshots(db, package_ids) if package_ids else {}
        for row in rows:
            yield row_payload(row, current)
        last_row_id = int(rows[-1].id)
        if len(rows) < _STOCKTAKE_EXPORT_CHUNK_SIZE:
            return


@router.get("/{count_id}/export.csv")
def export(count_id: int, db: DbSession, _: User = Depends(access)):
    count = get_count(db, count_id)
    headers = [
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
    def csv_lines():
        yield "\ufeff" + _csv_line(headers)
        seen_packages: set[int] = set()
        scanned_pieces = 0
        estimated_packages = 0
        unquantified_packages = 0
        unknown = 0
        ambiguous = 0
        for row in _stocktake_export_rows(db, count):
            s = row["snapshot"]
            now = row["current"] or {}
            observed = row["scan_snapshot"] or (s if row["scanned_at"] and row["package_id"] else {})
            items = observed.get("items") or ([observed] if observed else [])
            breakdown = "; ".join(
                " / ".join(str(item.get(key) or "") for key in ("model_code", "model_name", "color", "size"))
                + f" : {item.get('quantity', '')}"
                for item in items
            )
            yield _csv_line([
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
            ])
            package_id = int(row["package_id"]) if row["package_id"] is not None else None
            if row["scanned_at"] is not None and package_id is not None and package_id not in seen_packages:
                seen_packages.add(package_id)
                scanned_pieces += row["scanned_pieces"] or 0
                estimated_packages += row["scan_evidence_source"] == "count_start"
                unquantified_packages += row["scanned_pieces"] is None
            unknown += row["result"] == "unknown"
            ambiguous += row["result"] == "ambiguous"
        footer = {
            "Count": count.title,
            "Completed": count.completed_at or "",
            "Result": "TOTAL",
            "Row type": "totals",
            "Scanned packages total": len(seen_packages),
            "Scanned pieces total": scanned_pieces,
            "Count-start fallback packages": estimated_packages,
            "Scanned packages without quantity evidence": unquantified_packages,
            "Unknown labels total": unknown,
            "Ambiguous labels total": ambiguous,
        }
        yield _csv_line([footer.get(header, "") for header in headers])

    return StreamingResponse(
        csv_lines(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="inventory-count-{count_id}.csv"'},
    )
