from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.core.deps import DbSession, require_permissions
from app.libs.dto.inventory.warehouse_stocktake_input import (
    CreateCount, DeleteCounts, DeleteScans, ScanCount,
)
from app.models import stocktake_service
from app.schemas import User

router = APIRouter(prefix="/warehouse-stocktakes", tags=["warehouse_stocktakes"])
access = require_permissions("storage.packages", "storage.shipment")


@router.get("")
def list_counts(db: DbSession, _: User = Depends(access), offset: int = Query(0, ge=0)):
    return stocktake_service.list_counts(db, offset=offset)


@router.post("")
def create_count(body: CreateCount, db: DbSession, current: User = Depends(access)):
    return stocktake_service.create_count(db, body, current)


@router.post("/delete-selected")
def delete_counts(body: DeleteCounts, db: DbSession, current: User = Depends(access)):
    return stocktake_service.delete_counts(db, body, current)


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
    return stocktake_service.count_detail(db, count_id, result=result, q=q, offset=offset, limit=limit)


@router.post("/{count_id}/scan")
def scan(count_id: int, body: ScanCount, db: DbSession, current: User = Depends(access)):
    return stocktake_service.scan_count(db, count_id, body, current)


@router.post("/{count_id}/scans/delete-selected")
def delete_scans(count_id: int, body: DeleteScans, db: DbSession, current: User = Depends(access)):
    return stocktake_service.delete_scans(db, count_id, body, current)


@router.delete("/{count_id}/scans/{row_id}")
def undo_scan(count_id: int, row_id: int, db: DbSession, current: User = Depends(access)):
    return stocktake_service.undo_scan(db, count_id, row_id, current)


@router.post("/{count_id}/complete")
def complete(count_id: int, db: DbSession, current: User = Depends(access)):
    return stocktake_service.complete_count(db, count_id, current)


@router.get("/{count_id}/export.csv")
def export(count_id: int, db: DbSession, _: User = Depends(access)):
    csv_text = stocktake_service.export_count(db, count_id)
    return Response(
        "\ufeff" + csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="inventory-count-{count_id}.csv"'},
    )
