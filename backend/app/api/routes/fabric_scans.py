"""Isolated daily reporting: writes only fabric_scans, never stock movements."""
import re
from datetime import date, datetime, timezone
from typing import Literal
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError

from app.core.deps import DbSession, require_permissions
from app.models import StockBatch, User
from app.models.fabric_scan import FabricScan
from app.services.factory_scope import cutting_department_scope
from app.services.inventory_access import MATERIAL_CATEGORIES

router = APIRouter(prefix="/fabric-scans", tags=["fabric_scan_register"])
scan_access = require_permissions("cutting.records", "cutting.bundles", "storage.receive", "storage.items")
report_access = require_permissions("cutting.records", "cutting.bundles", "storage.receive", "storage.items", "planning.production", "management.view")
TASHKENT = ZoneInfo("Asia/Tashkent")


class ScanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=2048)
    direction: Literal["received", "returned"]


def now_utc():
    return datetime.now(timezone.utc)


def parse_roll(code: str) -> tuple[int, int]:
    value = code.strip()
    match = re.fullmatch(r"B([1-9]\d*)-R([1-9]\d*)", value, re.IGNORECASE)
    if match:
        batch, roll = match.groups()
    else:
        try:
            url = urlsplit(value)
            params = parse_qs(url.query, max_num_fields=20)
        except ValueError:
            raise HTTPException(400, "invalid_roll_code") from None
        if url.path.rstrip("/") != "/inventory" or url.scheme not in ("", "http", "https"):
            raise HTTPException(400, "invalid_roll_code")
        if len(params.get("batch_id", [])) != 1 or len(params.get("roll", [])) != 1:
            raise HTTPException(400, "invalid_roll_code")
        batch, roll = params["batch_id"][0], params["roll"][0]
    if not re.fullmatch(r"[1-9][0-9]{0,9}", batch) or not re.fullmatch(r"[1-9][0-9]{0,9}", roll):
        raise HTTPException(400, "invalid_roll_code")
    if int(batch) > 2147483647 or int(roll) > 2147483647:
        raise HTTPException(400, "invalid_roll_code")
    return int(batch), int(roll)


def row_data(row):
    return {
        "id": row.id, "report_date": row.report_date, "direction": row.direction,
        "fabric_name": row.fabric_name, "batch_no": row.batch_no, "color": row.color,
        "roll_number": row.roll_number, "operator_name": row.operator_name,
        "scanned_at": row.scanned_at.replace(tzinfo=timezone.utc) if row.scanned_at.tzinfo is None else row.scanned_at,
    }


@router.post("")
def scan(payload: ScanInput, db: DbSession, user: User = Depends(scan_access)):
    department = cutting_department_scope(user, None)
    batch_id, roll = parse_roll(payload.code)
    timestamp = now_utc()
    identity = dict(department=department, report_date=timestamp.astimezone(TASHKENT).date(),
                    batch_id=batch_id, roll_number=roll, direction=payload.direction)
    existing = db.query(FabricScan).filter_by(**identity).first()
    if existing:
        return {"duplicate": True, "row": row_data(existing)}
    batch = db.get(StockBatch, batch_id)
    if not batch or not batch.item or batch.item.category not in MATERIAL_CATEGORIES:
        raise HTTPException(404, "fabric_not_found")
    # Do not trust roll_total, weight, fabric names or other data inside the QR.
    # Depleted/archived batches can still have physical rolls returning to storage.
    count = max(batch.piece_count or 0, len(batch.roll_weights_kg or []))
    if roll > count:
        raise HTTPException(400, "roll_not_found")
    row = FabricScan(**identity, fabric_name=batch.item.name, batch_no=batch.batch_no,
                     color=batch.color, operator_id=user.id, operator_name=user.name,
                     scanned_at=timestamp)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(FabricScan).filter_by(**identity).first()
        if existing:
            return {"duplicate": True, "row": row_data(existing)}
        raise
    return {"duplicate": False, "row": row_data(row)}


@router.get("")
def report(db: DbSession, user: User = Depends(report_access),
           report_date: date | None = None, page: int = Query(1, ge=1),
           page_size: int = Query(50, ge=1, le=200)):
    department = cutting_department_scope(user, None)
    day = report_date or now_utc().astimezone(TASHKENT).date()
    query = db.query(FabricScan).filter_by(department=department, report_date=day)
    received = func.sum(case((FabricScan.direction == "received", 1), else_=0))
    returned = func.sum(case((FabricScan.direction == "returned", 1), else_=0))
    totals = query.with_entities(func.count(FabricScan.id), received, returned).one()
    groups = query.with_entities(FabricScan.batch_id, FabricScan.fabric_name, FabricScan.batch_no,
                                FabricScan.color, received, returned).group_by(
        FabricScan.batch_id, FabricScan.fabric_name, FabricScan.batch_no, FabricScan.color,
    ).order_by(FabricScan.fabric_name, FabricScan.batch_no).all()
    rows = query.order_by(FabricScan.scanned_at.desc(), FabricScan.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "report_date": day, "department": department, "total": totals[0],
        "received": totals[1] or 0, "returned": totals[2] or 0,
        "summary": [{"fabric_name": r[1], "batch_no": r[2], "color": r[3],
                     "received": r[4], "returned": r[5]} for r in groups],
        "rows": [row_data(row) for row in rows], "page": page, "page_size": page_size,
    }
