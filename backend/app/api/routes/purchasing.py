
from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from sqlalchemy.orm import joinedload, lazyload, selectinload

from app.core.deps import DbSession, require_permissions
from app.core.config import settings
from app.models import Item, PurchaseOrder, PurchaseOrderLine, PurchaseRequest, PurchaseRequestLine, User
from app.services import inventory_access
from app.services.factory_scope import selected_factory_code
from app.services.idempotency import replay_idempotent_response, store_idempotent_response
from app.schemas.purchasing import (
    PurchaseOrderIn,
    PurchaseOrderOut,
    PurchaseOrderReceiveIn,
    PurchaseRequestApprovalIn,
    PurchaseRequestIn,
    PurchaseRequestOrderIn,
    PurchaseRequestOut,
    PurchaseRequestPageOut,
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


@router.get("/requests", response_model=list[PurchaseRequestOut] | PurchaseRequestPageOut)
def list_purchase_requests(
    db: DbSession,
    _: User = Depends(require_permissions("purchasing.view", "*")),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=500),
):
    query = (
        db.query(PurchaseRequest)
        .filter(~PurchaseRequest.lines.any(PurchaseRequestLine.item_id.in_(
            db.query(Item.id).filter(Item.category.notin_(inventory_access.MATERIAL_CATEGORIES))
        )) if inventory_access.materials_only(_) else True)
        .options(joinedload(PurchaseRequest.lines))
        .order_by(PurchaseRequest.id.desc())
    )
    if page is None and page_size is None:
        return query.all()

    current_page = page or 1
    safe_page_size = page_size or 100
    total = query.order_by(None).count()
    rows = (
        query.offset((current_page - 1) * safe_page_size)
        .limit(safe_page_size)
        .all()
    )
    return {
        "rows": rows,
        "total": total,
        "page": current_page,
        "page_size": safe_page_size,
        "has_more": current_page * safe_page_size < total,
    }


@router.post("/requests", response_model=PurchaseRequestOut, status_code=201)
def create_request(
    payload: PurchaseRequestIn,
    db: DbSession,
    current: User = Depends(require_permissions("purchasing.request", "*")),
):
    request = create_purchase_request(db, data=payload.model_dump(), current=current)
    for line in request.lines:
        inventory_access.require_item(db, current, line.item_id)
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
    for line in request.lines:
        inventory_access.require_item(db, current, line.item_id)
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
    for line in request.lines:
        inventory_access.require_item(db, current, line.item_id)
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
    for line in request.lines:
        inventory_access.require_item(db, current, line.item_id)
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
    for line in order.lines:
        inventory_access.require_item(db, current, line.item_id)
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
        .filter(~PurchaseOrder.lines.any(PurchaseOrderLine.item_id.in_(
            db.query(Item.id).filter(Item.category.notin_(inventory_access.MATERIAL_CATEGORIES))
        )) if inventory_access.materials_only(_) else True)
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
    for line in order.lines:
        inventory_access.require_item(db, current, line.item_id)
    db.commit()
    db.refresh(order)
    return order


@router.post("/orders/{order_id}/receive", response_model=PurchaseOrderOut)
def receive_order(
    order_id: int,
    payload: PurchaseOrderReceiveIn,
    db: DbSession,
    current: User = Depends(require_permissions("purchasing.receive", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    # Serialize receipt/replay on the order before reading its current state.
    # Disable eager outer joins so PostgreSQL locks only the purchase order.
    order = (
        db.query(PurchaseOrder).options(lazyload("*"), selectinload(PurchaseOrder.lines))
        .filter(PurchaseOrder.id == order_id).with_for_update(of=PurchaseOrder)
        .populate_existing().first()
    )
    if not order:
        raise HTTPException(404, "Purchase order not found")
    for line in order.lines:
        inventory_access.require_item(db, current, line.item_id)
    scope = f"purchasing.receive:{selected_factory_code(current)}:{current.id}:{order_id}"
    fingerprint_payload = payload.model_dump(mode="json")
    replay = replay_idempotent_response(db, user=current, scope=scope, key=idempotency_key, payload=fingerprint_payload)
    if replay is not None:
        if replay.get("_purchase_receipt_request") == "cancelled":
            raise HTTPException(409, "This receipt request was cancelled; submit corrected values with a new key")
        return replay
    order = receive_purchase_order(db, order_id=order_id, data=payload.model_dump(), current=current)
    response = PurchaseOrderOut.model_validate(order).model_dump(mode="json")
    store_idempotent_response(
        db, scope=scope, key=idempotency_key, payload=fingerprint_payload,
        response=response, user=current, status_code=200,
    )
    db.commit()
    return response


@router.post("/orders/{order_id}/receive/reconcile")
def reconcile_order_receipt(
    order_id: int,
    payload: PurchaseOrderReceiveIn,
    db: DbSession,
    current: User = Depends(require_permissions("purchasing.receive", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key is required for receipt reconciliation")
    order = (
        db.query(PurchaseOrder).options(lazyload("*"), selectinload(PurchaseOrder.lines))
        .filter(PurchaseOrder.id == order_id).with_for_update(of=PurchaseOrder)
        .populate_existing().first()
    )
    if not order:
        raise HTTPException(404, "Purchase order not found")
    for line in order.lines:
        inventory_access.require_item(db, current, line.item_id)
    scope = f"purchasing.receive:{selected_factory_code(current)}:{current.id}:{order_id}"
    fingerprint_payload = payload.model_dump(mode="json")
    replay = replay_idempotent_response(
        db,
        user=current,
        scope=scope,
        key=idempotency_key,
        payload=fingerprint_payload,
    )
    if replay is not None:
        db.commit()
        if replay.get("_purchase_receipt_request") == "cancelled":
            return {"status": "cancelled"}
        return {"status": "completed", "result": replay}
    store_idempotent_response(
        db,
        scope=scope,
        key=idempotency_key,
        payload=fingerprint_payload,
        response={"_purchase_receipt_request": "cancelled"},
        user=current,
        status_code=409,
    )
    db.commit()
    return {"status": "cancelled"}
