from fastapi import APIRouter, Depends, Header

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.libs.dto.inventory.waste_disposal_input import WasteDisposalIn
from app.libs.dto.inventory.waste_disposal_output import WasteDisposalOut
from app.libs.dto.inventory.waste_input import WasteIn
from app.libs.dto.inventory.waste_output import WasteOut
from app.libs.dto.inventory.waste_sale_input import WasteSaleIn
from app.libs.dto.inventory.waste_sale_output import WasteSaleOut
from app.models.inventory import waste_service
from app.schemas import User

router = APIRouter(prefix="/waste", tags=["waste"])


@router.get("", response_model=list[WasteOut])
def list_waste(db: DbSession, _: CurrentUser, status: str | None = None, sellable: bool | None = None):
    return waste_service.list_waste(db, status=status, sellable=sellable)


@router.post("", response_model=WasteOut, status_code=201)
def create_waste(payload: WasteIn, db: DbSession, current: User = Depends(require_permissions(
    "cutting.records", "printing.records", "sewing.records", "packaging.records",
    "waste.receive", "planning.production", "management.approve", "*",
))):
    return waste_service.create_waste(db, payload, current)


@router.post("/{wid}/receive", response_model=WasteOut)
def receive_waste(wid: int, db: DbSession, current: User = Depends(require_permissions("waste.receive", "*"))):
    return waste_service.receive_waste(db, wid, current)


@router.post("/{wid}/sell", response_model=WasteSaleOut)
def sell_waste(
    wid: int,
    payload: WasteSaleIn,
    db: DbSession,
    current: User = Depends(require_permissions("waste.sell", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    return waste_service.sell_waste(db, wid, payload, current, idempotency_key=idempotency_key)


@router.post("/{wid}/request-disposal", response_model=WasteDisposalOut)
def request_disposal(wid: int, payload: WasteDisposalIn, db: DbSession, current: User = Depends(require_permissions("waste.disposal", "*"))):
    return waste_service.request_disposal(db, wid, payload, current)


@router.post("/disposal/{rid}/approve", response_model=WasteDisposalOut)
def approve_disposal(rid: int, db: DbSession, current: User = Depends(require_permissions("management.approve", "*"))):
    return waste_service.approve_disposal(db, rid, current)


@router.post("/disposal/{rid}/reject", response_model=WasteDisposalOut)
def reject_disposal(rid: int, db: DbSession, current: User = Depends(require_permissions("management.approve", "*"))):
    return waste_service.reject_disposal(db, rid, current)


@router.post("/disposal/{rid}/mark-disposed", response_model=WasteDisposalOut)
def mark_disposed(rid: int, db: DbSession, current: User = Depends(require_permissions("waste.disposal", "*"))):
    return waste_service.mark_disposed(db, rid, current)
