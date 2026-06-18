import os
from collections import defaultdict
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Depends
from fastapi import UploadFile, File
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.core.config import settings
from app.core.signing import sign_path, strip_signature
from app.core.uploads import (
    SAFE_DOCUMENT_EXTENSIONS,
    SAFE_IMAGE_EXTENSIONS,
    extension_for_upload,
    safe_content_type,
    read_validated_upload_content,
)
from app.models import (
    SalesOrder, SalesOrderItem, FinishedGoodsStock, StockReservation,
    Customer, Model, User, ProductionOrder, WorkOrder,
    CuttingRecord, PrintingRecord, SewingRecord, PackagingRecord, Shipment, ShipmentPackage,
    Task, Department, Invoice, Payment, StockMovement, Item, StockBatch, Package, AuditLog,
)
from app.schemas.sales import (
    SalesOrderIn, SalesOrderUpdate, SalesOrderOut, SalesOrderDetail,
)
from app.services.audit import log_action
from app.services.finished_goods import repair_missing_brand_metadata
from app.services.numbering import next_sales_order_no
from app.services.numbering import next_invoice_no
from app.services.workflow import notify_department

router = APIRouter(prefix="/sales-orders", tags=["sales"])


def _attachments_for_storage(attachments) -> list[dict]:
    """Persist the bare storage path (no signature) so it never expires at rest."""
    out: list[dict] = []
    for a in attachments or []:
        d = a.model_dump() if hasattr(a, "model_dump") else dict(a)
        if d.get("file_url"):
            d["file_url"] = strip_signature(d["file_url"])
        out.append(d)
    return out


def _sign_attachment_urls(payload: dict) -> dict:
    """Replace stored bare attachment paths with short-lived signed URLs on the
    way out so the browser can load them in <img> tags."""
    for a in payload.get("printing_attachments") or []:
        if isinstance(a, dict) and a.get("file_url"):
            a["file_url"] = sign_path(a["file_url"])
    return payload


def _serialize_sales_order(
    db: DbSession,
    so: SalesOrder,
    *,
    include_items: bool = False,
) -> dict:
    """Shape sales-order payloads with customer/model names for frontend display."""
    schema_cls = SalesOrderDetail if include_items else SalesOrderOut
    payload = schema_cls.model_validate(so).model_dump()

    customer = db.get(Customer, so.customer_id) if so.customer_id else None
    if customer:
        payload["customer_name"] = customer.name
        payload["customer"] = {"id": customer.id, "name": customer.name}
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
            }
            for mid, code, name, details in model_rows
        }
        for item in payload.get("items", []):
            model_ref = model_map.get(int(item.get("model_id") or 0))
            item["model_code"] = model_ref["code"] if model_ref else None
            item["model_name"] = model_ref["name"] if model_ref else None
            item["model"] = model_ref

    return payload


def _num(value) -> float:
    return float(value or 0)


def _int_qty(value) -> int:
    return int(_num(value))


def _history_event(event_type: str, title: str, at: datetime | None, **meta) -> dict | None:
    if not at:
        return None
    return {
        "type": event_type,
        "title": title,
        "at": at,
        "meta": {k: v for k, v in meta.items() if v is not None},
    }


def _event_sort_key(row: dict) -> str:
    at = row.get("at")
    return at.isoformat() if hasattr(at, "isoformat") else str(at or "")


def _latest_datetime(values: list[datetime | None]) -> datetime | None:
    present = [v for v in values if v]
    if not present:
        return None
    return sorted(present, key=lambda v: v.isoformat())[-1]


def _model_refs(db: DbSession, model_ids: set[int]) -> dict[int, dict]:
    if not model_ids:
        return {}
    rows = (
        db.query(Model.id, Model.code, Model.name, Model.details_json)
        .filter(Model.id.in_(model_ids))
        .all()
    )
    return {
        int(mid): {
            "id": int(mid),
            "code": code,
            "name": name,
            "translations": (details or {}).get("translation") if isinstance(details, dict) else None,
        }
        for mid, code, name, details in rows
    }


def _sales_order_history(db: DbSession, so: SalesOrder, *, include_detail: bool = False) -> dict:
    sales_items = (
        db.query(SalesOrderItem)
        .filter(SalesOrderItem.sales_order_id == so.id)
        .order_by(SalesOrderItem.id.asc())
        .all()
    )
    production_orders = (
        db.query(ProductionOrder)
        .options(
            joinedload(ProductionOrder.items),
            joinedload(ProductionOrder.batches),
            joinedload(ProductionOrder.work_orders),
        )
        .filter(ProductionOrder.sales_order_id == so.id)
        .order_by(ProductionOrder.id.asc())
        .all()
    )
    po_ids = [int(po.id) for po in production_orders]
    work_orders = sorted(
        [wo for po in production_orders for wo in (po.work_orders or [])],
        key=lambda wo: (int(wo.production_batch_id or 0), str(wo.operation or ""), int(wo.id)),
    )
    work_order_ids = [int(wo.id) for wo in work_orders]

    if work_order_ids:
        cutting_records = (
            db.query(CuttingRecord)
            .filter(CuttingRecord.work_order_id.in_(work_order_ids))
            .order_by(CuttingRecord.id.asc())
            .all()
        )
        printing_records = (
            db.query(PrintingRecord)
            .filter(PrintingRecord.work_order_id.in_(work_order_ids))
            .order_by(PrintingRecord.id.asc())
            .all()
        )
        sewing_records = (
            db.query(SewingRecord)
            .filter(SewingRecord.work_order_id.in_(work_order_ids))
            .order_by(SewingRecord.id.asc())
            .all()
        )
        packaging_records = (
            db.query(PackagingRecord)
            .filter(PackagingRecord.work_order_id.in_(work_order_ids))
            .order_by(PackagingRecord.id.asc())
            .all()
        )
    else:
        cutting_records = []
        printing_records = []
        sewing_records = []
        packaging_records = []

    package_filters = [Package.sales_order_id == so.id]
    if po_ids:
        package_filters.append(Package.production_order_id.in_(po_ids))
    packages = (
        db.query(Package)
        .options(joinedload(Package.items))
        .filter(or_(*package_filters))
        .order_by(Package.id.asc())
        .all()
    )
    package_ids = [int(pkg.id) for pkg in packages]

    shipments = (
        db.query(Shipment)
        .options(joinedload(Shipment.packages))
        .filter(Shipment.sales_order_id == so.id)
        .order_by(Shipment.id.asc())
        .all()
    )
    shipment_ids = {int(sh.id) for sh in shipments}
    package_shipment_rows = (
        db.query(ShipmentPackage)
        .filter(ShipmentPackage.package_id.in_(package_ids))
        .order_by(ShipmentPackage.id.asc())
        .all()
        if package_ids
        else []
    )
    shipment_ids.update(int(row.shipment_id) for row in package_shipment_rows)
    missing_shipment_ids = shipment_ids - {int(sh.id) for sh in shipments}
    if missing_shipment_ids:
        shipments.extend(
            db.query(Shipment)
            .options(joinedload(Shipment.packages))
            .filter(Shipment.id.in_(missing_shipment_ids))
            .order_by(Shipment.id.asc())
            .all()
        )
    shipment_ids = {int(sh.id) for sh in shipments}
    if shipment_ids:
        shipment_package_rows = (
            db.query(ShipmentPackage)
            .filter(ShipmentPackage.shipment_id.in_(shipment_ids))
            .order_by(ShipmentPackage.id.asc())
            .all()
        )
    else:
        shipment_package_rows = []
    if package_ids:
        order_package_ids = set(package_ids)
        shipment_package_rows = [row for row in shipment_package_rows if int(row.package_id) in order_package_ids]

    invoices = (
        db.query(Invoice)
        .filter(Invoice.sales_order_id == so.id)
        .order_by(Invoice.id.asc())
        .all()
    )
    invoice_ids = [int(inv.id) for inv in invoices]
    payments = (
        db.query(Payment)
        .filter(Payment.invoice_id.in_(invoice_ids))
        .order_by(Payment.paid_at.desc().nullslast(), Payment.id.desc())
        .all()
        if invoice_ids
        else []
    )

    movement_filters = []
    cutting_ids = [int(row.id) for row in cutting_records]
    packaging_record_ids = [int(row.id) for row in packaging_records]
    if cutting_ids:
        movement_filters.append((StockMovement.reference_type == "CuttingRecord") & StockMovement.reference_id.in_(cutting_ids))
    if packaging_record_ids:
        movement_filters.append((StockMovement.reference_type == "PackagingRecord") & StockMovement.reference_id.in_(packaging_record_ids))
    if po_ids:
        movement_filters.append((StockMovement.reference_type == "ProductionOrder") & StockMovement.reference_id.in_(po_ids))
    movement_filters.append((StockMovement.reference_type == "SalesOrder") & (StockMovement.reference_id == so.id))
    movement_rows = (
        db.query(StockMovement, Item, StockBatch)
        .join(Item, Item.id == StockMovement.item_id)
        .outerjoin(StockBatch, StockBatch.id == StockMovement.batch_id)
        .filter(or_(*movement_filters))
        .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
        .all()
    )

    ordered_qty = sum(_int_qty(item.quantity) for item in sales_items)
    planned_qty = sum(_int_qty(po.planned_quantity) for po in production_orders)
    cut_qty = sum(_int_qty(row.cut_pieces) for row in cutting_records)
    cut_passed_qty = sum(_int_qty(row.passed_pieces) for row in cutting_records)
    printed_qty = sum(_int_qty(row.printed_qty) for row in printing_records)
    sewn_qty = sum(_int_qty(row.sewn_qty) for row in sewing_records)
    sewn_passed_qty = sum(_int_qty(row.passed_qty) for row in sewing_records)
    packed_record_qty = sum(_int_qty(row.total_packed_quantity or row.packed_qty) for row in packaging_records)
    packaged_qty = sum(_int_qty(pkg.total_quantity) for pkg in packages)
    shipped_qty = sum(_int_qty(row.quantity) for row in shipment_package_rows)
    invoice_total = sum(_num(inv.amount) for inv in invoices)
    paid_total = sum(_num(payment.amount) for payment in payments)

    material_by_key: dict[tuple[int, str], dict] = {}
    material_movements: list[dict] = []
    material_cost_total = 0.0
    for movement, item, batch in movement_rows:
        qty = _num(movement.quantity)
        unit = movement.unit or item.unit
        unit_cost = _num(batch.cost_per_unit if batch else item.default_cost)
        cost = qty * unit_cost
        material_cost_total += cost
        key = (int(item.id), unit)
        bucket = material_by_key.setdefault(
            key,
            {
                "item_id": int(item.id),
                "sku": item.sku,
                "name": item.name,
                "category": item.category,
                "unit": unit,
                "quantity": 0.0,
                "estimated_cost": 0.0,
            },
        )
        bucket["quantity"] += qty
        bucket["estimated_cost"] += cost
        material_movements.append(
            {
                "id": movement.id,
                "movement_type": movement.movement_type,
                "quantity": qty,
                "unit": unit,
                "estimated_cost": cost,
                "reference_type": movement.reference_type,
                "reference_id": movement.reference_id,
                "created_at": movement.created_at,
                "item": {
                    "id": item.id,
                    "sku": item.sku,
                    "name": item.name,
                    "category": item.category,
                },
                "batch": {
                    "id": batch.id,
                    "batch_no": batch.batch_no,
                    "cost_per_unit": _num(batch.cost_per_unit),
                } if batch else None,
            }
        )
    materials_spent = sorted(material_by_key.values(), key=lambda row: (str(row["category"]), str(row["sku"])))

    done_markers = (
        [sh.delivered_at for sh in shipments]
        + [sh.shipped_at for sh in shipments]
        + [pkg.shipped_at or pkg.received_at or pkg.packed_at for pkg in packages]
        + [wo.end_time for wo in work_orders if str(wo.status or "") in {"completed", "done", "closed"}]
    )
    is_done = (
        str(so.status or "") in {"completed", "closed", "delivered", "shipped"}
        or (ordered_qty > 0 and max(packaged_qty, shipped_qty) >= ordered_qty)
    )
    completed_at = _latest_datetime(done_markers) if is_done else None
    last_activity_at = _latest_datetime(
        [so.updated_at, so.created_at, so.planning_estimate_submitted_at]
        + [po.updated_at or po.created_at for po in production_orders]
        + [wo.end_time or wo.start_time or wo.updated_at or wo.created_at for wo in work_orders]
        + [pkg.shipped_at or pkg.received_at or pkg.packed_at or pkg.updated_at or pkg.created_at for pkg in packages]
        + [sh.delivered_at or sh.shipped_at or sh.updated_at or sh.created_at for sh in shipments]
        + [inv.issued_at or inv.updated_at or inv.created_at for inv in invoices]
        + [payment.paid_at or payment.updated_at or payment.created_at for payment in payments]
    )

    summary = {
        "ordered_qty": ordered_qty,
        "planned_qty": planned_qty,
        "cut_qty": cut_qty,
        "cut_passed_qty": cut_passed_qty,
        "printed_qty": printed_qty,
        "sewn_qty": sewn_qty,
        "sewn_passed_qty": sewn_passed_qty,
        "packed_record_qty": packed_record_qty,
        "packaged_qty": packaged_qty,
        "shipped_qty": shipped_qty,
        "package_count": len(packages),
        "shipment_count": len(shipments),
        "invoice_count": len(invoices),
        "payment_count": len(payments),
        "order_amount": _num(so.total_amount),
        "invoice_total": invoice_total,
        "paid_total": paid_total,
        "outstanding_amount": max(_num(so.total_amount) - paid_total, 0),
        "material_spent_cost": material_cost_total,
        "material_spent": materials_spent,
        "ordered_at": so.created_at,
        "completed_at": completed_at,
        "last_activity_at": last_activity_at,
    }

    row = {
        "id": so.id,
        "order_no": so.order_no,
        "customer_id": so.customer_id,
        "customer_name": None,
        "order_type": so.order_type,
        "status": so.status,
        "deadline": so.deadline,
        "created_at": so.created_at,
        "updated_at": so.updated_at,
        "completed_at": completed_at,
        "last_activity_at": last_activity_at,
        "total_amount": _num(so.total_amount),
        "summary": summary,
    }
    customer = db.get(Customer, so.customer_id) if so.customer_id else None
    if customer:
        row["customer_name"] = customer.name

    if not include_detail:
        return row

    model_ids = {int(item.model_id) for item in sales_items if item.model_id}
    for po in production_orders:
        model_ids.add(int(po.model_id))
        model_ids.update(int(item.model_id) for item in (po.items or []) if item.model_id)
    for pkg in packages:
        model_ids.add(int(pkg.model_id))
        model_ids.update(int(item.model_id) for item in (pkg.items or []) if item.model_id)
    model_map = _model_refs(db, model_ids)

    audit_rows = (
        db.query(AuditLog, User)
        .outerjoin(User, User.id == AuditLog.user_id)
        .filter(AuditLog.entity_type == "SalesOrder", AuditLog.entity_id == so.id)
        .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        .all()
    )
    timeline = [
        _history_event("order_created", "Order created", so.created_at, order_no=so.order_no),
        _history_event("planning_estimate", "Planning estimate submitted", so.planning_estimate_submitted_at),
    ]
    for po in production_orders:
        timeline.append(_history_event("production_order", f"Production {so.order_no}", po.created_at, production_order_id=po.id, status=po.status))
    for wo in work_orders:
        if wo.start_time:
            timeline.append(_history_event("work_order_started", f"{wo.operation.title()} started", wo.start_time, work_order_id=wo.id, status=wo.status))
        if wo.end_time:
            timeline.append(_history_event("work_order_done", f"{wo.operation.title()} done", wo.end_time, work_order_id=wo.id, status=wo.status))
    for pkg in packages:
        timeline.append(_history_event("package_packed", f"Package {pkg.package_no} packed", pkg.packed_at, package_id=pkg.id, quantity=pkg.total_quantity))
        timeline.append(_history_event("package_received", f"Package {pkg.package_no} received", pkg.received_at, package_id=pkg.id))
        timeline.append(_history_event("package_shipped", f"Package {pkg.package_no} shipped", pkg.shipped_at, package_id=pkg.id))
    for sh in shipments:
        timeline.append(_history_event("shipment_shipped", f"Shipment {sh.shipment_no} shipped", sh.shipped_at, shipment_id=sh.id, status=sh.status))
        timeline.append(_history_event("shipment_delivered", f"Shipment {sh.shipment_no} delivered", sh.delivered_at, shipment_id=sh.id, status=sh.status))
    for inv in invoices:
        timeline.append(_history_event("invoice", f"Invoice {inv.invoice_no}", inv.issued_at or inv.created_at, invoice_id=inv.id, amount=_num(inv.amount), status=inv.status))
    for payment in payments:
        timeline.append(_history_event("payment", "Payment received", payment.paid_at or payment.created_at, payment_id=payment.id, amount=_num(payment.amount)))
    for audit, user in audit_rows:
        timeline.append(_history_event("audit", f"Sales order {audit.action}", audit.created_at, action=audit.action, user=user.name if user else None))
    timeline = sorted([event for event in timeline if event], key=_event_sort_key)

    shipment_packages_by_shipment: dict[int, list[ShipmentPackage]] = defaultdict(list)
    for row_sp in shipment_package_rows:
        shipment_packages_by_shipment[int(row_sp.shipment_id)].append(row_sp)

    detail = {
        **row,
        "order": _serialize_sales_order(db, so, include_items=True),
        "items": [
            {
                "id": item.id,
                "model_id": item.model_id,
                "model": model_map.get(int(item.model_id)),
                "brand_id": item.brand_id,
                "collection_id": item.collection_id,
                "color": item.color,
                "size": item.size,
                "quantity": _int_qty(item.quantity),
                "unit_price": _num(item.unit_price),
                "line_total": _num(item.unit_price) * _int_qty(item.quantity),
                "source_type": item.source_type,
                "printing_required": bool(item.printing_required),
                "notes": item.notes,
            }
            for item in sales_items
        ],
        "production_orders": [
            {
                "id": po.id,
                "production_no": po.production_no,
                "order_no": so.order_no,
                "production_type": po.production_type,
                "status": po.status,
                "model_id": po.model_id,
                "model": model_map.get(int(po.model_id)),
                "planned_quantity": _int_qty(po.planned_quantity),
                "start_date": po.start_date,
                "deadline": po.deadline,
                "estimated_material_code": po.estimated_material_code,
                "estimated_material_amount": _num(po.estimated_material_amount),
                "estimated_material_unit": po.estimated_material_unit,
                "items": [
                    {
                        "id": item.id,
                        "model_id": item.model_id,
                        "model": model_map.get(int(item.model_id)),
                        "color": item.color,
                        "size": item.size,
                        "planned_quantity": _int_qty(item.planned_quantity),
                        "completed_quantity": _int_qty(item.completed_quantity),
                    }
                    for item in (po.items or [])
                ],
                "batches": [
                    {
                        "id": batch.id,
                        "batch_no": batch.batch_no,
                        "name": batch.name,
                        "planned_quantity": _int_qty(batch.planned_quantity),
                        "start_date": batch.start_date,
                        "deadline": batch.deadline,
                        "notes": batch.notes,
                    }
                    for batch in (po.batches or [])
                ],
                "work_orders": [
                    {
                        "id": wo.id,
                        "order_no": so.order_no,
                        "production_batch_id": wo.production_batch_id,
                        "operation": wo.operation,
                        "status": wo.status,
                        "planned_input_qty": _int_qty(wo.planned_input_qty),
                        "planned_output_qty": _int_qty(wo.planned_output_qty),
                        "actual_input_qty": _int_qty(wo.actual_input_qty),
                        "actual_output_qty": _int_qty(wo.actual_output_qty),
                        "passed_qty": _int_qty(wo.passed_qty),
                        "failed_qty": _int_qty(wo.failed_qty),
                        "rework_qty": _int_qty(wo.rework_qty),
                        "start_time": wo.start_time,
                        "end_time": wo.end_time,
                        "deadline": wo.deadline,
                        "notes": wo.notes,
                    }
                    for wo in sorted((po.work_orders or []), key=lambda row_wo: (int(row_wo.production_batch_id or 0), str(row_wo.operation or ""), int(row_wo.id)))
                ],
            }
            for po in production_orders
        ],
        "materials": {
            "spent": materials_spent,
            "movements": material_movements,
        },
        "packages": [
            {
                "id": pkg.id,
                "package_no": pkg.package_no,
                "barcode": pkg.barcode,
                "qr_code_url": pkg.qr_code_url,
                "production_order_id": pkg.production_order_id,
                "production_batch_id": pkg.production_batch_id,
                "model_id": pkg.model_id,
                "model": model_map.get(int(pkg.model_id)),
                "color": pkg.color,
                "package_type": pkg.package_type,
                "total_quantity": _int_qty(pkg.total_quantity),
                "capacity": _int_qty(pkg.capacity),
                "weight_kg": _num(pkg.weight_kg),
                "status": pkg.status,
                "packed_at": pkg.packed_at,
                "received_at": pkg.received_at,
                "shipped_at": pkg.shipped_at,
                "items": [
                    {
                        "id": item.id,
                        "model_id": item.model_id,
                        "model": model_map.get(int(item.model_id)),
                        "color": item.color,
                        "size": item.size,
                        "quantity": _int_qty(item.quantity),
                    }
                    for item in (pkg.items or [])
                ],
            }
            for pkg in packages
        ],
        "shipments": [
            {
                "id": sh.id,
                "shipment_no": sh.shipment_no,
                "status": sh.status,
                "shipped_at": sh.shipped_at,
                "delivered_at": sh.delivered_at,
                "notes": sh.notes,
                "packages": [
                    {
                        "package_id": row_sp.package_id,
                        "quantity": _int_qty(row_sp.quantity),
                    }
                    for row_sp in shipment_packages_by_shipment.get(int(sh.id), [])
                ],
            }
            for sh in sorted(shipments, key=lambda row_sh: int(row_sh.id))
        ],
        "invoices": [
            {
                "id": inv.id,
                "invoice_no": inv.invoice_no,
                "amount": _num(inv.amount),
                "status": inv.status,
                "issued_at": inv.issued_at,
                "due_date": inv.due_date,
            }
            for inv in invoices
        ],
        "payments": [
            {
                "id": payment.id,
                "invoice_id": payment.invoice_id,
                "amount": _num(payment.amount),
                "payment_method": payment.payment_method,
                "paid_at": payment.paid_at,
                "notes": payment.notes,
            }
            for payment in payments
        ],
        "timeline": timeline,
    }
    return detail


def _is_any_stock_token(value: str | None) -> bool:
    token = str(value or "").strip().lower()
    return token in {"", "*", "any", "mixed", "__any__", "pack60", "bag"}


def _stock_variant_key(model_id: int, color: str, size: str, brand_id: int | None) -> tuple[int, str, str, int | None]:
    return (int(model_id), str(color or "").strip(), str(size or "").strip(), brand_id)


def _stock_rows_for_variant(
    db: DbSession,
    *,
    model_id: int,
    color: str,
    size: str,
    brand_id: int | None,
) -> list[FinishedGoodsStock]:
    qry = db.query(FinishedGoodsStock).filter(
        FinishedGoodsStock.model_id == model_id,
        FinishedGoodsStock.status == "available",
        FinishedGoodsStock.available_qty > 0,
    )
    if not _is_any_stock_token(color):
        qry = qry.filter(FinishedGoodsStock.color == color)
    if not _is_any_stock_token(size):
        qry = qry.filter(FinishedGoodsStock.size == size)
    if brand_id is not None:
        qry = qry.filter(FinishedGoodsStock.brand_id == brand_id)
    if db.bind and db.bind.dialect.name == "postgresql":
        qry = qry.with_for_update(of=FinishedGoodsStock)
    return qry.order_by(FinishedGoodsStock.id.asc()).all()


def _notify_planning_shortage(
    db: DbSession,
    *,
    so: SalesOrder,
    current: User,
    shortages: list[dict],
) -> None:
    if not shortages:
        return
    planning_dept = db.query(Department).filter(Department.code == "PLN").first()
    planning_user = (
        db.query(User)
        .filter(User.is_active.is_(True), User.department_id == planning_dept.id if planning_dept else False)
        .order_by(User.id.asc())
        .first()
        if planning_dept
        else None
    )
    if planning_user:
        summary = ", ".join(f"M{r['model_id']} {r['color']}/{r['size']}: {r['shortage']}" for r in shortages[:6])
        if len(shortages) > 6:
            summary += f" (+{len(shortages) - 6} more)"
        db.add(
            Task(
                title=f"Stock shortage for {so.order_no}",
                description=f"Auto-created from reserve-stock. Resolve shortages: {summary}",
                assigned_to=planning_user.id,
                created_by=current.id,
                status="pending",
                priority="high",
                due_date=so.deadline,
            )
        )
    notify_department(
        db,
        department_code="PLN",
        title=f"Shortage detected for {so.order_no}",
        message=f"{len(shortages)} shortage line(s) were detected during reserve-stock.",
        link=f"/sales-orders/{so.id}",
        exclude_user_id=current.id,
    )


def _reserve_branded_stock(
    db: DbSession,
    *,
    so: SalesOrder,
    current: User,
    lines: list[SalesOrderItem] | None = None,
    fail_on_shortage: bool = False,
    notify_shortage: bool = True,
    notify_storage_when_ready: bool = False,
) -> tuple[list[dict], list[dict]]:
    repair_missing_brand_metadata(db)
    line_rows = lines if lines is not None else db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id == so.id).all()
    requested_by_variant: dict[tuple[int, str, str, int | None], int] = defaultdict(int)
    for line in line_rows:
        key = _stock_variant_key(line.model_id, line.color, line.size, line.brand_id)
        requested_by_variant[key] += int(line.quantity or 0)

    existing_rows = (
        db.query(StockReservation, FinishedGoodsStock)
        .join(FinishedGoodsStock, FinishedGoodsStock.id == StockReservation.finished_goods_stock_id)
        .filter(StockReservation.sales_order_id == so.id)
        .all()
    )

    outstanding_by_variant: dict[tuple[int, str, str, int | None], int] = {}
    for key, requested_qty in requested_by_variant.items():
        model_id, color, size, brand_id = key
        any_color = _is_any_stock_token(color)
        any_size = _is_any_stock_token(size)
        already_reserved = 0
        for reservation, stock in existing_rows:
            if int(stock.model_id) != int(model_id):
                continue
            if not any_color and str(stock.color or "").strip() != color:
                continue
            if not any_size and str(stock.size or "").strip() != size:
                continue
            if brand_id is not None and int(stock.brand_id or 0) != int(brand_id):
                continue
            already_reserved += int(reservation.quantity or 0)
        outstanding_by_variant[key] = max(0, int(requested_qty) - already_reserved)

    if requested_by_variant and all(qty <= 0 for qty in outstanding_by_variant.values()):
        raise HTTPException(409, "Stock has already been fully reserved for this sales order")

    shortages_precheck: list[dict] = []
    for (model_id, color, size, brand_id), requested_qty in outstanding_by_variant.items():
        if requested_qty <= 0:
            continue
        available_qty = sum(
            int(row.available_qty or 0)
            for row in _stock_rows_for_variant(
                db,
                model_id=model_id,
                color=color,
                size=size,
                brand_id=brand_id,
            )
        )
        if available_qty < requested_qty:
            shortages_precheck.append(
                {
                    "model_id": model_id,
                    "brand_id": brand_id,
                    "color": color,
                    "size": size,
                    "requested": requested_qty,
                    "available": available_qty,
                    "shortage": requested_qty - available_qty,
                }
            )

    if fail_on_shortage and shortages_precheck:
        summary = "; ".join(
            f"M{s['model_id']} {s['color']}/{s['size']} need {s['requested']}, available {s['available']}"
            for s in shortages_precheck[:4]
        )
        if len(shortages_precheck) > 4:
            summary += f" (+{len(shortages_precheck) - 4} more)"
        raise HTTPException(409, f"Not enough branded stock to fulfill this order: {summary}")

    reservations: list[dict] = []
    shortages: list[dict] = []
    for (model_id, color, size, brand_id), requested_qty in outstanding_by_variant.items():
        if requested_qty <= 0:
            continue
        needed = int(requested_qty)
        stocks = _stock_rows_for_variant(
            db,
            model_id=model_id,
            color=color,
            size=size,
            brand_id=brand_id,
        )
        for s in stocks:
            if needed <= 0:
                break
            take = min(needed, int(s.available_qty or 0))
            if take <= 0:
                continue
            s.available_qty = int(s.available_qty or 0) - take
            s.reserved_qty = int(s.reserved_qty or 0) + take
            if int(s.available_qty or 0) == 0:
                s.status = "reserved"
            db.add(
                StockReservation(
                    sales_order_id=so.id,
                    finished_goods_stock_id=s.id,
                    package_id=s.package_id,
                    quantity=take,
                    reserved_by=current.id,
                )
            )
            reservations.append({"stock_id": s.id, "qty": take})
            needed -= take
        if needed > 0:
            shortages.append(
                {
                    "model_id": model_id,
                    "brand_id": brand_id,
                    "color": color,
                    "size": size,
                    "shortage": needed,
                }
            )

    if not shortages and reservations:
        so.status = "ready"
        auto_note = "[Auto route] Branded stock reserved and sent to storage team for shipment prep."
        so.notes = f"{so.notes}\n{auto_note}".strip() if so.notes else auto_note
        if notify_storage_when_ready:
            notify_department(
                db,
                department_code="FGS",
                title=f"{so.order_no} ready for shipment prep",
                message="Branded stock order has been auto-reserved. Prepare shipment from ready-goods storage.",
                link=f"/sales-orders/{so.id}",
                exclude_user_id=current.id,
            )

    if shortages and notify_shortage:
        _notify_planning_shortage(db, so=so, current=current, shortages=shortages)

    return reservations, shortages


@router.post("/printing-attachments/upload", status_code=201)
async def upload_printing_attachment(
    file: UploadFile = File(...),
    current: User = Depends(require_permissions("sales.orders", "*")),
):
    _ = current
    ext = extension_for_upload(file, SAFE_IMAGE_EXTENSIONS | SAFE_DOCUMENT_EXTENSIONS)
    os.makedirs(settings.SALES_ORDER_FILES_DIR, exist_ok=True)
    safe_name = f"so_print_{uuid4().hex}{ext}"
    abs_path = os.path.join(settings.SALES_ORDER_FILES_DIR, safe_name)
    content = await read_validated_upload_content(file, ext, 20 * 1024 * 1024)
    with open(abs_path, "wb") as f:
        f.write(content)
    file_url = f"/storage/sales-order-files/{safe_name}"
    return {
        # Signed for immediate <img> preview; the bare path is what gets stored
        # when the order is saved (create/update strip the signature).
        "file_url": sign_path(file_url),
        "file_name": file.filename or safe_name,
        "content_type": safe_content_type(ext),
    }


@router.get("")
def list_sales_orders(
    db: DbSession, _: CurrentUser,
    status: str | None = None, order_type: str | None = None,
    customer_id: int | None = None, q: str | None = None,
    page: int = 1, page_size: int = 50,
    include_total: bool = False,
):
    qry = db.query(SalesOrder)
    if status: qry = qry.filter(SalesOrder.status == status)
    if order_type: qry = qry.filter(SalesOrder.order_type == order_type)
    if customer_id: qry = qry.filter(SalesOrder.customer_id == customer_id)
    if q: qry = qry.filter(SalesOrder.order_no.ilike(f"%{q}%"))
    total = qry.count() if include_total else 0
    safe_page = max(1, page)
    safe_size = max(1, min(page_size, 500))
    rows = qry.order_by(SalesOrder.id.desc()).offset((safe_page - 1) * safe_size).limit(safe_size).all()
    payload = [_serialize_sales_order(db, so, include_items=False) for so in rows]
    if include_total:
        return {"rows": payload, "total": total, "page": safe_page, "page_size": safe_size}
    return payload


@router.get("/history")
def list_sales_order_history(
    db: DbSession,
    _: CurrentUser,
    status: str | None = None,
    order_type: str | None = None,
    customer_id: int | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 50,
    include_total: bool = False,
):
    qry = db.query(SalesOrder).outerjoin(Customer, Customer.id == SalesOrder.customer_id)
    if status:
        qry = qry.filter(SalesOrder.status == status)
    if order_type:
        qry = qry.filter(SalesOrder.order_type == order_type)
    if customer_id:
        qry = qry.filter(SalesOrder.customer_id == customer_id)
    if q:
        like = f"%{q.strip()}%"
        qry = qry.filter(
            or_(
                SalesOrder.order_no.ilike(like),
                SalesOrder.status.ilike(like),
                SalesOrder.order_type.ilike(like),
                Customer.name.ilike(like),
            )
        )
    total = qry.count() if include_total else 0
    safe_page = max(1, page)
    safe_size = max(1, min(page_size, 200))
    rows = (
        qry.order_by(SalesOrder.id.desc())
        .offset((safe_page - 1) * safe_size)
        .limit(safe_size)
        .all()
    )
    payload = [_sales_order_history(db, so, include_detail=False) for so in rows]
    if include_total:
        return {"rows": payload, "total": total, "page": safe_page, "page_size": safe_size}
    return payload


@router.get("/{sid}/history")
def get_sales_order_history(sid: int, db: DbSession, _: CurrentUser):
    so = db.query(SalesOrder).filter(SalesOrder.id == sid).first()
    if not so:
        raise HTTPException(404, "Sales order not found")
    return _sales_order_history(db, so, include_detail=True)


@router.post("", response_model=SalesOrderDetail, status_code=201)
def create_sales_order(payload: SalesOrderIn, db: DbSession, current: User = Depends(require_permissions("sales.orders", "*"))):
    if payload.order_type not in ("client_order", "branded_stock_sale"):
        raise HTTPException(400, "Invalid order_type")
    if payload.customer_id and not db.get(Customer, payload.customer_id):
        raise HTTPException(404, "Customer not found")
    so = SalesOrder(
        order_no=next_sales_order_no(db),
        customer_id=payload.customer_id,
        order_type=payload.order_type,
        status="draft",
        deadline=payload.deadline,
        printing_instructions=payload.printing_instructions,
        printing_attachments=_attachments_for_storage(payload.printing_attachments),
        notes=payload.notes,
        created_by=current.id,
    )
    db.add(so); db.flush()
    total = 0.0
    created_lines: list[SalesOrderItem] = []
    for item in payload.items:
        if not db.get(Model, item.model_id):
            raise HTTPException(404, f"Model {item.model_id} not found")
        line = SalesOrderItem(sales_order_id=so.id, **item.model_dump())
        db.add(line)
        created_lines.append(line)
        total += float(item.unit_price) * item.quantity
    so.total_amount = total
    if payload.order_type == "branded_stock_sale":
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
    return _serialize_sales_order(db, so, include_items=True)


@router.get("/{sid}", response_model=SalesOrderDetail)
def get_sales_order(sid: int, db: DbSession, _: CurrentUser):
    so = db.query(SalesOrder).options(joinedload(SalesOrder.items)).filter(SalesOrder.id == sid).first()
    if not so: raise HTTPException(404, "Sales order not found")
    return _serialize_sales_order(db, so, include_items=True)


@router.patch("/{sid}", response_model=SalesOrderOut)
def update_sales_order(sid: int, payload: SalesOrderUpdate, db: DbSession, current: User = Depends(require_permissions("sales.orders", "*"))):
    so = db.get(SalesOrder, sid)
    if not so: raise HTTPException(404, "Sales order not found")
    updates = payload.model_dump(exclude_unset=True)
    if "printing_attachments" in updates:
        updates["printing_attachments"] = _attachments_for_storage(updates["printing_attachments"])
    for k, v in updates.items():
        setattr(so, k, v)
    log_action(db, current, "update", "SalesOrder", so.id)
    db.commit(); db.refresh(so)
    return _serialize_sales_order(db, so, include_items=False)


@router.post("/{sid}/confirm", response_model=SalesOrderOut)
def confirm_sales_order(sid: int, db: DbSession, current: User = Depends(require_permissions("sales.orders", "*"))):
    so = db.get(SalesOrder, sid)
    if not so: raise HTTPException(404, "Sales order not found")
    if so.status != "draft":
        raise HTTPException(400, f"Cannot confirm order in status '{so.status}'")
    so.status = "confirmed"
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


@router.post("/{sid}/reserve-stock")
def reserve_stock(sid: int, db: DbSession, current: User = Depends(require_permissions("sales.orders", "*"))):
    """For branded_stock_sale: try to reserve from FinishedGoodsStock for each line."""
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
    db.commit()
    return {"reservations": reservations, "shortages": shortages}


@router.post("/{sid}/generate-invoice")
def generate_invoice_for_order(
    sid: int,
    db: DbSession,
    current: User = Depends(require_permissions("finance.invoice", "sales.orders", "*")),
):
    so = db.get(SalesOrder, sid)
    if not so:
        raise HTTPException(404, "Sales order not found")
    allowed = {"confirmed", "in_production", "cutting", "sewing", "packaging", "storage", "ready", "reserved", "shipped", "delivered", "planning", "planning_approved", "production"}
    if str(so.status or "") not in allowed:
        raise HTTPException(400, f"Cannot generate invoice for order in status '{so.status}'")
    existing = db.query(Invoice).filter(Invoice.sales_order_id == sid).order_by(Invoice.id.desc()).first()
    if existing:
        return {
            "id": existing.id,
            "sales_order_id": existing.sales_order_id,
            "invoice_no": existing.invoice_no,
            "amount": float(existing.amount or 0),
            "status": existing.status,
            "issued_at": existing.issued_at,
            "due_date": existing.due_date,
            "created_existing": True,
        }
    inv = Invoice(
        sales_order_id=sid,
        invoice_no=next_invoice_no(db),
        amount=float(so.total_amount or 0),
        status="unpaid",
        issued_at=datetime.now(timezone.utc),
    )
    db.add(inv)
    db.flush()
    log_action(db, current, "generate_invoice", "Invoice", inv.id, new_value={"sales_order_id": sid, "amount": float(inv.amount or 0)})
    db.commit()
    db.refresh(inv)
    return {
        "id": inv.id,
        "sales_order_id": inv.sales_order_id,
        "invoice_no": inv.invoice_no,
        "amount": float(inv.amount or 0),
        "status": inv.status,
        "issued_at": inv.issued_at,
        "due_date": inv.due_date,
        "created_existing": False,
    }


@router.delete("/{sid}", status_code=204)
def delete_sales_order(sid: int, db: DbSession, current: User = Depends(require_permissions("sales.orders", "*"))):
    so = db.get(SalesOrder, sid)
    if not so:
        raise HTTPException(404, "Sales order not found")

    if so.status not in ("draft", "cancelled"):
        raise HTTPException(409, "Only draft or cancelled sales orders can be deleted")
    if db.query(ProductionOrder).filter(ProductionOrder.sales_order_id == sid).first():
        raise HTTPException(409, "Sales order already has linked production orders")
    if db.query(Shipment).filter(Shipment.sales_order_id == sid).first():
        raise HTTPException(409, "Sales order already has linked shipments")
    if db.query(StockReservation).filter(StockReservation.sales_order_id == sid).first():
        raise HTTPException(409, "Sales order already has stock reservations")

    db.delete(so)
    log_action(db, current, "delete", "SalesOrder", sid, new_value={"order_no": so.order_no})
    db.commit()
