
from typing import Annotated

from fastapi import APIRouter, Depends, File, Header, Query, UploadFile

from app.core.deps import DbSession, require_permissions
from app.libs.dto.purchasing.purchase_order_input import PurchaseOrderIn, PurchaseOrderReceiveIn
from app.libs.dto.purchasing.purchase_order_output import PurchaseOrderOut
from app.libs.dto.purchasing.purchase_request_input import (
    PurchaseRequestApprovalIn,
    PurchaseRequestIn,
    PurchaseRequestOrderIn,
)
from app.libs.dto.purchasing.purchase_request_output import PurchaseRequestOut
from app.models.purchasing import orders_service, receiving_service, requests_service
from app.schemas import User

router = APIRouter(prefix="/purchasing", tags=["purchasing"])


@router.get("/requests", response_model=list[PurchaseRequestOut])
def list_purchase_requests(
    db: DbSession,
    _: User = Depends(require_permissions("purchasing.view", "*")),
):
    return requests_service.list_purchase_requests(db, user=_)


@router.post("/requests", response_model=PurchaseRequestOut, status_code=201)
def create_request(
    payload: PurchaseRequestIn,
    db: DbSession,
    current: User = Depends(require_permissions("purchasing.request", "*")),
):
    return requests_service.create_purchase_request(db, payload=payload, current=current)


@router.post("/requests/from-sales-order/{sales_order_id}", response_model=PurchaseRequestOut, status_code=201)
def create_request_from_sales_order(
    sales_order_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("purchasing.request", "*")),
):
    return requests_service.create_purchase_request_from_sales_order(
        db, sales_order_id=sales_order_id, current=current
    )


@router.post("/requests/{request_id}/approve", response_model=PurchaseRequestOut)
def approve_request(
    request_id: int,
    payload: PurchaseRequestApprovalIn,
    db: DbSession,
    current: User = Depends(require_permissions("purchasing.approve", "*")),
):
    return requests_service.approve_purchase_request(
        db, request_id=request_id, payload=payload, current=current
    )


@router.post("/requests/{request_id}/reject", response_model=PurchaseRequestOut)
def reject_request(
    request_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("purchasing.approve", "*")),
):
    return requests_service.reject_purchase_request(db, request_id=request_id, current=current)


@router.post("/requests/{request_id}/convert-to-order", response_model=PurchaseOrderOut, status_code=201)
def convert_request_to_order(
    request_id: int,
    payload: PurchaseRequestOrderIn,
    db: DbSession,
    current: User = Depends(require_permissions("purchasing.order", "*")),
):
    return requests_service.convert_purchase_request_to_order(
        db, request_id=request_id, payload=payload, current=current
    )


@router.post("/request-photo/upload", status_code=201)
async def upload_request_photo(
    file: UploadFile = File(...),
    _: User = Depends(require_permissions("purchasing.request", "purchasing.approve", "*")),
):
    return await requests_service.store_request_photo(file)


@router.get("/orders")
def list_purchase_orders(
    db: DbSession,
    _: User = Depends(require_permissions("purchasing.view", "*")),
    status: str | None = Query(None, max_length=32),
    limit: int = Query(50, ge=1, le=orders_service.PURCHASE_ORDER_LIST_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    receivable_only: Annotated[bool, Query()] = False,
):
    """One page of purchase orders plus the exact filtered total.

    `total` is the true count for the same filters, not the page length, so the
    receiving screen can page instead of silently showing a truncated list.
    Ordering is unchanged (`PurchaseOrder.id.desc()`).
    """
    return orders_service.list_purchase_orders(
        db, user=_, status=status, limit=limit, offset=offset, receivable_only=receivable_only
    )


@router.post("/orders", response_model=PurchaseOrderOut, status_code=201)
def create_order(
    payload: PurchaseOrderIn,
    db: DbSession,
    current: User = Depends(require_permissions("purchasing.order", "*")),
):
    return orders_service.create_purchase_order(db, payload=payload, current=current)


@router.post("/orders/{order_id}/receive", response_model=PurchaseOrderOut)
def receive_order(
    order_id: int,
    payload: PurchaseOrderReceiveIn,
    db: DbSession,
    current: User = Depends(require_permissions("purchasing.receive", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    return receiving_service.receive_purchase_order(
        db, order_id=order_id, payload=payload, current=current, idempotency_key=idempotency_key
    )
