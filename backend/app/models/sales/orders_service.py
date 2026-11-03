"""Sales-order lifecycle: CRUD, listing, options, confirm, reservation.

Contract for the order operations:
* input: the sales-order payload plus the acting user
* output: the serialized order, or the option/reservation lists
* refusals: 400 for an invalid order shape, 404 for a missing order, customer
  or model, 409 for a status or stock conflict
* records: `sales_orders`, `sales_order_items`, `stock_reservations` and the
  audit trail
* transaction owner: every operation below commits its own unit of work, and
  no helper commits part of it
"""
import os
from datetime import date
from typing import Iterable
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.dt import date_filter_bounds
from app.core.model_search import normalized_model_code_column, normalized_model_code_pattern
from app.core.order_reference import order_reference_contains
from app.core.signing import sign_path, strip_signature
from app.core.uploads import (
    SAFE_DOCUMENT_EXTENSIONS,
    SAFE_IMAGE_EXTENSIONS,
    extension_for_upload,
    safe_content_type,
    read_validated_upload_content,
)
from app.libs.dto.sales.sales_order_input import SalesOrderIn, SalesOrderPrintingAttachment
from app.libs.dto.sales.sales_order_output import SalesOrderDetail, SalesOrderListRow, SalesOrderOut
from app.libs.dto.sales.sales_stock_output import SalesStockReservationOut
from app.libs.dto.sales.sales_order_update import SalesOrderUpdate
from app.libs.enums.sales import SalesOrderItemSourceType, SalesOrderStatus, SalesOrderType
from app.libs.types.sales_order import SalesOrderHeaderChanges, StoredSalesAttachment
from app.models.audit_service import log_action
from app.models.idempotency_service import replay_idempotent_response, store_idempotent_response
from app.models.numbering_service import next_sales_order_no
from app.models.fulfillment.stock_service import ready_pack_candidates, is_any_stock_token
from app.libs.enums.packaging import PackageStockKind
from app.models.sales.ready_stock_service import _reserve_branded_stock
from app.models.workflow_service import notify_department
from app.models.model_images_service import model_print_image_url
from app.schemas import (
    Customer, Model, ProductionOrder, SalesOrder, SalesOrderItem, Shipment, StockReservation, User,
)
from app.schemas.sales.sales_order_persistence import (
    apply_sales_order_header_changes,
    create_sales_order_item,
    create_sales_order_row,
    delete_sales_order_row,
    set_sales_order_total,
    set_sales_order_status,
)


def _attachments_for_storage(
    attachments: Iterable[SalesOrderPrintingAttachment] | None,
) -> list[StoredSalesAttachment]:
    """Persist the bare storage path (no signature) so it never expires at rest."""
    out: list[StoredSalesAttachment] = []
    for a in attachments or []:
        d: StoredSalesAttachment = {
            "file_url": strip_signature(a.file_url) if a.file_url else a.file_url,
            "file_name": a.file_name,
            "content_type": a.content_type,
        }
        out.append(d)
    return out


def _sign_attachment_urls(payload: dict) -> dict:
    """Replace stored bare attachment paths with short-lived signed URLs on the
    way out so the browser can load them in <img> tags."""
    for a in payload.get("printing_attachments") or []:
        if isinstance(a, dict) and a.get("file_url"):
            a["file_url"] = sign_path(a["file_url"])
    return payload


def _customer_name_map(db: Session, customer_ids: set[int]) -> dict[int, str]:
    """Read only the customer names a list payload renders.

    Selecting the two display columns keeps the read bounded by the distinct
    customers on the page, instead of hydrating one full ``Customer`` entity per
    row. A customer whose name is NULL is still a key in the map, so callers can
    tell "no such customer" apart from "customer without a name".
    """
    if not customer_ids:
        return {}
    rows = (
        db.query(Customer.id, Customer.name)
        .filter(Customer.id.in_(sorted({int(customer_id) for customer_id in customer_ids})))
        .all()
    )
    return {int(customer_id): name for customer_id, name in rows}


def _serialize_sales_order(
    db: Session,
    so: SalesOrder,
    *,
    include_items: bool = False,
    customer_names: dict[int, str] | None = None,
) -> dict:
    """Shape sales-order payloads with customer/model names for frontend display."""
    schema_cls = SalesOrderDetail if include_items else SalesOrderOut
    payload = schema_cls.model_validate(so).model_dump()

    customer_id = int(so.customer_id) if so.customer_id else None
    if customer_names is not None:
        # The bounded map is only a lookup: presence decides the shape of
        # `customer`, and the stored name is passed through unchanged.
        customer_found = customer_id is not None and customer_id in customer_names
        customer_name = customer_names.get(customer_id) if customer_found else None
    else:
        customer = db.get(Customer, customer_id) if customer_id else None
        customer_found = customer is not None
        customer_name = customer.name if customer is not None else None
    if customer_found:
        payload["customer_name"] = customer_name
        payload["customer"] = {"id": customer_id, "name": customer_name}
    else:
        payload["customer_name"] = None
        payload["customer"] = None

    _sign_attachment_urls(payload)

    if include_items:
        model_ids = {int(item.model_id) for item in (so.items or []) if item.model_id}
        model_rows = (
            db.query(Model.id, Model.code, Model.name, Model.details_json)
            .filter(Model.id.in_(model_ids))
            .all()
            if model_ids
            else []
        )
        model_map = {
            int(mid): {
                "id": int(mid),
                "code": code,
                "name": name,
                "translations": (details or {}).get("translation") if isinstance(details, dict) else None,
                "composition": (details or {}).get("composition") if isinstance(details, dict) else None,
            }
            for mid, code, name, details in model_rows
        }
        for item in payload.get("items", []):
            model_ref = model_map.get(int(item.get("model_id") or 0))
            item["model_code"] = model_ref["code"] if model_ref else None
            item["model_name"] = model_ref["name"] if model_ref else None
            item["model"] = model_ref

    return payload


def first_grade_options(db: Session):
    candidates = ready_pack_candidates(db, stock_kind=PackageStockKind.FIRST_GRADE)
    models = {m.id: m for m in db.query(Model).filter(Model.id.in_({p.model_id for p, _ in candidates})).all()}
    grouped = {}
    for package, rows in candidates:
        for row in rows:
            key = (row.model_id, row.color, row.size)
            entry = grouped.setdefault(key, {"model_id": row.model_id, "model_code": models[row.model_id].code,
                                             "color": row.color, "size": row.size, "available": 0})
            entry["available"] += row.available_qty
    return list(grouped.values())


def ready_stock_options(db: Session):
    groups: dict[tuple[int, int | None], dict] = {}
    for package, rows in ready_pack_candidates(db):
        brands = {row.brand_id for row in rows}
        brand_id = next(iter(brands)) if len(brands) == 1 else None
        key = (package.model_id, brand_id)
        group = groups.setdefault(key, {"model_id": package.model_id, "brand_id": brand_id, "pack_count": 0, "quantity": 0})
        group["pack_count"] += 1
        group["quantity"] += package.total_quantity
    return list(groups.values())


async def upload_printing_attachment(file: UploadFile):
    ext = extension_for_upload(file, SAFE_IMAGE_EXTENSIONS | SAFE_DOCUMENT_EXTENSIONS)
    if ext in SAFE_IMAGE_EXTENSIONS:
        from app.models.image_storage_service import store_uploaded_image

        stored = await store_uploaded_image(
            file,
            target_dir=settings.SALES_ORDER_FILES_DIR,
            file_url_base="/storage/sales-order-files",
            name_prefix="so_print",
            max_bytes=20 * 1024 * 1024,
        )
        safe_name = stored.file_name
        content_type = stored.content_type
    else:
        os.makedirs(settings.SALES_ORDER_FILES_DIR, exist_ok=True)
        safe_name = f"so_print_{uuid4().hex}{ext}"
        abs_path = os.path.join(settings.SALES_ORDER_FILES_DIR, safe_name)
        content = await read_validated_upload_content(file, ext, 20 * 1024 * 1024)
        with open(abs_path, "wb") as f:
            f.write(content)
        content_type = safe_content_type(ext)
    file_url = f"/storage/sales-order-files/{safe_name}"
    return {
        # Signed for immediate <img> preview; the bare path is what gets stored
        # when the order is saved (create/update strip the signature).
        "file_url": sign_path(file_url),
        "file_name": file.filename or safe_name,
        "content_type": content_type,
    }


def list_sales_orders(
    db: Session,
    status: str | None = None,
    order_type: str | None = None,
    customer_id: int | None = None,
    q: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    page: int = 1,
    page_size: int = 50,
    include_total: bool = False,
):
    qry = db.query(SalesOrder).outerjoin(Customer, Customer.id == SalesOrder.customer_id)
    if status: qry = qry.filter(SalesOrder.status == status)
    if order_type: qry = qry.filter(SalesOrder.order_type == order_type)
    if customer_id: qry = qry.filter(SalesOrder.customer_id == customer_id)
    if q:
        term = q.strip()
        like = f"%{term}%"
        model_code_like = normalized_model_code_pattern(term)
        model_match = (
            db.query(SalesOrderItem.id)
            .join(Model, Model.id == SalesOrderItem.model_id)
            .filter(
                SalesOrderItem.sales_order_id == SalesOrder.id,
                (
                    normalized_model_code_column(Model.code).ilike(model_code_like)
                    | Model.name.ilike(like)
                ),
            )
            .exists()
        )
        qry = qry.filter(
            or_(
                order_reference_contains(SalesOrder.order_no, like),
                SalesOrder.status.ilike(like),
                SalesOrder.order_type.ilike(like),
                Customer.name.ilike(like),
                model_match,
            )
        )
    start, end = date_filter_bounds(created_from, created_to)
    if start: qry = qry.filter(SalesOrder.created_at >= start)
    if end: qry = qry.filter(SalesOrder.created_at <= end)
    total = qry.count() if include_total else 0
    safe_page = max(1, page)
    safe_size = max(1, min(page_size, 500))
    rows = qry.order_by(SalesOrder.id.desc()).offset((safe_page - 1) * safe_size).limit(safe_size).all()
    customer_names = _customer_name_map(db, {so.customer_id for so in rows if so.customer_id})
    # Bound the aggregate to the returned page; never hydrate each order's items.
    # quantity is pieces, not requested_pack_count and not production progress.
    quantities = dict(
        db.query(SalesOrderItem.sales_order_id, func.sum(SalesOrderItem.quantity))
        .filter(SalesOrderItem.sales_order_id.in_([so.id for so in rows]))
        .group_by(SalesOrderItem.sales_order_id)
        .all()
    ) if rows else {}
    typed_rows: list[SalesOrderListRow] = [
        SalesOrderListRow(
            **_serialize_sales_order(db, so, include_items=False, customer_names=customer_names),
            total_quantity=int(quantities.get(so.id, 0)),
        )
        for so in rows
    ]
    # Keep the legacy list/envelope shape for existing direct callers.
    payload = [row.model_dump() for row in typed_rows]
    if include_total:
        return {"rows": payload, "total": total, "page": safe_page, "page_size": safe_size}
    return payload


def create_sales_order(payload: SalesOrderIn, db: Session, current: User) -> SalesOrderDetail:
    if payload.order_type not in (SalesOrderType.CLIENT_ORDER, SalesOrderType.BRANDED_STOCK_SALE):
        raise HTTPException(400, "Invalid order_type")
    if payload.order_type == SalesOrderType.BRANDED_STOCK_SALE and not payload.items:
        raise HTTPException(400, "A Ready stock order must have at least one line")
    grade_lines = [item for item in payload.items if item.source_type == SalesOrderItemSourceType.FIRST_GRADE]
    if grade_lines and (len(grade_lines) != len(payload.items) or payload.order_type != SalesOrderType.BRANDED_STOCK_SALE
                        or any(item.requested_pack_count is not None or is_any_stock_token(item.size)
                               or is_any_stock_token(item.color) or item.printing_required for item in grade_lines)):
        raise HTTPException(400, "FIRST_GRADE_SEPARATE_ORDER")
    pack_order = any(item.requested_pack_count is not None for item in payload.items)
    if pack_order:
        if payload.order_type != SalesOrderType.BRANDED_STOCK_SALE or any(item.requested_pack_count is None for item in payload.items):
            raise HTTPException(400, "Pack counts require a Ready stock order with pack counts on every line")
        if len({item.model_id for item in payload.items}) != len(payload.items):
            raise HTTPException(400, "Use one pack-count line per model variant")
        if any(item.quantity is not None or item.printing_required for item in payload.items):
            raise HTTPException(400, "Ready stock pack quantities come from warehouse packages; printing is not supported")
    elif any(item.quantity is None for item in payload.items):
        raise HTTPException(400, "A piece quantity is required")
    if payload.customer_id and not db.get(Customer, payload.customer_id):
        raise HTTPException(404, "Customer not found")
    so = create_sales_order_row(
        db,
        order_no=next_sales_order_no(db),
        customer_id=payload.customer_id,
        order_type=payload.order_type,
        status=SalesOrderStatus.DRAFT,
        deadline=payload.deadline,
        printing_instructions=payload.printing_instructions,
        printing_attachments=_attachments_for_storage(payload.printing_attachments),
        notes=payload.notes,
        created_by=current.id,
    )
    total = 0.0
    created_lines: list[SalesOrderItem] = []
    selected_model_ids = {int(item.model_id) for item in payload.items}
    selected_models = {
        model.id: model
        for model in db.query(Model).filter(
            Model.id.in_(selected_model_ids),
            Model.catalog_scope == "standard",
        ).all()
    } if selected_model_ids else {}
    for item in payload.items:
        model = selected_models.get(item.model_id)
        if not model:
            raise HTTPException(404, f"Model {item.model_id} not found")
        unit_price = item.unit_price
        if unit_price is None:
            unit_price = float(model.selling_price) if model.selling_price is not None else 0.0
        line = create_sales_order_item(
            db,
            sales_order_id=so.id,
            model_id=item.model_id,
            brand_id=item.brand_id,
            collection_id=item.collection_id,
            color="mixed" if pack_order else item.color,
            size="any" if pack_order else item.size,
            quantity=0 if pack_order else item.quantity,
            requested_pack_count=item.requested_pack_count,
            unit_price=unit_price,
            printing_required=item.printing_required or (
                payload.order_type == SalesOrderType.CLIENT_ORDER
                and bool(model_print_image_url(model))
            ),
            source_type=SalesOrderItemSourceType.FROM_STOCK if pack_order else item.source_type,
            notes=item.notes,
        )
        created_lines.append(line)
        total += float(unit_price) * line.quantity
    set_sales_order_total(db, so, total)
    if payload.order_type == SalesOrderType.BRANDED_STOCK_SALE:
        reservations, shortages = _reserve_branded_stock(
            db,
            so=so,
            current=current,
            lines=created_lines,
            fail_on_shortage=True,
            notify_shortage=False,
            notify_storage_when_ready=True,
        )
        log_action(
            db,
            current,
            "reserve_stock_auto",
            "SalesOrder",
            so.id,
            new_value={"reservations": reservations, "shortages": shortages},
        )
    log_action(db, current, "create", "SalesOrder", so.id, new_value={"order_no": so.order_no})
    db.commit(); db.refresh(so)
    so = db.query(SalesOrder).options(joinedload(SalesOrder.items)).filter(SalesOrder.id == so.id).first()
    return SalesOrderDetail.model_validate(_serialize_sales_order(db, so, include_items=True))


def get_sales_order(sid: int, db: Session):
    so = db.query(SalesOrder).options(joinedload(SalesOrder.items)).filter(SalesOrder.id == sid).first()
    if not so: raise HTTPException(404, "Sales order not found")
    return _serialize_sales_order(db, so, include_items=True)


def update_sales_order(
    sid: int, payload: SalesOrderUpdate, db: Session, current: User
) -> SalesOrderOut:
    """Update sales order header fields. Line items are managed separately."""
    so = db.get(SalesOrder, sid)
    if not so: raise HTTPException(404, "Sales order not found")
    supplied = payload.model_fields_set
    if "status" in supplied:
        supplied_status = payload.status
        if supplied_status is None or supplied_status.value != so.status:
            raise HTTPException(409, "Order status is controlled by workflow commands, not general edits")
        # A full-form resubmission may include the unchanged status. Never write
        # that snapshot back over progress made by another workflow command.
    # Key presence is the supplied/not-supplied signal: an omitted header field
    # stays untouched, an explicit null clears it.
    changes: SalesOrderHeaderChanges = {}
    if "customer_id" in supplied:
        changes["customer_id"] = payload.customer_id
    if "deadline" in supplied:
        changes["deadline"] = payload.deadline
    if "printing_instructions" in supplied:
        changes["printing_instructions"] = payload.printing_instructions
    if "printing_attachments" in supplied:
        changes["printing_attachments"] = _attachments_for_storage(payload.printing_attachments)
    if "notes" in supplied:
        changes["notes"] = payload.notes
    apply_sales_order_header_changes(db, so, changes)
    log_action(db, current, "update", "SalesOrder", so.id)
    db.commit(); db.refresh(so)
    return SalesOrderOut.model_validate(_serialize_sales_order(db, so, include_items=False))


def confirm_sales_order(sid: int, db: Session, current: User):
    so = db.get(SalesOrder, sid)
    if not so: raise HTTPException(404, "Sales order not found")
    if so.status != "draft":
        raise HTTPException(400, f"Cannot confirm order in status '{so.status}'")
    set_sales_order_status(db, so, SalesOrderStatus.CONFIRMED)
    notify_department(
        db,
        department_code="PLN",
        title=f"Sales order {so.order_no} sent to planning",
        message="Planning can create the production order now.",
        link=f"/planning?so_id={so.id}",
        exclude_user_id=current.id,
    )
    log_action(db, current, "confirm", "SalesOrder", so.id)
    db.commit(); db.refresh(so)
    return _serialize_sales_order(db, so, include_items=False)


def reserve_stock(
    sid: int,
    db: Session,
    current: User,
    idempotency_key: str | None = None,
) -> SalesStockReservationOut:
    """For branded_stock_sale: try to reserve from FinishedGoodsStock for each line."""
    fingerprint_payload = {"sales_order_id": sid}
    replay = replay_idempotent_response(db, scope="sales.reserve-stock", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return SalesStockReservationOut.model_validate(replay)

    so = db.get(SalesOrder, sid)
    if not so: raise HTTPException(404, "Sales order not found")
    if so.order_type != "branded_stock_sale":
        raise HTTPException(400, "Reservation only applies to branded stock sales")

    reservations, shortages = _reserve_branded_stock(
        db,
        so=so,
        current=current,
        fail_on_shortage=False,
        notify_shortage=True,
        notify_storage_when_ready=True,
    )
    log_action(db, current, "reserve_stock", "SalesOrder", so.id, new_value={"reservations": reservations, "shortages": shortages})
    response = SalesStockReservationOut.model_validate({"reservations": reservations, "shortages": shortages})
    store_idempotent_response(
        db,
        scope="sales.reserve-stock",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response.model_dump(mode="json"),
        user=current,
    )
    db.commit()
    return response


def delete_sales_order(sid: int, db: Session, current: User):
    so = db.get(SalesOrder, sid)
    if not so:
        raise HTTPException(404, "Sales order not found")

    if so.status not in (SalesOrderStatus.DRAFT.value, SalesOrderStatus.CANCELLED.value):
        raise HTTPException(409, "Only draft or cancelled sales orders can be deleted")
    if db.query(ProductionOrder).filter(ProductionOrder.sales_order_id == sid).first():
        raise HTTPException(409, "Sales order already has linked production orders")
    if db.query(Shipment).filter(Shipment.sales_order_id == sid).first():
        raise HTTPException(409, "Sales order already has linked shipments")
    if db.query(StockReservation).filter(StockReservation.sales_order_id == sid).first():
        raise HTTPException(409, "Sales order already has stock reservations")

    delete_sales_order_row(db, so)
    log_action(db, current, "delete", "SalesOrder", sid, new_value={"order_no": so.order_no})
    db.commit()
