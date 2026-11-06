"""Milana-owned fabric sent offsite and returned; never receipts into Eco inventory."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.core.deps import DbSession, require_permissions
from app.libs.dto.inventory.eco_fabric_transfer_input import ReturnIn, ScanIn, SendIn
from app.models.factory_scope_service import selected_factory_code
from app.models.inventory.transfers_service import (
    eco_return_fabric,
    eco_scan_roll,
    eco_send_fabric,
    eco_transfer_pdf,
    eco_transfer_report,
)
from app.schemas import User

router = APIRouter(prefix="/eco-fabric-transfers", tags=["eco_fabric_transfers"])


def access(user: User = Depends(require_permissions("inventory.eco_transfers"))):
    if selected_factory_code(user) != "MIL":
        raise HTTPException(403, "ecoTransfers.milanaOnly")
    return user


@router.post("/scan")
def scan(payload: ScanIn, db: DbSession, user: User = Depends(access)):
    return eco_scan_roll(db, payload)


@router.post("/send")
def send(payload: SendIn, db: DbSession, user: User = Depends(access)):
    return eco_send_fabric(db, payload, user)


@router.post("/return")
def receive(payload: ReturnIn, db: DbSession, user: User = Depends(access)):
    return eco_return_fabric(db, payload, user)


@router.get("")
def report(db: DbSession, user: User = Depends(access), report_date: date | None = None,
           page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100)):
    return eco_transfer_report(db, report_date=report_date, page=page, page_size=page_size)


@router.get("/{dispatch_id}/pdf")
def pdf(dispatch_id: int, db: DbSession, lang: str = "en", user: User = Depends(access)):
    document = eco_transfer_pdf(db, dispatch_id, lang=lang)
    return Response(document["content"], media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{document["number"]}.pdf"'})
