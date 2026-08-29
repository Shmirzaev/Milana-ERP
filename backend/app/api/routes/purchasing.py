import os
from uuid import uuid4

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import joinedload

from app.core.deps import DbSession, require_permissions
from app.core.config import settings
from app.core.uploads import SAFE_IMAGE_EXTENSIONS, extension_for_upload, read_validated_upload_content
from app.models import PurchaseOrder, PurchaseRequest, User
from app.schemas.purchasing import (
    PurchaseOrderIn,
    PurchaseOrderOut,
    PurchaseOrderReceiveIn,
    PurchaseRequestApprovalIn,
    PurchaseRequestIn,
    PurchaseRequestOrderIn,
    PurchaseRequestOut,
)
from app.services.purchasing import (
    approve_purchase_request,
    convert_purchase_request_to_order,
    create_purchase_order,
    create_purchase_request,
    create_purchase_request_from_sales_order,
    receive_purchase_order,
    reject_purchase_request,
)

router = APIRouter(prefix="/purchasing", tags=["purchasing"])


@router.get("/requests", response_model=list[PurchaseRequestOut])
def list_purchase_requests(
    db: DbSession,
    _: User = Depends(require_permissions("purchasing.view", "*")),
):
    return (
        db.query(PurchaseRequest)
        .options(joinedload(PurchaseRequest.lines))
        .order_by(PurchaseRequest.id.desc())
        .all()
    )


@router.post("/requests", response_model=PurchaseRequestOut, status_code=201)
def create_request(
    payload: PurchaseRequestIn,
    db: DbSession,
    current: User = Depends(require_permissions("purchasing.request", "*")),
):
    request = create_purchase_request(db, data=payload.model_dump(), current=current)
    db.commit()
    db.refresh(request)
    return request


@router.post("/requests/from-sales-order/{sales_order_id}", response_model=PurchaseRequestOut, status_code=201)
def create_request_from_sales_order(
    sales_order_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("purchasing.request", "*")),
):
    request = create_purchase_request_from_sales_order(db, sales_order_id=sales_order_id, current=current)
    db.commit()
    db.refresh(request)
    return request


@router.post("/requests/{request_id}/approve", response_model=PurchaseRequestOut)
def approve_request(
    request_id: int,
    payload: PurchaseRequestApprovalIn,
    db: DbSession,
    current: User = Depends(require_permissions("purchasing.approve", "*")),
):
    request = approve_purchase_request(db, request_id=request_id, data=payload.model_dump(), current=current)
    db.commit()
    db.refresh(request)
    return request


@router.post("/requests/{request_id}/reject", response_model=PurchaseRequestOut)
def reject_request(
    request_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("purchasing.approve", "*")),
):
    request = reject_purchase_request(db, request_id=request_id, current=current)
    db.commit()
    db.refresh(request)
    return request


@router.post("/requests/{request_id}/convert-to-order", response_model=PurchaseOrderOut, status_code=201)
def convert_request_to_order(
    request_id: int,
    payload: PurchaseRequestOrderIn,
    db: DbSession,
    current: User = Depends(require_permissions("purchasing.order", "*")),
):
    order = convert_purchase_request_to_order(db, request_id=request_id, data=payload.model_dump(), current=current)
    db.commit()
    db.refresh(order)
    return order


@router.post("/request-photo/upload", status_code=201)
async def upload_request_photo(
    file: UploadFile = File(...),
    _: User = Depends(require_permissions("purchasing.request", "purchasing.approve", "*")),
):
    from app.services.image_storage import store_uploaded_image

    stored = await store_uploaded_image(
        file,
        target_dir=settings.MODEL_FILES_DIR,
        file_url_base="/storage/model-files",
        name_prefix="purchase",
        max_bytes=10 * 1024 * 1024,
        prebuild_thumbnails=True,
    )
    return {"file_url": stored.file_url}


@router.get("/orders", response_model=list[PurchaseOrderOut])
def list_purchase_orders(
    db: DbSession,
    _: User = Depends(require_permissions("purchasing.view", "*")),
):
    return (
        db.query(PurchaseOrder)
        .options(joinedload(PurchaseOrder.lines))
        .order_by(PurchaseOrder.id.desc())
        .all()
    )


@router.post("/orders", response_model=PurchaseOrderOut, status_code=201)
def create_order(
    payload: PurchaseOrderIn,
    db: DbSession,
    current: User = Depends(require_permissions("purchasing.order", "*")),
):
    order = create_purchase_order(db, data=payload.model_dump(), current=current)
    db.commit()
    db.refresh(order)
    return order


@router.post("/orders/{order_id}/receive", response_model=PurchaseOrderOut)
def receive_order(
    order_id: int,
    payload: PurchaseOrderReceiveIn,
    db: DbSession,
    current: User = Depends(require_permissions("purchasing.receive", "*")),
):
    order = receive_purchase_order(db, order_id=order_id, data=payload.model_dump(), current=current)
    db.commit()
    db.refresh(order)
    return order
