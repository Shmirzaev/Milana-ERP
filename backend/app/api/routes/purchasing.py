from typing import Annotated

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import aliased, joinedload, lazyload, load_only, selectinload

from app.core.deps import CurrentUser, DbSession, require_permissions, user_permissions
from app.core.config import settings
from app.models import (
    Item,
    ProductionOrder,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequest,
    PurchaseRequestLine,
    SalesOrder,
    Supplier,
    User,
    Warehouse,
)
from app.services import inventory_access
from app.services.factory_scope import selected_factory_code
from app.services.idempotency import replay_idempotent_response, store_idempotent_response
from app.schemas.purchasing import (
    PurchaseOrderIn,
    PurchaseOrderOut,
    PurchaseOrderPageOut,
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
        .options(
            lazyload("*"),
            load_only(
                PurchaseRequest.id,
                PurchaseRequest.request_no,
                PurchaseRequest.status,
                PurchaseRequest.sales_order_id,
                PurchaseRequest.production_order_id,
                PurchaseRequest.requested_by,
                PurchaseRequest.approved_by,
                PurchaseRequest.approved_at,
                PurchaseRequest.notes,
                PurchaseRequest.created_at,
                PurchaseRequest.updated_at,
            ),
            joinedload(PurchaseRequest.sales_order).load_only(
                SalesOrder.id,
                SalesOrder.order_no,
            ),
            joinedload(PurchaseRequest.production_order).load_only(
                ProductionOrder.id,
                ProductionOrder.production_no,
            ),
            joinedload(PurchaseRequest.lines).load_only(
                PurchaseRequestLine.id,
                PurchaseRequestLine.purchase_request_id,
                PurchaseRequestLine.item_id,
                PurchaseRequestLine.required_quantity,
                PurchaseRequestLine.requested_quantity,
                PurchaseRequestLine.unit,
                PurchaseRequestLine.available_quantity,
                PurchaseRequestLine.shortage_quantity,
                PurchaseRequestLine.preferred_supplier_id,
                PurchaseRequestLine.material_name,
                PurchaseRequestLine.photo_url,
                PurchaseRequestLine.notes,
            ).options(
                joinedload(PurchaseRequestLine.item).load_only(
                    Item.id,
                    Item.sku,
                    Item.name,
                ),
                joinedload(PurchaseRequestLine.preferred_supplier).load_only(
                    Supplier.id,
                    Supplier.name,
                ),
            ),
        )
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


@router.get("/orders", response_model=list[PurchaseOrderOut] | PurchaseOrderPageOut)
def list_purchase_orders(
    db: DbSession,
    _: User = Depends(require_permissions("purchasing.view", "*")),
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=500)] = None,
    order_id: Annotated[int | None, Query(ge=1)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    receivable_only: bool = False,
):
    filters = []
    if inventory_access.materials_only(_):
        filters.append(~PurchaseOrder.lines.any(PurchaseOrderLine.item_id.in_(
            db.query(Item.id).filter(Item.category.notin_(inventory_access.MATERIAL_CATEGORIES))
        )))
    if order_id is not None:
        filters.append(PurchaseOrder.id == order_id)
    if receivable_only:
        filters.extend((
            PurchaseOrder.status.in_(("sent", "approved", "partially_received")),
            PurchaseOrder.lines.any(
                PurchaseOrderLine.ordered_quantity > PurchaseOrderLine.received_quantity
            ),
        ))
    needle = (q or "").strip()
    if needle:
        escaped_needle = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped_needle}%"
        line_search = or_(
            PurchaseOrderLine.material_name.ilike(pattern, escape="\\"),
            PurchaseOrderLine.item.has(or_(
                Item.name.ilike(pattern, escape="\\"),
                Item.sku.ilike(pattern, escape="\\"),
            )),
            PurchaseOrderLine.supplier.has(Supplier.name.ilike(pattern, escape="\\")),
        )
        if receivable_only:
            line_search = and_(
                PurchaseOrderLine.ordered_quantity > PurchaseOrderLine.received_quantity,
                line_search,
            )
        filters.append(or_(
            PurchaseOrder.po_no.ilike(pattern, escape="\\"),
            PurchaseOrder.supplier.has(Supplier.name.ilike(pattern, escape="\\")),
            PurchaseOrder.purchase_request.has(PurchaseRequest.request_no.ilike(pattern, escape="\\")),
            PurchaseOrder.lines.any(line_search),
        ))
    query = (
        db.query(PurchaseOrder)
        .filter(*filters)
        .options(
            lazyload("*"),
            load_only(
                PurchaseOrder.id,
                PurchaseOrder.po_no,
                PurchaseOrder.purchase_request_id,
                PurchaseOrder.supplier_id,
                PurchaseOrder.status,
                PurchaseOrder.ordered_by,
                PurchaseOrder.expected_date,
                PurchaseOrder.notes,
                PurchaseOrder.created_at,
                PurchaseOrder.updated_at,
            ),
            joinedload(PurchaseOrder.purchase_request).load_only(
                PurchaseRequest.id,
                PurchaseRequest.request_no,
            ),
            joinedload(PurchaseOrder.supplier).load_only(
                Supplier.id,
                Supplier.name,
            ),
            joinedload(PurchaseOrder.lines).load_only(
                PurchaseOrderLine.id,
                PurchaseOrderLine.purchase_order_id,
                PurchaseOrderLine.item_id,
                PurchaseOrderLine.ordered_quantity,
                PurchaseOrderLine.received_quantity,
                PurchaseOrderLine.unit,
                PurchaseOrderLine.unit_cost,
                PurchaseOrderLine.warehouse_id,
                PurchaseOrderLine.supplier_id,
                PurchaseOrderLine.material_name,
                PurchaseOrderLine.photo_url,
                PurchaseOrderLine.notes,
            ).options(
                joinedload(PurchaseOrderLine.item).load_only(
                    Item.id,
                    Item.sku,
                    Item.name,
                ),
                joinedload(PurchaseOrderLine.warehouse).load_only(
                    Warehouse.id,
                    Warehouse.name,
                ),
                joinedload(PurchaseOrderLine.supplier).load_only(
                    Supplier.id,
                    Supplier.name,
                ),
            ),
        )
        .order_by(PurchaseOrder.id.desc())
    )
    if page is None and page_size is None:
        return query.all()
    current_page = page or 1
    safe_page_size = page_size or 100
    total = query.order_by(None).count()
    rows = query.offset((current_page - 1) * safe_page_size).limit(safe_page_size).all()
    supplier_totals = []
    if receivable_only:
        visible_supplier_ids = set()
        visible_supplier_names = set()
        for order in rows:
            for line in order.lines:
                if (line.ordered_quantity or 0) <= (line.received_quantity or 0):
                    continue
                supplier_id = line.supplier_id or order.supplier_id
                if supplier_id:
                    visible_supplier_ids.add(int(supplier_id))
                    continue
                supplier_name = line.supplier.name if line.supplier else None
                supplier_name = supplier_name or (order.supplier.name if order.supplier else "")
                visible_supplier_names.add(supplier_name.strip())

        line_supplier = aliased(Supplier)
        order_supplier = aliased(Supplier)
        supplier_id_expr = func.coalesce(PurchaseOrderLine.supplier_id, PurchaseOrder.supplier_id)
        supplier_name_expr = func.trim(func.coalesce(
            line_supplier.name, order_supplier.name, "",
        ))
        normalized_unit = func.lower(func.trim(func.replace(PurchaseOrderLine.unit, ".", "")))
        visible_supplier_filter = []
        if visible_supplier_ids:
            visible_supplier_filter.append(supplier_id_expr.in_(visible_supplier_ids))
        if visible_supplier_names:
            visible_supplier_filter.append(
                supplier_id_expr.is_(None) & supplier_name_expr.in_(visible_supplier_names)
            )
        if visible_supplier_filter:
            aggregate_rows = db.query(
                supplier_id_expr,
                supplier_name_expr,
                func.coalesce(func.sum(case(
                    (normalized_unit.in_(("kg", "kgs", "kilogram", "kilograms", "кг")), PurchaseOrderLine.ordered_quantity),
                    else_=0,
                )), 0),
            ).select_from(PurchaseOrder).join(
                PurchaseOrderLine, PurchaseOrderLine.purchase_order_id == PurchaseOrder.id,
            ).outerjoin(
                line_supplier, line_supplier.id == PurchaseOrderLine.supplier_id,
            ).outerjoin(
                order_supplier, order_supplier.id == PurchaseOrder.supplier_id,
            ).filter(
                *filters,
                or_(*visible_supplier_filter),
                PurchaseOrder.status.in_(("sent", "approved", "partially_received")),
                PurchaseOrderLine.ordered_quantity > PurchaseOrderLine.received_quantity,
            ).group_by(supplier_id_expr, supplier_name_expr).all()
            totals_by_key = {}
            for row in aggregate_rows:
                key = f"supplier:{int(row[0])}" if row[0] else f"supplier-name:{row[1].strip().lower()}"
                totals_by_key[key] = totals_by_key.get(key, 0.0) + float(row[2] or 0)
            supplier_totals = [
                {"key": key, "total_ordered_kg": total_ordered_kg}
                for key, total_ordered_kg in totals_by_key.items()
            ]
    return {
        "rows": rows,
        "total": total,
        "page": current_page,
        "page_size": safe_page_size,
        "has_more": current_page * safe_page_size < total,
        "supplier_totals": supplier_totals,
    }


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
    current: CurrentUser,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key is required for receipt reconciliation")
    can_receive = bool(set(user_permissions(current)).intersection({"purchasing.receive", "*"}))
    order = (
        db.query(PurchaseOrder).options(lazyload("*"))
        .filter(PurchaseOrder.id == order_id).with_for_update(of=PurchaseOrder)
        .populate_existing().first()
    )
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
        if replay.get("_purchase_receipt_request") == "cancelled":
            db.commit()
            return {"status": "cancelled"}
        if not can_receive or not order:
            db.commit()
            return {"status": "completed_unavailable"}
        try:
            for line in order.lines:
                inventory_access.require_item(db, current, line.item_id)
        except HTTPException as exc:
            if exc.status_code not in {403, 404}:
                raise
            db.commit()
            return {"status": "completed_unavailable"}
        db.commit()
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
