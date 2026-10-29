"""Order-history assembly for sales orders and stock production orders.

Contract for `list_sales_order_history`:
* input: the same filters the history endpoint accepts
* output: one ledger row per sales order or stock production order, newest
  first, or a page envelope when `include_total` is set
* refusals: 404 when a single order or production order does not exist
* records: read-only; the ledger never writes
* transaction owner: the caller
"""
from collections import defaultdict
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import func, literal, or_
from sqlalchemy.orm import Session, joinedload

from app.core.dt import date_filter_bounds
from app.core.model_search import normalized_model_code_column, normalized_model_code_pattern
from app.core.order_reference import order_reference_contains
from app.core.signing import sign_path
from app.models.model_images_service import model_variant_picture_url
from app.models.sales.orders_service import _serialize_sales_order
from app.schemas import (
    AuditLog, BrandedPlanningOrder, Bundle, CuttingRecord, Customer, FinishedGoodsStock, Invoice,
    Item, MaterialReservation, Model, Package, PackagingRecord, Payment, PrintingRecord,
    ProductionOrder, QualityCheck, SalesOrder, SalesOrderItem, SewingRecord, Shipment, ShipmentPackage,
    StockBatch, StockMovement, User,
)


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


def _model_refs(db: Session, model_ids: set[int]) -> dict[int, dict]:
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


def _history_products(db: Session, model_ids: set[int]) -> list[dict]:
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
        picture_url = model_variant_picture_url(model)
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


def _production_step_records(db: Session, production_orders: list[ProductionOrder]) -> dict:
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


def _sales_order_history(db: Session, so: SalesOrder, *, include_detail: bool = False) -> dict:
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

    product_model_ids = {int(item.model_id) for item in sales_items if item.model_id}
    for production_order in production_orders:
        if production_order.model_id:
            product_model_ids.add(int(production_order.model_id))
        product_model_ids.update(int(item.model_id) for item in (production_order.items or []) if item.model_id)

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
        "products": _history_products(db, product_model_ids),
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
        timeline.append(_history_event("invoice", f"Invoice {inv.invoice_no}", inv.issued_at or inv.created_at, invoice_id=inv.id, amount=_num(inv.amount), status=inv.status.value))
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
                "model": model_map.get(int(pkg.model_id)),
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
                "status": inv.status.value,
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


def _stock_production_history(db: Session, po: ProductionOrder, *, include_detail: bool = False) -> dict:
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


def list_sales_order_history(
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
            model_code_like = normalized_model_code_pattern(term)
            sales_model_match = (
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
                    sales_model_match,
                )
            )
            stock_qry = stock_qry.filter(
                or_(
                    order_reference_contains(ProductionOrder.production_no, like),
                    ProductionOrder.status.ilike(like),
                    ProductionOrder.production_type.ilike(like),
                    normalized_model_code_column(Model.code).ilike(model_code_like),
                    Model.name.ilike(like),
                    order_reference_contains(BrandedPlanningOrder.order_no, like),
                    BrandedPlanningOrder.ordered_for_name.ilike(like),
                )
            )
    safe_page = max(1, page)
    safe_size = max(1, min(page_size, 200))
    # Count, order and page the candidate set in SQL, then hydrate only the ids
    # on this page. Hydrating first meant every caller paid for the whole
    # history - including the joined production children - to show ten rows.
    # The ordering keys reproduce the previous Python sort exactly:
    # `created_at` descending with `nullslast` matches the old `""` sort key
    # for a missing timestamp, `row_id` descending matches the integer id, and
    # the explicit kind rank reproduces list.sort's stability, which kept a
    # sales row ahead of a production row when timestamp and id were equal.
    sales_candidates = qry.enable_eagerloads(False).with_entities(
        SalesOrder.created_at.label("created_at"),
        literal("sales").label("kind"),
        literal(0).label("kind_order"),
        SalesOrder.id.label("row_id"),
    )
    production_candidates = stock_qry.enable_eagerloads(False).with_entities(
        ProductionOrder.created_at.label("created_at"),
        literal("production").label("kind"),
        literal(1).label("kind_order"),
        ProductionOrder.id.label("row_id"),
    )
    candidate_union = sales_candidates.union_all(production_candidates).subquery()
    total = (
        int(db.query(func.count()).select_from(candidate_union).scalar() or 0)
        if include_total else 0
    )
    start_index = (safe_page - 1) * safe_size
    selected = (
        db.query(
            candidate_union.c.created_at,
            candidate_union.c.kind,
            candidate_union.c.row_id,
        )
        .order_by(
            candidate_union.c.created_at.desc().nullslast(),
            candidate_union.c.row_id.desc(),
            candidate_union.c.kind_order.asc(),
        )
        .offset(start_index)
        .limit(safe_size)
        .all()
    )
    sales_ids = [int(row_id) for _, kind, row_id in selected if kind == "sales"]
    production_ids = [int(row_id) for _, kind, row_id in selected if kind == "production"]
    selected_sales = {
        row.id: row for row in db.query(SalesOrder).filter(SalesOrder.id.in_(sales_ids)).all()
    } if sales_ids else {}
    selected_production = {
        row.id: row for row in db.query(ProductionOrder).options(
            joinedload(ProductionOrder.planning_order),
            joinedload(ProductionOrder.items),
            joinedload(ProductionOrder.batches),
            joinedload(ProductionOrder.work_orders),
        ).filter(ProductionOrder.id.in_(production_ids)).all()
    } if production_ids else {}
    payload = [
        _sales_order_history(db, entity, include_detail=False)
        if kind == "sales" else _stock_production_history(db, entity, include_detail=False)
        for _, kind, row_id in selected
        # A candidate deleted between the two statements leaves a short page
        # rather than a failed request.
        if (entity := (selected_sales if kind == "sales" else selected_production).get(int(row_id))) is not None
    ]
    if include_total:
        return {"rows": payload, "total": total, "page": safe_page, "page_size": safe_size}
    return payload


def get_stock_production_history(pid: int, db: Session):
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


def get_sales_order_history(sid: int, db: Session):
    so = db.query(SalesOrder).filter(SalesOrder.id == sid).first()
    if not so:
        raise HTTPException(404, "Sales order not found")
    return _sales_order_history(db, so, include_detail=True)
