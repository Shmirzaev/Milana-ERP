import os
from collections import defaultdict
from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Depends, Header
from fastapi import UploadFile, File
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.core.config import settings
from app.core.dt import date_filter_bounds
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
    BrandedPlanningOrder, Customer, Model, User, ProductionOrder,
    CuttingRecord, PrintingRecord, SewingRecord, PackagingRecord, QualityCheck, Shipment, ShipmentPackage,
    Task, Department, Invoice, Payment, StockMovement, Item, StockBatch, MaterialReservation,
    Package, Bundle, FinishedGoodsStock, AuditLog,
)
from app.schemas.sales import (
    SalesOrderIn, SalesOrderUpdate, SalesOrderOut, SalesOrderDetail,
)
from app.services.audit import log_action
from app.services.finished_goods import repair_missing_brand_metadata
from app.services.numbering import next_sales_order_no
from app.services.numbering import next_invoice_no
from app.services.workflow import notify_department
from app.services.idempotency import replay_idempotent_response, store_idempotent_response
from app.services.legacy_stock import package_legacy_identity
from app.services.model_images import material_preview_image_url, model_display_image_url

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
                "composition": (details or {}).get("composition") if isinstance(details, dict) else None,
            }
            for mid, code, name, details in model_rows
        }
        for item in payload.get("items", []):
            model_ref = model_map.get(int(item.get("model_id") or 0))
            item["model_code"] = (
                model_ref["code"] if model_ref else item.get("source_model_code")
            )
            item["model_name"] = (
                model_ref["name"] if model_ref else item.get("source_model_name")
            )
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
            "composition": (details or {}).get("composition") if isinstance(details, dict) else None,
        }
        for mid, code, name, details in rows
    }


def _history_products(db: DbSession, model_ids: set[int]) -> list[dict]:
    if not model_ids:
        return []
    models = (
        db.query(Model)
        .options(joinedload(Model.images), joinedload(Model.bom))
        .filter(Model.id.in_(model_ids))
        .order_by(Model.code.asc())
        .all()
    )
    products: list[dict] = []
    for model in models:
        details = model.details_json if isinstance(model.details_json, dict) else {}
        general = details.get("general") if isinstance(details.get("general"), dict) else {}
        code = str(model.code or "").strip()
        code_parts = code.rsplit("-", 1)
        model_no = str(general.get("model_no") or general.get("modelNo") or code_parts[0] or "").strip()
        variant_no = str(
            general.get("variant_no")
            or general.get("variantNo")
            or (code_parts[1] if len(code_parts) > 1 else "")
        ).strip()
        picture_url = material_preview_image_url(model) or model_display_image_url(model)
        if picture_url and str(picture_url).startswith("/storage/"):
            picture_url = sign_path(picture_url)
        products.append(
            {
                "model_id": int(model.id),
                "model_no": model_no,
                "variant_no": variant_no,
                "code": code,
                "name": model.name,
                "picture_url": picture_url,
            }
        )
    return products


def _production_step_records(db: DbSession, production_orders: list[ProductionOrder]) -> dict:
    """Return the entered values from every production step for the history ledger."""
    po_ids = [int(po.id) for po in production_orders]
    work_orders = sorted(
        [wo for po in production_orders for wo in (po.work_orders or [])],
        key=lambda wo: (int(wo.production_batch_id or 0), str(wo.operation or ""), int(wo.id)),
    )
    work_order_ids = [int(wo.id) for wo in work_orders]

    def records(model):
        if not work_order_ids:
            return []
        return db.query(model).filter(model.work_order_id.in_(work_order_ids)).order_by(model.id.asc()).all()

    cutting = records(CuttingRecord)
    printing = records(PrintingRecord)
    sewing = records(SewingRecord)
    packaging = records(PackagingRecord)
    quality = records(QualityCheck)
    reservations = (
        db.query(MaterialReservation)
        .filter(MaterialReservation.production_order_id.in_(po_ids))
        .order_by(MaterialReservation.id.asc())
        .all()
        if po_ids else []
    )
    bundles = (
        db.query(Bundle)
        .options(joinedload(Bundle.scan_logs))
        .filter(Bundle.production_order_id.in_(po_ids))
        .order_by(Bundle.id.asc())
        .all()
        if po_ids else []
    )
    finished_goods = (
        db.query(FinishedGoodsStock)
        .filter(FinishedGoodsStock.production_order_id.in_(po_ids))
        .order_by(FinishedGoodsStock.id.asc())
        .all()
        if po_ids else []
    )
    audit_filters = []
    if po_ids:
        audit_filters.append((AuditLog.entity_type == "ProductionOrder") & AuditLog.entity_id.in_(po_ids))
    if work_order_ids:
        audit_filters.append((AuditLog.entity_type == "WorkOrder") & AuditLog.entity_id.in_(work_order_ids))
    audits = (
        db.query(AuditLog, User)
        .outerjoin(User, User.id == AuditLog.user_id)
        .filter(or_(*audit_filters))
        .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        .all()
        if audit_filters else []
    )

    return {
        "material_reservations": [
            {
                "id": row.id, "reservation_no": row.reservation_no, "production_order_id": row.production_order_id,
                "sales_order_id": row.sales_order_id, "item_id": row.item_id,
                "item_sku": row.item.sku if row.item else None, "item_name": row.item.name if row.item else None,
                "stock_batch_id": row.stock_batch_id,
                "batch_no": row.stock_batch.batch_no if row.stock_batch else None,
                "warehouse_id": row.warehouse_id, "warehouse_name": row.warehouse.name if row.warehouse else None,
                "reserved_quantity": _num(row.reserved_quantity), "consumed_quantity": _num(row.consumed_quantity),
                "released_quantity": _num(row.released_quantity), "unit": row.unit, "status": row.status,
                "reservation_type": row.reservation_type, "source": row.source, "reserved_by": row.reserved_by,
                "reserved_at": row.reserved_at, "notes": row.notes,
            }
            for row in reservations
        ],
        "cutting": [
            {
                "id": row.id, "work_order_id": row.work_order_id, "production_batch_id": row.production_batch_id,
                "fabric_batch_id": row.fabric_batch_id, "input_quantity": _num(row.input_quantity),
                "input_unit": row.input_unit, "cut_pieces": row.cut_pieces, "passed_pieces": row.passed_pieces,
                "defective_pieces": row.defective_pieces, "waste_quantity": _num(row.waste_quantity),
                "waste_unit": row.waste_unit, "layer_material_kg": _num(row.layer_material_kg),
                "beika_kg": _num(row.beika_kg), "material_rolls_used": _num(row.material_rolls_used),
                "bundle_count": row.bundle_count, "total_bundled_quantity": row.total_bundled_quantity,
                "operator_id": row.operator_id, "notes": row.notes, "created_at": row.created_at,
            }
            for row in cutting
        ],
        "printing": [
            {
                "id": row.id, "work_order_id": row.work_order_id, "production_batch_id": row.production_batch_id,
                "input_qty": row.input_qty, "printed_qty": row.printed_qty, "passed_qty": row.passed_qty,
                "rejected_qty": row.rejected_qty, "defect_reason": row.defect_reason, "print_type": row.print_type,
                "operator_id": row.operator_id, "notes": row.notes, "created_at": row.created_at,
            }
            for row in printing
        ],
        "sewing": [
            {
                "id": row.id, "work_order_id": row.work_order_id, "production_batch_id": row.production_batch_id,
                "input_qty": row.input_qty, "sewn_qty": row.sewn_qty, "passed_qty": row.passed_qty,
                "failed_qty": row.failed_qty, "rework_qty": row.rework_qty, "rejected_qty": row.rejected_qty,
                "defect_reason": row.defect_reason, "line_name": row.line_name, "operator_id": row.operator_id,
                "notes": row.notes, "created_at": row.created_at,
            }
            for row in sewing
        ],
        "quality_checks": [
            {
                "id": row.id, "work_order_id": row.work_order_id, "department_id": row.department_id,
                "checked_qty": row.checked_qty, "passed_qty": row.passed_qty, "failed_qty": row.failed_qty,
                "defect_type": row.defect_type, "defect_reason": row.defect_reason, "severity": row.severity,
                "checked_by": row.checked_by, "checked_at": row.checked_at,
            }
            for row in quality
        ],
        "packaging": [
            {
                "id": row.id, "work_order_id": row.work_order_id, "production_batch_id": row.production_batch_id,
                "input_qty": row.input_qty, "packed_qty": row.packed_qty, "damaged_qty": row.damaged_qty,
                "package_count": row.package_count, "total_packed_quantity": row.total_packed_quantity,
                "packaging_material_used": row.packaging_material_used, "operator_id": row.operator_id,
                "notes": row.notes, "created_at": row.created_at,
            }
            for row in packaging
        ],
        "bundles": [
            {
                "id": row.id, "bundle_no": row.bundle_no, "barcode": row.barcode,
                "production_order_id": row.production_order_id, "production_batch_id": row.production_batch_id,
                "sales_order_id": row.sales_order_id, "model_id": row.model_id, "color": row.color,
                "size": row.size, "quantity": row.quantity, "current_department_id": row.current_department_id,
                "next_department_id": row.next_department_id, "sewing_factory_code": row.sewing_factory_code,
                "status": row.status, "created_by": row.created_by, "notes": row.notes, "created_at": row.created_at,
                "scan_logs": [
                    {
                        "id": scan.id, "scan_type": scan.scan_type, "from_department_id": scan.from_department_id,
                        "to_department_id": scan.to_department_id, "location": scan.location,
                        "scanned_by": scan.scanned_by, "scanned_at": scan.scanned_at,
                    }
                    for scan in (row.scan_logs or [])
                ],
            }
            for row in bundles
        ],
        "finished_goods": [
            {
                "id": row.id, "production_order_id": row.production_order_id, "sales_order_id": row.sales_order_id,
                "package_id": row.package_id, "model_id": row.model_id, "collection_id": row.collection_id,
                "brand_id": row.brand_id, "color": row.color, "size": row.size, "quantity": row.quantity,
                "available_qty": row.available_qty, "reserved_qty": row.reserved_qty, "sold_qty": row.sold_qty,
                "cost_per_piece": _num(row.cost_per_piece), "selling_price": _num(row.selling_price),
                "warehouse_id": row.warehouse_id, "status": row.status, "created_at": row.created_at,
            }
            for row in finished_goods
        ],
        "audit": [
            {
                "id": audit.id, "entity_type": audit.entity_type, "entity_id": audit.entity_id,
                "action": audit.action, "user_id": audit.user_id, "user_name": user.name if user else None,
                "old_value": audit.old_value_json, "new_value": audit.new_value_json, "created_at": audit.created_at,
            }
            for audit, user in audits
        ],
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

    reserved_package_ids = [
        int(package_id)
        for (package_id,) in (
            db.query(StockReservation.package_id)
            .filter(
                StockReservation.sales_order_id == so.id,
                StockReservation.package_id.isnot(None),
            )
            .distinct()
            .all()
        )
        if package_id is not None
    ]
    package_filters = [Package.sales_order_id == so.id]
    if po_ids:
        package_filters.append(Package.production_order_id.in_(po_ids))
    if reserved_package_ids:
        package_filters.append(Package.id.in_(reserved_package_ids))
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

    product_model_ids = {int(item.model_id) for item in sales_items if item.model_id}
    for production_order in production_orders:
        if production_order.model_id:
            product_model_ids.add(int(production_order.model_id))
        product_model_ids.update(int(item.model_id) for item in (production_order.items or []) if item.model_id)

    history_products = _history_products(db, product_model_ids)
    legacy_product_keys: set[tuple[int | None, str]] = set()
    for item in sales_items:
        code = str(item.source_model_code or "").strip()
        if item.model_id is not None or not code:
            continue
        key = (item.finished_goods_stock_id, code)
        if key in legacy_product_keys:
            continue
        legacy_product_keys.add(key)
        history_products.append(
            {
                "model_id": None,
                "finished_goods_stock_id": item.finished_goods_stock_id,
                "model_no": code,
                "variant_no": None,
                "code": code,
                "name": item.source_model_name,
                "picture_url": None,
            }
        )

    row = {
        "id": so.id,
        "record_type": "sales_order",
        "history_key": f"sales:{so.id}",
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
        "products": history_products,
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
        if pkg.model_id:
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
                "finished_goods_stock_id": item.finished_goods_stock_id,
                "model": model_map.get(int(item.model_id)) if item.model_id else None,
                "model_code": (
                    model_map[int(item.model_id)]["code"]
                    if item.model_id and int(item.model_id) in model_map
                    else item.source_model_code
                ),
                "model_name": (
                    model_map[int(item.model_id)]["name"]
                    if item.model_id and int(item.model_id) in model_map
                    else item.source_model_name
                ),
                "source_model_code": item.source_model_code,
                "source_model_name": item.source_model_name,
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
                "collection_id": po.collection_id,
                "estimated_material_code": po.estimated_material_code,
                "estimated_material_amount": _num(po.estimated_material_amount),
                "estimated_material_unit": po.estimated_material_unit,
                "printing_instructions": po.printing_instructions,
                "printing_attachments": [
                    {
                        **attachment,
                        "file_url": sign_path(attachment.get("file_url")) if attachment.get("file_url") else None,
                    }
                    for attachment in (po.printing_attachments or [])
                    if isinstance(attachment, dict)
                ],
                "destination_warehouse_id": po.destination_warehouse_id,
                "created_by": po.created_by,
                "created_at": po.created_at,
                "updated_at": po.updated_at,
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
                        "department_id": wo.department_id,
                        "assigned_to": wo.assigned_to,
                        "sewing_flow_id": wo.sewing_flow_id,
                        "is_blocked": wo.is_blocked,
                        "block_reason": wo.block_reason,
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
                "model": model_map.get(int(pkg.model_id)) if pkg.model_id else None,
                "model_code": (
                    model_map[int(pkg.model_id)]["code"]
                    if pkg.model_id and int(pkg.model_id) in model_map
                    else package_legacy_identity(db, pkg).get("model_code")
                ),
                "model_name": (
                    model_map[int(pkg.model_id)]["name"]
                    if pkg.model_id and int(pkg.model_id) in model_map
                    else package_legacy_identity(db, pkg).get("model_name")
                ),
                "color": pkg.color,
                "package_type": pkg.package_type,
                "total_quantity": _int_qty(pkg.total_quantity),
                "capacity": _int_qty(pkg.capacity),
                "weight_kg": _num(pkg.weight_kg),
                "warehouse_id": pkg.warehouse_id,
                "storage_cell": pkg.storage_cell,
                "storage_shelf": pkg.storage_shelf,
                "storage_placed_at": pkg.storage_placed_at,
                "status": pkg.status,
                "packed_by": pkg.packed_by,
                "packed_at": pkg.packed_at,
                "received_by": pkg.received_by,
                "received_at": pkg.received_at,
                "shipped_at": pkg.shipped_at,
                "notes": pkg.notes,
                "scan_logs": [
                    {
                        "id": scan.id, "scan_type": scan.scan_type, "location": scan.location,
                        "scanned_by": scan.scanned_by, "scanned_at": scan.scanned_at,
                    }
                    for scan in (pkg.scan_logs or [])
                ],
                "items": [
                    {
                        "id": item.id,
                        "model_id": item.model_id,
                        "model": model_map.get(int(item.model_id)) if item.model_id else None,
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
        "step_records": _production_step_records(db, production_orders),
        "timeline": timeline,
    }
    return detail


def _stock_production_history(db: DbSession, po: ProductionOrder, *, include_detail: bool = False) -> dict:
    """Build the same ledger shape for a Planning-created stock production order."""
    production_orders = [po]
    work_orders = sorted(
        list(po.work_orders or []),
        key=lambda wo: (int(wo.production_batch_id or 0), str(wo.operation or ""), int(wo.id)),
    )
    work_order_ids = [int(wo.id) for wo in work_orders]
    cutting = db.query(CuttingRecord).filter(CuttingRecord.work_order_id.in_(work_order_ids)).all() if work_order_ids else []
    printing = db.query(PrintingRecord).filter(PrintingRecord.work_order_id.in_(work_order_ids)).all() if work_order_ids else []
    sewing = db.query(SewingRecord).filter(SewingRecord.work_order_id.in_(work_order_ids)).all() if work_order_ids else []
    packaging = db.query(PackagingRecord).filter(PackagingRecord.work_order_id.in_(work_order_ids)).all() if work_order_ids else []
    packages = (
        db.query(Package)
        .options(joinedload(Package.items), joinedload(Package.scan_logs))
        .filter(Package.production_order_id == po.id)
        .order_by(Package.id.asc())
        .all()
    )
    movement_filters = [
        (StockMovement.reference_type == "ProductionOrder") & (StockMovement.reference_id == po.id),
    ]
    cutting_ids = [int(row.id) for row in cutting]
    packaging_ids = [int(row.id) for row in packaging]
    if cutting_ids:
        movement_filters.append((StockMovement.reference_type == "CuttingRecord") & StockMovement.reference_id.in_(cutting_ids))
    if packaging_ids:
        movement_filters.append((StockMovement.reference_type == "PackagingRecord") & StockMovement.reference_id.in_(packaging_ids))
    movement_rows = (
        db.query(StockMovement, Item, StockBatch)
        .join(Item, Item.id == StockMovement.item_id)
        .outerjoin(StockBatch, StockBatch.id == StockMovement.batch_id)
        .filter(or_(*movement_filters))
        .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
        .all()
    )

    material_by_key: dict[tuple[int, str], dict] = {}
    material_movements: list[dict] = []
    material_cost_total = 0.0
    for movement, item, batch in movement_rows:
        quantity = _num(movement.quantity)
        unit = movement.unit or item.unit
        unit_cost = _num(batch.cost_per_unit if batch else item.default_cost)
        cost = quantity * unit_cost
        material_cost_total += cost
        bucket = material_by_key.setdefault(
            (int(item.id), unit),
            {
                "item_id": int(item.id), "sku": item.sku, "name": item.name,
                "category": item.category, "unit": unit, "quantity": 0.0, "estimated_cost": 0.0,
            },
        )
        bucket["quantity"] += quantity
        bucket["estimated_cost"] += cost
        material_movements.append(
            {
                "id": movement.id, "movement_type": movement.movement_type, "quantity": quantity,
                "unit": unit, "estimated_cost": cost, "reference_type": movement.reference_type,
                "reference_id": movement.reference_id, "created_at": movement.created_at,
                "item": {"id": item.id, "sku": item.sku, "name": item.name, "category": item.category},
                "batch": {
                    "id": batch.id, "batch_no": batch.batch_no, "cost_per_unit": _num(batch.cost_per_unit),
                } if batch else None,
            }
        )
    materials_spent = sorted(material_by_key.values(), key=lambda row: (str(row["category"]), str(row["sku"])))

    planned_qty = _int_qty(po.planned_quantity)
    cut_qty = sum(_int_qty(row.cut_pieces) for row in cutting)
    printed_qty = sum(_int_qty(row.printed_qty) for row in printing)
    sewn_qty = sum(_int_qty(row.sewn_qty) for row in sewing)
    packaged_qty = sum(_int_qty(pkg.total_quantity) for pkg in packages)
    shipped_qty = sum(_int_qty(pkg.total_quantity) for pkg in packages if pkg.status in {"shipped", "delivered"})
    completed_at = _latest_datetime(
        [pkg.shipped_at or pkg.received_at or pkg.packed_at for pkg in packages]
        + [wo.end_time for wo in work_orders if wo.status == "completed"]
    ) if str(po.status or "") in {"completed", "closed", "done"} or (planned_qty and packaged_qty >= planned_qty) else None
    last_activity_at = _latest_datetime(
        [po.updated_at, po.created_at]
        + [wo.end_time or wo.start_time or wo.updated_at or wo.created_at for wo in work_orders]
        + [row.created_at for row in cutting + printing + sewing + packaging]
        + [pkg.shipped_at or pkg.received_at or pkg.packed_at or pkg.updated_at or pkg.created_at for pkg in packages]
    )
    summary = {
        "ordered_qty": planned_qty, "planned_qty": planned_qty, "cut_qty": cut_qty,
        "cut_passed_qty": sum(_int_qty(row.passed_pieces) for row in cutting),
        "printed_qty": printed_qty, "sewn_qty": sewn_qty,
        "sewn_passed_qty": sum(_int_qty(row.passed_qty) for row in sewing),
        "packed_record_qty": sum(_int_qty(row.total_packed_quantity or row.packed_qty) for row in packaging),
        "packaged_qty": packaged_qty, "shipped_qty": shipped_qty, "package_count": len(packages),
        "shipment_count": 0, "invoice_count": 0, "payment_count": 0, "order_amount": 0.0,
        "invoice_total": 0.0, "paid_total": 0.0, "outstanding_amount": 0.0,
        "material_spent_cost": material_cost_total, "material_spent": materials_spent,
        "ordered_at": po.created_at, "completed_at": completed_at, "last_activity_at": last_activity_at,
    }
    product_model_ids = {int(po.model_id)} if po.model_id else set()
    product_model_ids.update(int(item.model_id) for item in (po.items or []) if item.model_id)
    planning_order = po.planning_order
    row = {
        "id": po.id, "record_type": "production_order", "history_key": f"production:{po.id}",
        "order_no": po.order_no, "customer_id": None, "customer_name": "Stock",
        "group_order_no": planning_order.order_no if planning_order else None,
        "ordered_for": planning_order.ordered_for_name if planning_order else None,
        "order_type": po.production_type, "status": po.status, "deadline": po.deadline,
        "created_at": po.created_at, "updated_at": po.updated_at, "completed_at": completed_at,
        "last_activity_at": last_activity_at, "total_amount": 0.0,
        "products": _history_products(db, product_model_ids), "summary": summary,
    }
    if not include_detail:
        return row

    model_ids = {int(po.model_id)}
    model_ids.update(int(item.model_id) for item in (po.items or []) if item.model_id)
    model_ids.update(int(pkg.model_id) for pkg in packages if pkg.model_id)
    model_map = _model_refs(db, model_ids)
    timeline = [_history_event("production_order", f"Stock production {po.order_no} created", po.created_at, production_order_id=po.id, status=po.status)]
    for wo in work_orders:
        timeline.append(_history_event("work_order_started", f"{wo.operation.title()} started", wo.start_time, work_order_id=wo.id, status=wo.status))
        timeline.append(_history_event("work_order_done", f"{wo.operation.title()} done", wo.end_time, work_order_id=wo.id, status=wo.status))
    for pkg in packages:
        timeline.append(_history_event("package_packed", f"Package {pkg.package_no} packed", pkg.packed_at, package_id=pkg.id, quantity=pkg.total_quantity))
        timeline.append(_history_event("package_received", f"Package {pkg.package_no} received", pkg.received_at, package_id=pkg.id))
        timeline.append(_history_event("package_shipped", f"Package {pkg.package_no} shipped", pkg.shipped_at, package_id=pkg.id))
    timeline = sorted([event for event in timeline if event], key=_event_sort_key)
    production_payload = {
        "id": po.id, "production_no": po.production_no, "order_no": po.order_no,
        "planning_order_id": po.planning_order_id,
        "group_order_no": planning_order.order_no if planning_order else None,
        "ordered_for": planning_order.ordered_for_name if planning_order else None,
        "production_type": po.production_type, "status": po.status, "model_id": po.model_id,
        "model": model_map.get(int(po.model_id)), "planned_quantity": planned_qty,
        "start_date": po.start_date, "deadline": po.deadline, "collection_id": po.collection_id,
        "estimated_material_code": po.estimated_material_code,
        "estimated_material_amount": _num(po.estimated_material_amount),
        "estimated_material_unit": po.estimated_material_unit,
        "printing_instructions": po.printing_instructions,
        "printing_attachments": [
            {**attachment, "file_url": sign_path(attachment.get("file_url")) if attachment.get("file_url") else None}
            for attachment in (po.printing_attachments or []) if isinstance(attachment, dict)
        ],
        "destination_warehouse_id": po.destination_warehouse_id, "created_by": po.created_by,
        "created_at": po.created_at, "updated_at": po.updated_at,
        "items": [
            {
                "id": item.id, "model_id": item.model_id, "model": model_map.get(int(item.model_id)),
                "color": item.color, "size": item.size, "planned_quantity": item.planned_quantity,
                "completed_quantity": item.completed_quantity, "printing_required": item.printing_required,
            }
            for item in (po.items or [])
        ],
        "batches": [
            {
                "id": batch.id, "batch_no": batch.batch_no, "name": batch.name,
                "planned_quantity": batch.planned_quantity, "start_date": batch.start_date,
                "deadline": batch.deadline, "notes": batch.notes,
            }
            for batch in (po.batches or [])
        ],
        "work_orders": [
            {
                "id": wo.id, "order_no": po.order_no, "production_batch_id": wo.production_batch_id,
                "department_id": wo.department_id, "operation": wo.operation, "status": wo.status,
                "planned_input_qty": wo.planned_input_qty, "planned_output_qty": wo.planned_output_qty,
                "actual_input_qty": wo.actual_input_qty, "actual_output_qty": wo.actual_output_qty,
                "passed_qty": wo.passed_qty, "failed_qty": wo.failed_qty, "rework_qty": wo.rework_qty,
                "start_time": wo.start_time, "end_time": wo.end_time, "deadline": wo.deadline,
                "assigned_to": wo.assigned_to, "sewing_flow_id": wo.sewing_flow_id,
                "is_blocked": wo.is_blocked, "block_reason": wo.block_reason, "notes": wo.notes,
            }
            for wo in work_orders
        ],
    }
    return {
        **row,
        "order": production_payload,
        "items": [
            {
                "id": item.id, "model_id": item.model_id, "model": model_map.get(int(item.model_id)),
                "color": item.color, "size": item.size, "quantity": item.planned_quantity,
                "unit_price": 0.0, "line_total": 0.0, "printing_required": item.printing_required,
            }
            for item in (po.items or [])
        ],
        "production_orders": [production_payload],
        "materials": {"spent": materials_spent, "movements": material_movements},
        "packages": [
            {
                "id": pkg.id, "package_no": pkg.package_no, "barcode": pkg.barcode,
                "production_order_id": pkg.production_order_id, "production_batch_id": pkg.production_batch_id,
                "model_id": pkg.model_id, "model": model_map.get(int(pkg.model_id)), "color": pkg.color,
                "package_type": pkg.package_type, "total_quantity": pkg.total_quantity, "capacity": pkg.capacity,
                "weight_kg": _num(pkg.weight_kg), "warehouse_id": pkg.warehouse_id,
                "storage_cell": pkg.storage_cell, "storage_shelf": pkg.storage_shelf,
                "storage_placed_at": pkg.storage_placed_at, "status": pkg.status, "packed_by": pkg.packed_by,
                "packed_at": pkg.packed_at, "received_by": pkg.received_by, "received_at": pkg.received_at,
                "shipped_at": pkg.shipped_at, "notes": pkg.notes,
                "items": [
                    {"id": item.id, "model_id": item.model_id, "model": model_map.get(int(item.model_id)), "color": item.color, "size": item.size, "quantity": item.quantity}
                    for item in (pkg.items or [])
                ],
                "scan_logs": [
                    {"id": scan.id, "scan_type": scan.scan_type, "location": scan.location, "scanned_by": scan.scanned_by, "scanned_at": scan.scanned_at}
                    for scan in (pkg.scan_logs or [])
                ],
            }
            for pkg in packages
        ],
        "shipments": [], "invoices": [], "payments": [],
        "step_records": _production_step_records(db, production_orders), "timeline": timeline,
    }


def _is_any_stock_token(value: str | None) -> bool:
    token = str(value or "").strip().lower()
    return token in {"", "*", "any", "mixed", "__any__", "pack60", "bag"}


def _stock_variant_key(
    model_id: int | None,
    color: str,
    size: str,
    brand_id: int | None,
    finished_goods_stock_id: int | None = None,
) -> tuple[str, int, str, str, int | None]:
    if finished_goods_stock_id is not None:
        return ("stock", int(finished_goods_stock_id), "", "", None)
    if model_id is None:
        raise HTTPException(400, "A model or ready-stock product is required")
    return (
        "model",
        int(model_id),
        str(color or "").strip(),
        str(size or "").strip(),
        brand_id,
    )


def _stock_rows_for_variant(
    db: DbSession,
    *,
    model_id: int | None,
    color: str,
    size: str,
    brand_id: int | None,
    finished_goods_stock_id: int | None = None,
) -> list[FinishedGoodsStock]:
    qry = db.query(FinishedGoodsStock).filter(
        FinishedGoodsStock.status == "available",
        FinishedGoodsStock.available_qty > 0,
    )
    if finished_goods_stock_id is not None:
        qry = qry.filter(FinishedGoodsStock.id == finished_goods_stock_id)
    else:
        if model_id is None:
            return []
        qry = qry.filter(FinishedGoodsStock.model_id == model_id)
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
        summary = ", ".join(
            (
                f"S{r['finished_goods_stock_id']}: {r['shortage']}"
                if r.get("finished_goods_stock_id")
                else f"M{r['model_id']} {r['color']}/{r['size']}: {r['shortage']}"
            )
            for r in shortages[:6]
        )
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
    requested_by_variant: dict[tuple[str, int, str, str, int | None], int] = defaultdict(int)
    for line in line_rows:
        key = _stock_variant_key(
            line.model_id,
            line.color,
            line.size,
            line.brand_id,
            line.finished_goods_stock_id,
        )
        requested_by_variant[key] += int(line.quantity or 0)

    existing_rows = (
        db.query(StockReservation, FinishedGoodsStock)
        .join(FinishedGoodsStock, FinishedGoodsStock.id == StockReservation.finished_goods_stock_id)
        .filter(StockReservation.sales_order_id == so.id)
        .all()
    )

    outstanding_by_variant: dict[tuple[str, int, str, str, int | None], int] = {}
    for key, requested_qty in requested_by_variant.items():
        reference_type, reference_id, color, size, brand_id = key
        any_color = _is_any_stock_token(color)
        any_size = _is_any_stock_token(size)
        already_reserved = 0
        for reservation, stock in existing_rows:
            if reference_type == "stock":
                if int(stock.id) != int(reference_id):
                    continue
            else:
                if stock.model_id is None or int(stock.model_id) != int(reference_id):
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
    for (reference_type, reference_id, color, size, brand_id), requested_qty in outstanding_by_variant.items():
        if requested_qty <= 0:
            continue
        model_id = reference_id if reference_type == "model" else None
        stock_id = reference_id if reference_type == "stock" else None
        available_qty = sum(
            int(row.available_qty or 0)
            for row in _stock_rows_for_variant(
                db,
                model_id=model_id,
                color=color,
                size=size,
                brand_id=brand_id,
                finished_goods_stock_id=stock_id,
            )
        )
        if available_qty < requested_qty:
            shortages_precheck.append(
                {
                    "model_id": model_id,
                    "finished_goods_stock_id": stock_id,
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
            (
                f"S{s['finished_goods_stock_id']} need {s['requested']}, available {s['available']}"
                if s.get("finished_goods_stock_id")
                else f"M{s['model_id']} {s['color']}/{s['size']} need {s['requested']}, available {s['available']}"
            )
            for s in shortages_precheck[:4]
        )
        if len(shortages_precheck) > 4:
            summary += f" (+{len(shortages_precheck) - 4} more)"
        raise HTTPException(409, f"Not enough branded stock to fulfill this order: {summary}")

    reservations: list[dict] = []
    shortages: list[dict] = []
    for (reference_type, reference_id, color, size, brand_id), requested_qty in outstanding_by_variant.items():
        if requested_qty <= 0:
            continue
        model_id = reference_id if reference_type == "model" else None
        stock_id = reference_id if reference_type == "stock" else None
        needed = int(requested_qty)
        stocks = _stock_rows_for_variant(
            db,
            model_id=model_id,
            color=color,
            size=size,
            brand_id=brand_id,
            finished_goods_stock_id=stock_id,
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
                    "finished_goods_stock_id": stock_id,
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
    created_from: date | None = None,
    created_to: date | None = None,
    page: int = 1, page_size: int = 50,
    include_total: bool = False,
):
    qry = db.query(SalesOrder).outerjoin(Customer, Customer.id == SalesOrder.customer_id)
    if status: qry = qry.filter(SalesOrder.status == status)
    if order_type: qry = qry.filter(SalesOrder.order_type == order_type)
    if customer_id: qry = qry.filter(SalesOrder.customer_id == customer_id)
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
    start, end = date_filter_bounds(created_from, created_to)
    if start: qry = qry.filter(SalesOrder.created_at >= start)
    if end: qry = qry.filter(SalesOrder.created_at <= end)
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
    created_from: date | None = None,
    created_to: date | None = None,
    page: int = 1,
    page_size: int = 50,
    include_total: bool = False,
):
    qry = db.query(SalesOrder).outerjoin(Customer, Customer.id == SalesOrder.customer_id)
    stock_qry = (
        db.query(ProductionOrder)
        .options(
            joinedload(ProductionOrder.planning_order),
            joinedload(ProductionOrder.items),
            joinedload(ProductionOrder.batches),
            joinedload(ProductionOrder.work_orders),
        )
        .outerjoin(Model, Model.id == ProductionOrder.model_id)
        .outerjoin(BrandedPlanningOrder, BrandedPlanningOrder.id == ProductionOrder.planning_order_id)
        .filter(ProductionOrder.sales_order_id.is_(None), ProductionOrder.production_type == "branded_stock")
    )
    if status:
        qry = qry.filter(SalesOrder.status == status)
        stock_qry = stock_qry.filter(ProductionOrder.status == status)
    if order_type:
        qry = qry.filter(SalesOrder.order_type == order_type)
        stock_qry = stock_qry.filter(ProductionOrder.production_type == order_type)
    if customer_id:
        qry = qry.filter(SalesOrder.customer_id == customer_id)
        stock_qry = stock_qry.filter(False)
    start, end = date_filter_bounds(created_from, created_to)
    if start:
        qry = qry.filter(SalesOrder.created_at >= start)
        stock_qry = stock_qry.filter(ProductionOrder.created_at >= start)
    if end:
        qry = qry.filter(SalesOrder.created_at <= end)
        stock_qry = stock_qry.filter(ProductionOrder.created_at <= end)
    if q:
        term = q.strip()
        exact_branded_group = (
            db.query(BrandedPlanningOrder.id)
            .filter(BrandedPlanningOrder.order_no == term)
            .first()
        )
        if exact_branded_group:
            qry = qry.filter(False)
            stock_qry = stock_qry.filter(BrandedPlanningOrder.order_no == term)
        else:
            like = f"%{term}%"
            qry = qry.filter(
                or_(
                    SalesOrder.order_no.ilike(like),
                    SalesOrder.status.ilike(like),
                    SalesOrder.order_type.ilike(like),
                    Customer.name.ilike(like),
                )
            )
            stock_qry = stock_qry.filter(
                or_(
                    ProductionOrder.production_no.ilike(like),
                    ProductionOrder.status.ilike(like),
                    ProductionOrder.production_type.ilike(like),
                    Model.code.ilike(like),
                    Model.name.ilike(like),
                    BrandedPlanningOrder.order_no.ilike(like),
                    BrandedPlanningOrder.ordered_for_name.ilike(like),
                )
            )
    safe_page = max(1, page)
    safe_size = max(1, min(page_size, 200))
    candidates = (
        [(so.created_at, "sales", so) for so in qry.all()]
        + [(po.created_at, "production", po) for po in stock_qry.all()]
    )
    candidates.sort(key=lambda entry: ((entry[0].isoformat() if entry[0] else ""), int(entry[2].id)), reverse=True)
    total = len(candidates)
    start_index = (safe_page - 1) * safe_size
    selected = candidates[start_index:start_index + safe_size]
    payload = [
        _sales_order_history(db, entity, include_detail=False)
        if kind == "sales" else _stock_production_history(db, entity, include_detail=False)
        for _, kind, entity in selected
    ]
    if include_total:
        return {"rows": payload, "total": total, "page": safe_page, "page_size": safe_size}
    return payload


@router.get("/history/production/{pid}")
def get_stock_production_history(pid: int, db: DbSession, _: CurrentUser):
    po = (
        db.query(ProductionOrder)
        .options(
            joinedload(ProductionOrder.planning_order),
            joinedload(ProductionOrder.items),
            joinedload(ProductionOrder.batches),
            joinedload(ProductionOrder.work_orders),
        )
        .filter(
            ProductionOrder.id == pid,
            ProductionOrder.sales_order_id.is_(None),
            ProductionOrder.production_type == "branded_stock",
        )
        .first()
    )
    if not po:
        raise HTTPException(404, "Stock production order not found")
    return _stock_production_history(db, po, include_detail=True)


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
        if int(item.quantity or 0) <= 0:
            raise HTTPException(400, "Sales order quantity must be greater than zero")
        if float(item.unit_price or 0) < 0:
            raise HTTPException(400, "Sales order unit price cannot be negative")

        item_data = item.model_dump()
        stock = None
        source_model_code = None
        source_model_name = None
        if item.finished_goods_stock_id is not None:
            if payload.order_type != "branded_stock_sale":
                raise HTTPException(400, "Ready-stock selection only applies to stock sales")
            stock = db.get(FinishedGoodsStock, int(item.finished_goods_stock_id))
            if not stock:
                raise HTTPException(404, f"Ready stock {item.finished_goods_stock_id} not found")
            if stock.model_id is not None:
                if item.model_id is not None and int(item.model_id) != int(stock.model_id):
                    raise HTTPException(409, "Selected stock does not match the requested model")
                item_data["model_id"] = int(stock.model_id)
            elif item.model_id is not None:
                raise HTTPException(409, "Model-less legacy stock cannot be assigned a model during sale")
            else:
                package = db.get(Package, stock.package_id) if stock.package_id else None
                identity = package_legacy_identity(db, package)
                source_model_code = identity.get("model_code")
                source_model_name = identity.get("model_name")
                if not package or not package.legacy_receipt_id or not source_model_code:
                    raise HTTPException(409, "Model-less stock is missing its legacy receipt identity")
                item_data["source_type"] = "legacy_stock"
            if item_data.get("brand_id") is None and stock.brand_id is not None:
                item_data["brand_id"] = int(stock.brand_id)
            if item_data.get("collection_id") is None and stock.collection_id is not None:
                item_data["collection_id"] = int(stock.collection_id)
        else:
            if item.model_id is None:
                raise HTTPException(400, "Select a model or an old inventory product")
            if not db.get(Model, item.model_id):
                raise HTTPException(404, f"Model {item.model_id} not found")

        line = SalesOrderItem(
            sales_order_id=so.id,
            source_model_code=source_model_code,
            source_model_name=source_model_name,
            **item_data,
        )
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
def reserve_stock(
    sid: int,
    db: DbSession,
    current: User = Depends(require_permissions("sales.orders", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """For branded_stock_sale: try to reserve from FinishedGoodsStock for each line."""
    fingerprint_payload = {"sales_order_id": sid}
    replay = replay_idempotent_response(db, scope="sales.reserve-stock", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay

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
    response = {"reservations": reservations, "shortages": shortages}
    store_idempotent_response(
        db,
        scope="sales.reserve-stock",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
    )
    db.commit()
    return response


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
