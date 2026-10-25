"""Isolated daily reporting: writes only fabric_scans, never stock movements."""
from datetime import date

from fastapi import APIRouter, Depends, Query

from app.core.deps import DbSession, require_permissions
from app.libs.dto.inventory.fabric_scan_input import ScanInput
from app.models.inventory.fabric_scans_service import fabric_scan_report, scan_fabric_roll
from app.schemas import User

router = APIRouter(prefix="/fabric-scans", tags=["fabric_scan_register"])
scan_access = require_permissions("cutting.records", "cutting.bundles", "storage.receive", "storage.items")
report_access = require_permissions("cutting.records", "cutting.bundles", "storage.receive", "storage.items", "planning.production", "management.view")


@router.post("")
def scan(payload: ScanInput, db: DbSession, user: User = Depends(scan_access)):
    return scan_fabric_roll(db, payload, user)


@router.get("")
def report(db: DbSession, user: User = Depends(report_access),
           report_date: date | None = None, page: int = Query(1, ge=1),
           page_size: int = Query(50, ge=1, le=200)):
    return fabric_scan_report(db, user, report_date=report_date, page=page, page_size=page_size)
