from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    Item,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequest,
    PurchaseRequestLine,
    SalesOrder,
    StockBatch,
    StockMovement,
    Supplier,
    User,
    Warehouse,
    ProductionOrder,
)
from app.services.audit import log_action
from app.services.material_rolls import normalize_material_roll_weights
from app.services.numbering import next_purchase_order_no, next_purchase_request_no
from app.services.planning import material_requirements_for_sales_order
from app.services.workflow import notify_department

REQUEST_CREATE_STATUSES = {"draft", "pending_approval"}
REQUEST_APPROVABLE_STATUSES = {"draft", "pending_approval"}
REQUEST_REJECTABLE_STATUSES = {"draft", "pending_approval", "approved"}
ORDER_CREATE_STATUSES = {"draft", "sent"}
ORDER_RECEIVABLE_STATUSES = {"sent", "approved", "partially_received"}


def _num(value) -> float:
    return float(value or 0)


def _require_item(db: Session, item_id: int) -> Item:
    item = db.get(Item, item_id)
    if not item:
        raise HTTPException(404, f"Item {item_id} not found")
    return item


def _require_supplier(db: Session, supplier_id: int | None) -> Supplier | None:
    if supplier_id is None:
        return None
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(404, f"Supplier {supplier_id} not found")
    return supplier


def _require_warehouse(db: Session, warehouse_id: int | None) -> Warehouse:
    if not warehouse_id:
        raise HTTPException(400, "warehouse_id is required")
    warehouse = db.get(Warehouse, warehouse_id)
    if not warehouse:
        raise HTTPException(404, f"Warehouse {warehouse_id} not found")
    return warehouse


def create_purchase_request(db: Session, *, data: dict, current: User) -> PurchaseRequest:
    status = str(data.get("status") or "pending_approval").strip() or "pending_approval"
    if status not in REQUEST_CREATE_STATUSES:
        raise HTTPException(400, "Purchase request status must be draft or pending_approval")

    sales_order_id = data.get("sales_order_id")
    production_order_id = data.get("production_order_id")
    if sales_order_id and not db.get(SalesOrder, int(sales_order_id)):
        raise HTTPException(404, "Sales order not found")
    if production_order_id and not db.get(ProductionOrder, int(production_order_id)):
        raise HTTPException(404, "Production order not found")

    line_inputs = data.get("lines") or []
    if not line_inputs:
        raise HTTPException(400, "At least one purchase request line is required")

    request = PurchaseRequest(
        request_no=next_purchase_request_no(db),
        status=status,
        sales_order_id=sales_order_id,
        production_order_id=production_order_id,
        requested_by=current.id,
        notes=data.get("notes"),
    )
    db.add(request)
    db.flush()

    for raw in line_inputs:
        item = _require_item(db, int(raw.get("item_id") or 0))
        preferred_supplier_id = raw.get("preferred_supplier_id")
        _require_supplier(db, int(preferred_supplier_id) if preferred_supplier_id else None)

        required_quantity = _num(raw.get("required_quantity"))
        available_quantity = _num(raw.get("available_quantity"))
        shortage_quantity = (
            _num(raw.get("shortage_quantity"))
            if raw.get("shortage_quantity") is not None
            else max(0.0, required_quantity - available_quantity)
        )
        requested_quantity = (
            _num(raw.get("requested_quantity"))
            if raw.get("requested_quantity") is not None
            else (shortage_quantity if shortage_quantity > 0 else required_quantity)
        )
        if requested_quantity < 0:
            raise HTTPException(400, "Requested quantity cannot be negative")

        unit = str(raw.get("unit") or item.unit or "").strip() or item.unit
        db.add(
            PurchaseRequestLine(
                purchase_request_id=request.id,
                item_id=item.id,
                required_quantity=required_quantity,
                requested_quantity=requested_quantity,
                unit=unit,
                available_quantity=available_quantity,
                shortage_quantity=shortage_quantity,
                preferred_supplier_id=preferred_supplier_id,
                material_name=str(raw.get("material_name") or item.name or "").strip() or item.name,
                photo_url=str(raw.get("photo_url") or item.image_url or "").strip() or None,
                notes=raw.get("notes"),
            )
        )

    db.flush()
    log_action(
        db,
        current,
        "create",
        "PurchaseRequest",
        request.id,
        new_value={"request_no": request.request_no, "status": request.status, "line_count": len(line_inputs)},
    )
    notify_department(
        db,
        department_code="ADM",
        title=f"Purchase request awaiting approval: {request.request_no}",
        message=f"{len(line_inputs)} line(s) need manager approval.",
        link="/purchasing",
        exclude_user_id=current.id,
    )
    return request


def create_purchase_request_from_sales_order(db: Session, *, sales_order_id: int, current: User) -> PurchaseRequest:
    sales_order = db.get(SalesOrder, sales_order_id)
    if not sales_order:
        raise HTTPException(404, "Sales order not found")

    requirement_rows = material_requirements_for_sales_order(db, sales_order_id)
    shortage_lines = []
    for row in requirement_rows:
        shortage = _num(row.get("shortage"))
        if shortage <= 1e-9:
            continue
        shortage_lines.append(
            {
                "item_id": int(row["item_id"]),
                "required_quantity": _num(row.get("required_quantity")),
                "requested_quantity": shortage,
                "unit": row.get("unit"),
                "available_quantity": _num(row.get("available_quantity")),
                "shortage_quantity": shortage,
            }
        )

    if not shortage_lines:
        raise HTTPException(400, "No material shortages found for this sales order")

    return create_purchase_request(
        db,
        data={
            "sales_order_id": sales_order_id,
            "status": "pending_approval",
            "notes": f"Auto-created from material shortages for {sales_order.order_no}",
            "lines": shortage_lines,
        },
        current=current,
    )


def approve_purchase_request(db: Session, *, request_id: int, data: dict, current: User) -> PurchaseRequest:
    request = db.get(PurchaseRequest, request_id)
    if not request:
        raise HTTPException(404, "Purchase request not found")
    if request.status == "approved":
        return request
    if request.status not in REQUEST_APPROVABLE_STATUSES:
        raise HTTPException(409, f"Cannot approve purchase request in status '{request.status}'")

    approval_lines = data.get("lines") or []
    lines_by_id = {int(line.id): line for line in request.lines}
    if len(approval_lines) != len(lines_by_id):
        raise HTTPException(400, "Photo, material name, and supplier are required for every request line")
    seen: set[int] = set()
    for raw in approval_lines:
        line_id = int(raw.get("purchase_request_line_id") or 0)
        line = lines_by_id.get(line_id)
        if not line or line_id in seen:
            raise HTTPException(400, "Approval lines must match the purchase request")
        seen.add(line_id)
        material_name = str(raw.get("material_name") or "").strip()
        photo_url = str(raw.get("photo_url") or "").strip()
        supplier_id = int(raw.get("preferred_supplier_id") or 0)
        if not material_name or not photo_url or not supplier_id:
            raise HTTPException(400, "Photo, material name, and supplier are required for every request line")
        _require_supplier(db, supplier_id)
        line.material_name = material_name
        line.photo_url = photo_url
        line.preferred_supplier_id = supplier_id

    old_status = request.status
    request.status = "approved"
    request.approved_by = current.id
    request.approved_at = datetime.now(timezone.utc)
    log_action(
        db,
        current,
        "approve",
        "PurchaseRequest",
        request.id,
        old_value={"status": old_status},
        new_value={"status": request.status, "request_no": request.request_no},
    )
    notify_department(
        db,
        department_code="PLN",
        title=f"Purchase request approved: {request.request_no}",
        message="The request is approved and can be converted to a purchase order.",
        link="/purchasing",
        exclude_user_id=current.id,
    )
    return request


def reject_purchase_request(db: Session, *, request_id: int, current: User) -> PurchaseRequest:
    request = db.get(PurchaseRequest, request_id)
    if not request:
        raise HTTPException(404, "Purchase request not found")
    if request.status not in REQUEST_REJECTABLE_STATUSES:
        raise HTTPException(409, f"Cannot reject purchase request in status '{request.status}'")

    old_status = request.status
    request.status = "rejected"
    log_action(
        db,
        current,
        "reject",
        "PurchaseRequest",
        request.id,
        old_value={"status": old_status},
        new_value={"status": request.status, "request_no": request.request_no},
    )
    return request


def create_purchase_order(db: Session, *, data: dict, current: User) -> PurchaseOrder:
    purchase_request_id = data.get("purchase_request_id")
    request = db.get(PurchaseRequest, int(purchase_request_id)) if purchase_request_id else None
    if purchase_request_id and not request:
        raise HTTPException(404, "Purchase request not found")

    supplier_id = data.get("supplier_id")
    _require_supplier(db, int(supplier_id) if supplier_id else None)

    line_inputs = data.get("lines") or []
    if not line_inputs:
        raise HTTPException(400, "At least one purchase order line is required")

    order = PurchaseOrder(
        po_no=next_purchase_order_no(db),
        purchase_request_id=purchase_request_id,
        supplier_id=supplier_id,
        status=str(data.get("status") or "draft"),
        ordered_by=current.id,
        expected_date=data.get("expected_date"),
        notes=data.get("notes"),
    )
    if order.status not in ORDER_CREATE_STATUSES:
        raise HTTPException(400, "Purchase order status must be draft or sent")
    db.add(order)
    db.flush()

    for raw in line_inputs:
        item = _require_item(db, int(raw.get("item_id") or 0))
        ordered_quantity = _num(raw.get("ordered_quantity"))
        if ordered_quantity <= 0:
            raise HTTPException(400, "Ordered quantity must be greater than zero")
        warehouse_id = raw.get("warehouse_id")
        if warehouse_id:
            _require_warehouse(db, int(warehouse_id))
        unit = str(raw.get("unit") or item.unit or "").strip() or item.unit
        line_supplier_id = raw.get("supplier_id") or supplier_id
        _require_supplier(db, int(line_supplier_id) if line_supplier_id else None)
        db.add(
            PurchaseOrderLine(
                purchase_order_id=order.id,
                item_id=item.id,
                ordered_quantity=ordered_quantity,
                received_quantity=0,
                unit=unit,
                unit_cost=_num(raw.get("unit_cost")),
                warehouse_id=warehouse_id,
                supplier_id=line_supplier_id,
                material_name=str(raw.get("material_name") or item.name or "").strip() or item.name,
                photo_url=str(raw.get("photo_url") or item.image_url or "").strip() or None,
                notes=raw.get("notes"),
            )
        )

    db.flush()
    log_action(
        db,
        current,
        "create",
        "PurchaseOrder",
        order.id,
        new_value={"po_no": order.po_no, "request_no": request.request_no if request else None, "line_count": len(line_inputs)},
    )
    notify_department(
        db,
        department_code="STR",
        title=f"Purchase order ready for receiving: {order.po_no}",
        message=f"{len(line_inputs)} line(s) are pending warehouse receiving.",
        link="/purchasing/receiving",
        exclude_user_id=current.id,
    )
    return order


def convert_purchase_request_to_order(db: Session, *, request_id: int, data: dict, current: User) -> PurchaseOrder:
    request = db.get(PurchaseRequest, request_id)
    if not request:
        raise HTTPException(404, "Purchase request not found")
    if request.status != "approved":
        raise HTTPException(409, f"Only approved purchase requests can be converted (current: '{request.status}')")
    if not request.lines:
        raise HTTPException(400, "Purchase request has no lines")

    expected_date = data.get("expected_date")
    if not expected_date:
        raise HTTPException(400, "Expected date is required")
    quantity_inputs = data.get("lines") or []
    request_lines_by_id = {int(line.id): line for line in request.lines}
    if len(quantity_inputs) != len(request_lines_by_id):
        raise HTTPException(400, "Order quantity is required for every request line")
    ordered_by_line_id: dict[int, float] = {}
    for raw in quantity_inputs:
        line_id = int(raw.get("purchase_request_line_id") or 0)
        if line_id not in request_lines_by_id or line_id in ordered_by_line_id:
            raise HTTPException(400, "Order lines must match the approved purchase request")
        quantity = _num(raw.get("ordered_quantity"))
        if quantity <= 0:
            raise HTTPException(400, "Ordered quantity must be greater than zero")
        ordered_by_line_id[line_id] = quantity

    supplier_ids = {
        int(line.preferred_supplier_id)
        for line in request.lines
        if line.preferred_supplier_id
    }
    supplier_id = next(iter(supplier_ids)) if len(supplier_ids) == 1 else None
    order = create_purchase_order(
        db,
        data={
            "purchase_request_id": request.id,
            "supplier_id": supplier_id,
            "status": "sent",
            "expected_date": expected_date,
            "notes": f"Converted from {request.request_no}",
            "lines": [
                {
                    "item_id": line.item_id,
                    "ordered_quantity": ordered_by_line_id[int(line.id)],
                    "unit": line.unit,
                    "supplier_id": line.preferred_supplier_id,
                    "material_name": line.material_name or line.item_name,
                    "photo_url": line.photo_url,
                    "unit_cost": 0,
                    "warehouse_id": None,
                    "notes": line.notes,
                }
                for line in request.lines
            ],
        },
        current=current,
    )
    old_status = request.status
    request.status = "converted"
    log_action(
        db,
        current,
        "convert_to_order",
        "PurchaseRequest",
        request.id,
        old_value={"status": old_status},
        new_value={"status": request.status, "request_no": request.request_no, "po_no": order.po_no},
    )
    return order


def _purchase_order_status(order: PurchaseOrder) -> str:
    if not order.lines:
        return order.status
    if all(_num(line.received_quantity) >= _num(line.ordered_quantity) - 1e-9 for line in order.lines):
        return "received"
    if any(_num(line.received_quantity) > 1e-9 for line in order.lines):
        return "partially_received"
    return order.status


def receive_purchase_order(db: Session, *, order_id: int, data: dict, current: User) -> PurchaseOrder:
    order = db.get(PurchaseOrder, order_id)
    if not order:
        raise HTTPException(404, "Purchase order not found")
    if order.status not in ORDER_RECEIVABLE_STATUSES:
        raise HTTPException(409, f"Cannot receive a purchase order in status '{order.status}'")

    line_inputs = data.get("lines") or []
    if not line_inputs:
        raise HTTPException(400, "At least one receive line is required")

    order_lines_by_id = {int(line.id): line for line in order.lines}
    default_supplier_id = data.get("supplier_id") or order.supplier_id
    _require_supplier(db, int(default_supplier_id) if default_supplier_id else None)
    old_status = order.status

    for raw in line_inputs:
        line_id = int(raw.get("purchase_order_line_id") or 0)
        line = order_lines_by_id.get(line_id)
        if not line:
            raise HTTPException(404, f"Purchase order line {line_id} not found")

        quantity = _num(raw.get("received_quantity"))
        if quantity <= 0:
            raise HTTPException(400, "Received quantity must be greater than zero")

        batch_no = str(raw.get("batch_no") or "").strip()
        if not batch_no:
            raise HTTPException(400, "batch_no is required")

        warehouse_id = raw.get("warehouse_id") or line.warehouse_id
        _require_warehouse(db, int(warehouse_id) if warehouse_id else None)
        supplier_id = raw.get("supplier_id") or line.supplier_id or default_supplier_id
        _require_supplier(db, int(supplier_id) if supplier_id else None)

        item = _require_item(db, int(line.item_id))
        unit = str(line.unit or item.unit or "").strip() or item.unit
        cost_per_unit = _num(raw.get("cost_per_unit")) if raw.get("cost_per_unit") is not None else _num(line.unit_cost)
        roll_weights, piece_count = normalize_material_roll_weights(
            item_category=item.category,
            unit=unit,
            quantity=quantity,
            roll_weights_kg=raw.get("roll_weights_kg"),
            piece_count=raw.get("piece_count"),
        )

        batch = StockBatch(
            item_id=item.id,
            batch_no=batch_no,
            internal_batch_no=order.po_no,
            supplier_id=supplier_id,
            color=raw.get("color"),
            old_code=raw.get("old_code"),
            color_code=raw.get("color_code"),
            color_status=raw.get("color_status"),
            order_no=raw.get("order_no") or order.po_no,
            width=raw.get("width"),
            gsm=raw.get("gsm"),
            quantity=quantity,
            piece_count=piece_count,
            roll_weights_kg=roll_weights,
            processes=raw.get("processes") or f"Purchase order {order.po_no}",
            unit=unit,
            cost_per_unit=cost_per_unit,
            image_url=str(line.photo_url or item.image_url or "").strip() or None,
            warehouse_id=warehouse_id,
            qc_status=raw.get("qc_status") or "passed",
        )
        db.add(batch)
        db.flush()

        movement = StockMovement(
            movement_type="receive",
            item_id=item.id,
            batch_id=batch.id,
            to_warehouse_id=warehouse_id,
            quantity=quantity,
            unit=unit,
            reference_type="PurchaseOrderLine",
            reference_id=line.id,
            created_by=current.id,
        )
        db.add(movement)
        line.received_quantity = _num(line.received_quantity) + quantity
        if raw.get("cost_per_unit") is not None:
            line.unit_cost = cost_per_unit
        if not line.warehouse_id:
            line.warehouse_id = warehouse_id

        log_action(
            db,
            current,
            "receive",
            "StockBatch",
            batch.id,
            new_value={
                "batch_no": batch.batch_no,
                "internal_batch_no": batch.internal_batch_no,
                "po_no": order.po_no,
                "qty": quantity,
            },
        )
        log_action(
            db,
            current,
            "receive_purchase_order_line",
            "PurchaseOrderLine",
            line.id,
            new_value={
                "po_no": order.po_no,
                "batch_no": batch.batch_no,
                "internal_batch_no": batch.internal_batch_no,
                "item_id": item.id,
                "received_quantity": quantity,
                "total_received": float(line.received_quantity or 0),
            },
        )

    close_order = bool(data.get("close_order"))
    remaining_quantity = sum(
        max(0.0, _num(line.ordered_quantity) - _num(line.received_quantity))
        for line in order.lines
    )
    new_status = "received" if close_order else _purchase_order_status(order)
    if new_status != old_status:
        order.status = new_status
        new_value = {"status": new_status, "po_no": order.po_no}
        if close_order and remaining_quantity > 1e-9:
            new_value.update({
                "short_receipt_closed": True,
                "remaining_quantity_cancelled": remaining_quantity,
            })
        log_action(
            db,
            current,
            "update_status",
            "PurchaseOrder",
            order.id,
            old_value={"status": old_status},
            new_value=new_value,
        )

    db.flush()
    return order
