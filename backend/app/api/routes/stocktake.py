import csv
import hashlib
import io
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from app.core.deps import DbSession, require_permissions
from app.models import User
from app.models.stocktake import WarehouseStocktake, WarehouseStocktakeRow
from app.services.audit import log_action
from app.services.stocktake import package_snapshots, resolve_package, row_payload

router = APIRouter(prefix="/warehouse-stocktakes", tags=["warehouse_stocktakes"])
access = require_permissions("storage.packages", "storage.shipment")


class CreateCount(BaseModel):
    request_key: UUID
    title: str = Field(min_length=1, max_length=120)


class ScanCount(BaseModel):
    code: str = Field(min_length=1, max_length=512)


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


@router.get("")
def list_counts(db: DbSession, _: User = Depends(access), offset: int = Query(0, ge=0)):
    query = db.query(WarehouseStocktake)
    return {
        "total": query.count(),
        "items": [
            count_info(c)
            for c in query.order_by(
                WarehouseStocktake.id.desc(),
            )
            .offset(offset)
            .limit(50)
            .all()
        ],
    }


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
    result: Literal["all", "found", "missing", "unknown", "unexpected", "ambiguous", "changed"] = "all",
    q: str = Query("", max_length=120),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
):
    count = get_count(db, count_id)
    rows = results(db, count)
    summary = {
        key: sum(r["result"] == key for r in rows) for key in ("found", "missing", "unknown", "unexpected", "ambiguous")
    }
    summary["expected"] = sum(r["expected"] for r in rows)
    summary["changed"] = sum(r["changed"] for r in rows)
    summary["scanned"] = sum(r["scanned_at"] is not None for r in rows)
    needle = q.strip().casefold()
    filtered = [
        r
        for r in rows
        if (result == "all" or (r["changed"] if result == "changed" else r["result"] == result))
        and (
            not needle
            or needle
            in " ".join(
                str(v or "")
                for v in [
                    r["scan_code"],
                    *r["snapshot"].values(),
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
    identity = f"package:{pid}" if pid else "code:" + hashlib.sha256(code.encode()).hexdigest()
    row = db.query(WarehouseStocktakeRow).filter_by(stocktake_id=count_id, identity=identity).first()
    duplicate = bool(row and row.scanned_at)
    if not row:
        snapshot = package_snapshots(db, [pid]).get(pid, {}) if pid else {}
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


@router.get("/{count_id}/export.csv")
def export(count_id: int, db: DbSession, _: User = Depends(access)):
    count = get_count(db, count_id)
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(
        [
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
        ]
    )
    for row in results(db, count):
        s = row["snapshot"]
        now = row["current"] or {}
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
        ]
        writer.writerow(
            [
                "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else v
                for v in values
            ]
        )
    return Response(
        "\ufeff" + stream.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="inventory-count-{count_id}.csv"'},
    )
