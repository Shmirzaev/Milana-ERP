from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from html import escape
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AuditLog,
    Brand,
    Bundle,
    Collection,
    Customer,
    CuttingRecord,
    Department,
    Item,
    Model,
    Package,
    PackagingRecord,
    PrintingRecord,
    ProductionBatch,
    ProductionOrder,
    QualityCheck,
    SalesOrder,
    SewingRecord,
    Shipment,
    ShipmentPackage,
    ShipmentScanLog,
    StockBatch,
    Supplier,
    SystemSetting,
    Warehouse,
    WasteRecord,
    WorkOrder,
    PackageBatchAllocation,
)
from app.services.inventory import accessory_issue_summary
from app.services.packages import format_storage_location


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _num(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def _dt(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _h(value: Any) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def _company_info(db: Session) -> dict:
    defaults = {
        "name": "Milana Ecosystem",
        "logo_url": None,
        "address": None,
        "phone": None,
        "email": None,
    }
    row = db.query(SystemSetting).filter(SystemSetting.key == "company_info").first()
    if row and isinstance(row.value_json, dict):
        return {**defaults, **row.value_json}
    return defaults


def _basic(obj: Any, *fields: str) -> dict[str, Any] | None:
    if obj is None:
        return None
    out: dict[str, Any] = {"id": int(obj.id)} if getattr(obj, "id", None) is not None else {}
    for field in fields:
        out[field] = _num(getattr(obj, field, None))
    return out


def _work_orders_for_po(db: Session, po_id: int) -> list[WorkOrder]:
    return (
        db.query(WorkOrder)
        .filter(WorkOrder.production_order_id == po_id)
        .order_by(WorkOrder.id.asc())
        .all()
    )


def _package_batch_ids(pkg: Package | None) -> set[int]:
    if not pkg:
        return set()
    ids = {int(a.production_batch_id) for a in (pkg.batch_allocations or []) if a.production_batch_id}
    if pkg.production_batch_id:
        ids.add(int(pkg.production_batch_id))
    return ids


def _filter_records_for_package(records: list[Any], batch_ids: set[int], *, strict: bool = False) -> list[Any]:
    if not batch_ids:
        return records
    exact = [row for row in records if getattr(row, "production_batch_id", None) in batch_ids]
    return exact if strict or exact else records


def _related_shipments_for_package(db: Session, pkg_id: int) -> list[Shipment]:
    rows = (
        db.query(Shipment)
        .join(ShipmentPackage, ShipmentPackage.shipment_id == Shipment.id)
        .filter(ShipmentPackage.package_id == pkg_id)
        .order_by(Shipment.id.desc())
        .all()
    )
    return rows


def _sales_order_payload(db: Session, sales_order: SalesOrder | None) -> tuple[dict | None, dict | None]:
    if not sales_order:
        return None, None
    customer = db.get(Customer, sales_order.customer_id) if sales_order.customer_id else None
    return (
        {
            "id": int(sales_order.id),
            "order_no": sales_order.order_no,
            "order_type": sales_order.order_type,
            "status": sales_order.status,
            "deadline": _dt(sales_order.deadline),
            "created_at": _dt(sales_order.created_at),
        },
        _basic(customer, "name", "phone", "email", "address") if customer else None,
    )


def _brand_collection_model(
    db: Session,
    *,
    model_id: int | None,
    brand_id: int | None,
    collection_id: int | None,
) -> tuple[dict | None, dict | None, dict | None]:
    model = db.get(Model, model_id) if model_id else None
    collection = db.get(Collection, collection_id or (model.collection_id if model else None)) if (collection_id or (model and model.collection_id)) else None
    brand = db.get(Brand, brand_id or (collection.brand_id if collection else None) or (model.brand_id if model else None)) if (brand_id or collection or (model and model.brand_id)) else None
    return (
        _basic(brand, "name", "description", "logo_url") if brand else None,
        _basic(collection, "name", "season", "year", "status") if collection else None,
        _basic(model, "code", "name", "category", "product_type", "season", "status") if model else None,
    )


def _production_order_payload(po: ProductionOrder | None) -> dict | None:
    if not po:
        return None
    return {
        "id": int(po.id),
        "production_no": po.production_no,
        "order_no": po.order_no,
        "production_type": po.production_type,
        "status": po.status,
        "planned_quantity": int(po.planned_quantity or 0),
        "sales_order_id": int(po.sales_order_id) if po.sales_order_id else None,
        "collection_id": int(po.collection_id) if po.collection_id else None,
        "model_id": int(po.model_id),
        "start_date": _dt(po.start_date),
        "deadline": _dt(po.deadline),
    }


def _cutting_payload(db: Session, row: CuttingRecord) -> tuple[dict, dict | None, str | None]:
    batch = db.get(StockBatch, row.fabric_batch_id) if row.fabric_batch_id else None
    item = batch.item if batch and batch.item else (db.get(Item, batch.item_id) if batch else None)
    supplier = db.get(Supplier, batch.supplier_id) if batch and batch.supplier_id else None
    warehouse = db.get(Warehouse, batch.warehouse_id) if batch and batch.warehouse_id else None
    material = None
    if batch:
        material = {
            "id": int(batch.id),
            "batch_no": batch.batch_no,
            "item_id": int(batch.item_id),
            "item_sku": item.sku if item else None,
            "item_name": item.name if item else None,
            "supplier_id": int(batch.supplier_id) if batch.supplier_id else None,
            "supplier_name": supplier.name if supplier else None,
            "color": batch.color,
            "old_code": batch.old_code,
            "color_code": batch.color_code,
            "width": _num(batch.width),
            "gsm": _num(batch.gsm),
            "quantity": _num(batch.quantity),
            "unit": batch.unit,
            "warehouse_id": int(batch.warehouse_id),
            "warehouse_name": warehouse.name if warehouse else None,
            "qc_status": batch.qc_status,
            "received_date": _dt(batch.received_date),
        }
    payload = {
        "id": int(row.id),
        "work_order_id": int(row.work_order_id),
        "production_batch_id": int(row.production_batch_id) if row.production_batch_id else None,
        "fabric_batch_id": int(row.fabric_batch_id) if row.fabric_batch_id else None,
        "input_quantity": _num(row.input_quantity),
        "input_unit": row.input_unit,
        "cut_pieces": int(row.cut_pieces or 0),
        "report_piece_count": int(row.report_piece_count or 0),
        "passed_pieces": int(row.passed_pieces or 0),
        "defective_pieces": int(row.defective_pieces or 0),
        "waste_quantity": _num(row.waste_quantity),
        "waste_unit": row.waste_unit,
        "layer_material_kg": _num(row.layer_material_kg),
        "beika_kg": _num(row.beika_kg),
        "material_rolls_used": _num(row.material_rolls_used),
        "bundle_count": int(row.bundle_count or 0),
        "total_bundled_quantity": int(row.total_bundled_quantity or 0),
        "operator_id": int(row.operator_id) if row.operator_id else None,
        "notes": row.notes,
        "created_at": _dt(row.created_at),
        "materials": [
            {
                "stock_batch_id": int(usage.stock_batch_id),
                "quantity": _num(usage.quantity),
                "unit": usage.unit,
                "position": int(usage.position or 0),
            }
            for usage in (getattr(row, "materials", None) or [])
        ],
        "beika_materials": [
            {
                "stock_batch_id": int(usage.stock_batch_id),
                "quantity": _num(usage.quantity),
                "unit": usage.unit,
                "position": int(usage.position or 0),
            }
            for usage in (getattr(row, "beika_materials", None) or [])
        ],
    }
    gap = None if batch else "No fabric batch linked to cutting record"
    return payload, material, gap


def _bundle_payload(db: Session, bundle: Bundle) -> dict:
    departments = {
        int(d.id): d
        for d in db.query(Department).filter(
            Department.id.in_([
                did for did in [bundle.current_department_id, bundle.next_department_id] if did
            ])
        ).all()
    } if (bundle.current_department_id or bundle.next_department_id) else {}
    scan_logs = [
        {
            "id": int(log.id),
            "scan_type": log.scan_type,
            "scanned_by": int(log.scanned_by) if log.scanned_by else None,
            "from_department_id": int(log.from_department_id) if log.from_department_id else None,
            "to_department_id": int(log.to_department_id) if log.to_department_id else None,
            "location": log.location,
            "scanned_at": _dt(log.scanned_at),
        }
        for log in (bundle.scan_logs or [])
    ]
    return {
        "id": int(bundle.id),
        "bundle_no": bundle.bundle_no,
        "barcode": bundle.barcode,
        "qr_code_url": bundle.qr_code_url,
        "production_order_id": int(bundle.production_order_id),
        "production_batch_id": int(bundle.production_batch_id) if bundle.production_batch_id else None,
        "sales_order_id": int(bundle.sales_order_id) if bundle.sales_order_id else None,
        "model_id": int(bundle.model_id),
        "color": bundle.color,
        "size": bundle.size,
        "quantity": int(bundle.quantity or 0),
        "status": bundle.status,
        "current_department_id": int(bundle.current_department_id) if bundle.current_department_id else None,
        "current_department_name": departments.get(int(bundle.current_department_id)).name if bundle.current_department_id and int(bundle.current_department_id) in departments else None,
        "next_department_id": int(bundle.next_department_id) if bundle.next_department_id else None,
        "next_department_name": departments.get(int(bundle.next_department_id)).name if bundle.next_department_id and int(bundle.next_department_id) in departments else None,
        "sewing_factory_code": bundle.sewing_factory_code,
        "scan_logs": scan_logs,
        "created_at": _dt(bundle.created_at),
    }


def _record_payload(row: Any, fields: list[str]) -> dict:
    out = {"id": int(row.id), "work_order_id": int(row.work_order_id)}
    if getattr(row, "production_batch_id", None):
        out["production_batch_id"] = int(row.production_batch_id)
    for field in fields:
        value = getattr(row, field, None)
        out[field] = _num(value)
    out["created_at"] = _dt(getattr(row, "created_at", None))
    return out


def _package_payload(db: Session, pkg: Package) -> dict:
    warehouse = db.get(Warehouse, pkg.warehouse_id) if pkg.warehouse_id else None
    return {
        "id": int(pkg.id),
        "package_no": pkg.package_no,
        "barcode": pkg.barcode,
        "qr_code_url": pkg.qr_code_url,
        "production_order_id": int(pkg.production_order_id),
        "production_batch_id": int(pkg.production_batch_id) if pkg.production_batch_id else None,
        "sales_order_id": int(pkg.sales_order_id) if pkg.sales_order_id else None,
        "brand_id": int(pkg.brand_id) if pkg.brand_id else None,
        "collection_id": int(pkg.collection_id) if pkg.collection_id else None,
        "model_id": int(pkg.model_id),
        "color": pkg.color,
        "package_type": pkg.package_type,
        "total_quantity": int(pkg.total_quantity or 0),
        "capacity": int(pkg.capacity or 0),
        "weight_kg": _num(pkg.weight_kg),
        "warehouse_id": int(pkg.warehouse_id) if pkg.warehouse_id else None,
        "warehouse_name": warehouse.name if warehouse else None,
        "storage_cell": pkg.storage_cell,
        "storage_shelf": pkg.storage_shelf,
        "storage_location": format_storage_location(pkg.storage_cell, pkg.storage_shelf),
        "status": pkg.status,
        "packed_at": _dt(pkg.packed_at),
        "received_at": _dt(pkg.received_at),
        "shipped_at": _dt(pkg.shipped_at),
        "created_at": _dt(pkg.created_at),
    }


def _package_items(pkg: Package) -> list[dict]:
    return [
        {
            "id": int(item.id),
            "package_id": int(item.package_id),
            "model_id": int(item.model_id),
            "color": item.color,
            "size": item.size,
            "quantity": int(item.quantity or 0),
        }
        for item in sorted((pkg.items or []), key=lambda row: row.id)
    ]


def _package_scans(pkg: Package) -> list[dict]:
    return [
        {
            "id": int(log.id),
            "scan_type": log.scan_type,
            "scanned_by": int(log.scanned_by) if log.scanned_by else None,
            "location": log.location,
            "scanned_at": _dt(log.scanned_at),
        }
        for log in (pkg.scan_logs or [])
    ]


def _shipment_payload(db: Session, shipment: Shipment | None) -> dict | None:
    if not shipment:
        return None
    so = db.get(SalesOrder, shipment.sales_order_id) if shipment.sales_order_id else None
    customer = db.get(Customer, shipment.customer_id or (so.customer_id if so else None)) if (shipment.customer_id or (so and so.customer_id)) else None
    return {
        "id": int(shipment.id),
        "shipment_no": shipment.shipment_no,
        "status": shipment.status,
        "sales_order_id": int(shipment.sales_order_id) if shipment.sales_order_id else None,
        "sales_order_no": so.order_no if so else None,
        "customer_id": int(customer.id) if customer else None,
        "customer_name": customer.name if customer else None,
        "shipped_at": _dt(shipment.shipped_at),
        "delivered_at": _dt(shipment.delivered_at),
        "created_at": _dt(shipment.created_at),
        "notes": shipment.notes,
    }


def _shipment_packages(db: Session, shipment_ids: list[int]) -> list[dict]:
    if not shipment_ids:
        return []
    rows = (
        db.query(ShipmentPackage, Package)
        .join(Package, Package.id == ShipmentPackage.package_id)
        .filter(ShipmentPackage.shipment_id.in_(shipment_ids))
        .order_by(ShipmentPackage.shipment_id.asc(), ShipmentPackage.id.asc())
        .all()
    )
    return [
        {
            "id": int(link.id),
            "shipment_id": int(link.shipment_id),
            "package_id": int(link.package_id),
            "package_no": pkg.package_no if pkg else None,
            "barcode": pkg.barcode if pkg else None,
            "quantity": int(link.quantity or 0),
        }
        for link, pkg in rows
    ]


def _shipment_scan_logs(db: Session, shipment_ids: list[int], package_id: int | None = None) -> list[dict]:
    if not shipment_ids:
        return []
    qry = db.query(ShipmentScanLog).filter(ShipmentScanLog.shipment_id.in_(shipment_ids))
    if package_id is not None:
        qry = qry.filter(ShipmentScanLog.package_id == package_id)
    return [
        {
            "id": int(log.id),
            "shipment_id": int(log.shipment_id),
            "package_id": int(log.package_id) if log.package_id else None,
            "scanned_code": log.scanned_code,
            "scan_result": log.scan_result,
            "message": log.message,
            "scanned_by": int(log.scanned_by) if log.scanned_by else None,
            "scanned_at": _dt(log.scanned_at),
        }
        for log in qry.order_by(ShipmentScanLog.scanned_at.asc(), ShipmentScanLog.id.asc()).all()
    ]


def _audit_summary(db: Session, entity_refs: list[tuple[str, int | None]]) -> dict:
    filters = []
    for entity_type, entity_id in entity_refs:
        if entity_id is None:
            continue
        filters.append((AuditLog.entity_type == entity_type) & (AuditLog.entity_id == int(entity_id)))
    if not filters:
        return {"count": 0, "recent": []}
    rows = (
        db.query(AuditLog)
        .filter(or_(*filters))
        .order_by(AuditLog.id.desc())
        .limit(10)
        .all()
    )
    return {
        "count": len(rows),
        "recent": [
            {
                "id": int(row.id),
                "action": row.action,
                "entity_type": row.entity_type,
                "entity_id": int(row.entity_id) if row.entity_id else None,
                "created_at": _dt(row.created_at),
            }
            for row in rows
        ],
    }


def _color_size_from_package(pkg: Package | None) -> list[dict]:
    if not pkg:
        return []
    return [
        {"color": item.color, "size": item.size, "quantity": int(item.quantity or 0)}
        for item in sorted((pkg.items or []), key=lambda row: (row.color, row.size, row.id))
    ]


def _color_size_from_po(po: ProductionOrder | None) -> list[dict]:
    if not po:
        return []
    return [
        {"color": item.color, "size": item.size, "quantity": int(item.planned_quantity or 0)}
        for item in sorted((po.items or []), key=lambda row: (row.color, row.size, row.id))
    ]


def build_traceability(
    db: Session,
    *,
    subject_type: str,
    production_order: ProductionOrder | None,
    package: Package | None = None,
    bundle: Bundle | None = None,
    shipment: Shipment | None = None,
    production_batch_id: int | None = None,
) -> dict:
    gaps: list[str] = []
    po = production_order
    if not po and package:
        po = db.get(ProductionOrder, package.production_order_id)
    if not po and bundle:
        po = db.get(ProductionOrder, bundle.production_order_id)

    sales_order = None
    if package and package.sales_order_id:
        sales_order = db.get(SalesOrder, package.sales_order_id)
    if not sales_order and po and po.sales_order_id:
        sales_order = db.get(SalesOrder, po.sales_order_id)
    if not sales_order and shipment and shipment.sales_order_id:
        sales_order = db.get(SalesOrder, shipment.sales_order_id)

    sales_payload, customer_payload = _sales_order_payload(db, sales_order)
    brand_id = package.brand_id if package and package.brand_id else None
    collection_id = package.collection_id if package and package.collection_id else None
    model_id = package.model_id if package else (bundle.model_id if bundle else (po.model_id if po else None))
    if not collection_id and po:
        collection_id = po.collection_id
    if bundle:
        brand_id = brand_id or bundle.brand_id
        collection_id = collection_id or bundle.collection_id
    brand_payload, collection_payload, model_payload = _brand_collection_model(
        db,
        model_id=model_id,
        brand_id=brand_id,
        collection_id=collection_id,
    )

    work_orders = _work_orders_for_po(db, int(po.id)) if po else []
    wo_ids = [int(wo.id) for wo in work_orders]
    batch_ids = _package_batch_ids(package)
    strict_batch_scope = production_batch_id is not None
    if production_batch_id is not None:
        batch_ids = {int(production_batch_id)}
    if bundle and bundle.production_batch_id:
        batch_ids.add(int(bundle.production_batch_id))

    cutting_rows = []
    material_batches: list[dict] = []
    if wo_ids:
        all_cutting = (
            db.query(CuttingRecord)
            .filter(CuttingRecord.work_order_id.in_(wo_ids))
            .order_by(CuttingRecord.created_at.asc(), CuttingRecord.id.asc())
            .all()
        )
        for row in _filter_records_for_package(all_cutting, batch_ids, strict=strict_batch_scope):
            payload, material, gap = _cutting_payload(db, row)
            cutting_rows.append(payload)
            if material and all(material["id"] != existing["id"] for existing in material_batches):
                material_batches.append(material)
            if gap:
                gaps.append(gap)
    if po and not cutting_rows:
        gaps.append("No cutting record found for production order")

    bundles_query = db.query(Bundle).options(selectinload(Bundle.scan_logs))
    if po:
        bundles_query = bundles_query.filter(Bundle.production_order_id == po.id)
        if batch_ids:
            matched = bundles_query.filter(Bundle.production_batch_id.in_(batch_ids)).all()
            bundle_rows = matched if strict_batch_scope or matched else bundles_query.all()
        elif package:
            item_keys = {(item.color, item.size) for item in (package.items or [])}
            bundle_rows = bundles_query.all()
            if item_keys:
                matched = [row for row in bundle_rows if (row.color, row.size) in item_keys]
                bundle_rows = matched if matched else bundle_rows
        else:
            bundle_rows = bundles_query.all()
    elif bundle:
        bundle_rows = [bundle]
    else:
        bundle_rows = []
    if bundle and all(int(row.id) != int(bundle.id) for row in bundle_rows):
        bundle_rows.append(bundle)
    bundle_payloads = [_bundle_payload(db, row) for row in sorted(bundle_rows, key=lambda r: r.id)]
    if po and not bundle_payloads:
        gaps.append("No bundles found for production route")
    for row in bundle_payloads:
        scan_types = {str(log.get("scan_type") or "") for log in row.get("scan_logs") or []}
        if "received_sewing" not in scan_types:
            gaps.append("Bundle history missing sewing receive scan")
            break

    def op_records(model_cls, fields: list[str]) -> list[dict]:
        if not wo_ids:
            return []
        rows = (
            db.query(model_cls)
            .filter(model_cls.work_order_id.in_(wo_ids))
            .order_by(model_cls.created_at.asc(), model_cls.id.asc())
            .all()
        )
        return [
            _record_payload(row, fields)
            for row in _filter_records_for_package(rows, batch_ids, strict=strict_batch_scope)
        ]

    printing_rows = op_records(PrintingRecord, ["input_qty", "printed_qty", "passed_qty", "rejected_qty", "defect_reason", "print_type", "operator_id", "notes"])
    sewing_rows = op_records(SewingRecord, ["input_qty", "sewn_qty", "passed_qty", "failed_qty", "rework_qty", "rejected_qty", "defect_reason", "line_name", "operator_id", "notes"])
    packaging_rows = op_records(PackagingRecord, ["input_qty", "packed_qty", "damaged_qty", "package_count", "total_packed_quantity", "packaging_material_used", "operator_id", "notes"])

    quality_rows = []
    quality_wo_ids = (
        [int(wo.id) for wo in work_orders if int(wo.production_batch_id or 0) == int(production_batch_id or 0)]
        if strict_batch_scope
        else wo_ids
    )
    if quality_wo_ids:
        quality_rows = [
            {
                "id": int(row.id),
                "work_order_id": int(row.work_order_id),
                "department_id": int(row.department_id) if row.department_id else None,
                "checked_qty": int(row.checked_qty or 0),
                "passed_qty": int(row.passed_qty or 0),
                "failed_qty": int(row.failed_qty or 0),
                "defect_type": row.defect_type,
                "defect_reason": row.defect_reason,
                "severity": row.severity,
                "checked_by": int(row.checked_by) if row.checked_by else None,
                "checked_at": _dt(row.checked_at),
            }
            for row in db.query(QualityCheck).filter(QualityCheck.work_order_id.in_(quality_wo_ids)).order_by(QualityCheck.id.asc()).all()
        ]

    waste_rows = []
    if po and not strict_batch_scope:
        waste_rows = [
            {
                "waste_type": waste_type,
                "unit": unit,
                "quantity": float(quantity or 0),
            }
            for waste_type, unit, quantity in (
                db.query(WasteRecord.waste_type, WasteRecord.unit, func.coalesce(func.sum(WasteRecord.quantity), 0))
                .filter(WasteRecord.production_order_id == po.id)
                .group_by(WasteRecord.waste_type, WasteRecord.unit)
                .all()
            )
        ]

    package_payload = _package_payload(db, package) if package else None
    package_items = _package_items(package) if package else []
    package_scan_history = _package_scans(package) if package else []
    if package and not any(log["scan_type"] == "received_storage" for log in package_scan_history):
        gaps.append("Package has no warehouse receive scan")

    shipments = _related_shipments_for_package(db, int(package.id)) if package else ([shipment] if shipment else [])
    shipment_ids = [int(sh.id) for sh in shipments if sh]
    shipment_payloads = [_shipment_payload(db, row) for row in shipments]
    shipment_payloads = [row for row in shipment_payloads if row]
    primary_shipment = _shipment_payload(db, shipment) if shipment else (shipment_payloads[0] if shipment_payloads else None)
    shipment_package_rows = _shipment_packages(db, shipment_ids)
    shipment_scan_rows = _shipment_scan_logs(db, shipment_ids, package_id=int(package.id) if package else None)
    if package and not shipment_payloads:
        gaps.append("Package is not attached to a shipment")
    for sh_payload in shipment_payloads:
        if not sh_payload.get("delivered_at"):
            gaps.append("Shipment has no delivery timestamp")
            break

    warehouse_location = None
    if package:
        warehouse = db.get(Warehouse, package.warehouse_id) if package.warehouse_id else None
        warehouse_location = {
            "warehouse_id": int(package.warehouse_id) if package.warehouse_id else None,
            "warehouse_name": warehouse.name if warehouse else None,
            "storage_cell": package.storage_cell,
            "storage_shelf": package.storage_shelf,
            "location": format_storage_location(package.storage_cell, package.storage_shelf),
            "storage_placed_at": _dt(package.storage_placed_at),
        }

    entity_refs: list[tuple[str, int | None]] = [
        ("ProductionOrder", int(po.id) if po else None),
        ("Package", int(package.id) if package else None),
        ("Shipment", int(primary_shipment["id"]) if primary_shipment else None),
    ]
    seen_gaps: list[str] = []
    for gap in gaps:
        if gap not in seen_gaps:
            seen_gaps.append(gap)

    return {
        "generated_at": _now_iso(),
        "subject_type": subject_type,
        "subject_id": int(package.id) if package else int(bundle.id) if bundle else int(shipment.id) if shipment else int(po.id) if po else None,
        "company": _company_info(db),
        "production_order": _production_order_payload(po),
        "sales_order": sales_payload,
        "customer": customer_payload,
        "brand": brand_payload,
        "collection": collection_payload,
        "model": model_payload,
        "color_size_quantities": _color_size_from_package(package) or _color_size_from_po(po),
        "material_batches": material_batches,
        "cutting_records": cutting_rows,
        "bundles": bundle_payloads,
        "printing_records": printing_rows,
        "sewing_records": sewing_rows,
        "quality_checks": quality_rows,
        "packaging_records": packaging_rows,
        "waste_summary": waste_rows,
        "package": package_payload,
        "packages": [package_payload] if package_payload else [],
        "package_items": package_items,
        "package_scan_history": package_scan_history,
        "warehouse_location": warehouse_location,
        "shipment": primary_shipment,
        "shipments": shipment_payloads,
        "shipment_packages": shipment_package_rows,
        "shipment_package_scan_logs": shipment_scan_rows,
        "delivery_status": {
            "status": primary_shipment.get("status") if primary_shipment else None,
            "shipped_at": primary_shipment.get("shipped_at") if primary_shipment else None,
            "delivered_at": primary_shipment.get("delivered_at") if primary_shipment else None,
        } if primary_shipment else None,
        "audit_summary": _audit_summary(db, entity_refs),
        "gaps": seen_gaps,
        "trace_gap": bool(seen_gaps),
    }


def package_traceability(db: Session, package: Package) -> dict:
    return build_traceability(db, subject_type="package", production_order=None, package=package)


def bundle_traceability(db: Session, bundle: Bundle) -> dict:
    return build_traceability(db, subject_type="bundle", production_order=None, bundle=bundle)


def production_order_traceability(db: Session, po: ProductionOrder) -> dict:
    data = build_traceability(db, subject_type="production_order", production_order=po)
    packages = (
        db.query(Package)
        .filter(Package.production_order_id == po.id)
        .order_by(Package.id.asc())
        .all()
    )
    data["packages"] = [_package_payload(db, pkg) for pkg in packages]
    if not packages:
        data["gaps"].append("Production order has no packages")
        data["trace_gap"] = True
    return data


def _sum_rows(rows: list[dict], key: str) -> float:
    return sum(float(row.get(key) or 0) for row in rows)


def _event_bounds(values: list[Any]) -> tuple[str | None, str | None]:
    cleaned = sorted(str(value) for value in values if value)
    return (cleaned[0], cleaned[-1]) if cleaned else (None, None)


def _batch_packages(db: Session, batch_id: int, production_order_id: int) -> tuple[list[Package], dict[int, int]]:
    allocation_rows = (
        db.query(PackageBatchAllocation, Package)
        .join(Package, Package.id == PackageBatchAllocation.package_id)
        .filter(
            PackageBatchAllocation.production_batch_id == batch_id,
            Package.production_order_id == production_order_id,
        )
        .all()
    )
    packages_by_id: dict[int, Package] = {}
    quantities: dict[int, int] = {}
    for allocation, package in allocation_rows:
        packages_by_id[int(package.id)] = package
        quantities[int(package.id)] = quantities.get(int(package.id), 0) + int(allocation.quantity or 0)

    direct_packages = (
        db.query(Package)
        .filter(
            Package.production_order_id == production_order_id,
            Package.production_batch_id == batch_id,
        )
        .all()
    )
    for package in direct_packages:
        packages_by_id[int(package.id)] = package
        quantities.setdefault(int(package.id), int(package.total_quantity or 0))
    return sorted(packages_by_id.values(), key=lambda row: int(row.id)), quantities


def _batch_material_usage(db: Session, data: dict) -> list[dict]:
    origin_cache = {int(row["id"]): row for row in data.get("material_batches") or [] if row.get("id")}
    grouped: dict[tuple[str, int | None, str], dict] = {}

    def origin(stock_batch_id: int | None) -> dict:
        if not stock_batch_id:
            return {}
        if stock_batch_id not in origin_cache:
            stock_batch = db.get(StockBatch, stock_batch_id)
            item = stock_batch.item if stock_batch and stock_batch.item else None
            origin_cache[stock_batch_id] = {
                "batch_no": stock_batch.batch_no if stock_batch else None,
                "item_id": int(stock_batch.item_id) if stock_batch else None,
                "item_sku": item.sku if item else None,
                "item_name": item.name if item else None,
                "color": stock_batch.color if stock_batch else None,
            }
        return origin_cache[stock_batch_id]

    def add_usage(*, usage_type: str, stock_batch_id: int | None, quantity: float, unit: str) -> None:
        source = origin(stock_batch_id)
        key = (usage_type, stock_batch_id, unit)
        row = grouped.setdefault(
            key,
            {
                "usage_type": usage_type,
                "stock_batch_id": stock_batch_id,
                "batch_no": source.get("batch_no"),
                "item_id": source.get("item_id"),
                "item_sku": source.get("item_sku"),
                "item_name": source.get("item_name") or ("Beyka" if usage_type == "beika" else "Main fabric"),
                "color": source.get("color"),
                "used_quantity": 0.0,
                "unit": unit,
                "scope": "production_batch",
            },
        )
        row["used_quantity"] += quantity

    for record in data.get("cutting_records") or []:
        material_rows = record.get("materials") or []
        if material_rows:
            for usage in material_rows:
                add_usage(
                    usage_type="fabric",
                    stock_batch_id=int(usage["stock_batch_id"]) if usage.get("stock_batch_id") else None,
                    quantity=float(usage.get("quantity") or 0),
                    unit=str(usage.get("unit") or "kg"),
                )
        else:
            add_usage(
                usage_type="fabric",
                stock_batch_id=int(record["fabric_batch_id"]) if record.get("fabric_batch_id") else None,
                quantity=float(record.get("input_quantity") or 0),
                unit=str(record.get("input_unit") or "kg"),
            )

        beika_rows = record.get("beika_materials") or []
        if beika_rows:
            for usage in beika_rows:
                add_usage(
                    usage_type="beika",
                    stock_batch_id=int(usage["stock_batch_id"]) if usage.get("stock_batch_id") else None,
                    quantity=float(usage.get("quantity") or 0),
                    unit=str(usage.get("unit") or "kg"),
                )
        elif float(record.get("beika_kg") or 0) > 0:
            add_usage(
                usage_type="beika",
                stock_batch_id=None,
                quantity=float(record.get("beika_kg") or 0),
                unit="kg",
            )
    return list(grouped.values())


def production_batch_traceability(db: Session, batch: ProductionBatch) -> dict:
    po = db.get(ProductionOrder, batch.production_order_id)
    if not po:
        raise ValueError("Production order not found for batch")
    data = build_traceability(
        db,
        subject_type="production_batch",
        production_order=po,
        production_batch_id=int(batch.id),
    )
    packages, batch_quantity_by_package = _batch_packages(db, int(batch.id), int(po.id))
    package_payloads = []
    for package in packages:
        payload = _package_payload(db, package)
        payload["batch_quantity"] = int(batch_quantity_by_package.get(int(package.id), 0))
        package_payloads.append(payload)

    package_ids = [int(package.id) for package in packages]
    shipment_rows = (
        db.query(Shipment)
        .join(ShipmentPackage, ShipmentPackage.shipment_id == Shipment.id)
        .filter(ShipmentPackage.package_id.in_(package_ids))
        .order_by(Shipment.created_at.asc(), Shipment.id.asc())
        .all()
        if package_ids
        else []
    )
    shipment_ids = [int(row.id) for row in shipment_rows]
    shipment_payloads = [_shipment_payload(db, row) for row in shipment_rows]
    shipment_payloads = [row for row in shipment_payloads if row]

    package_scans = []
    for package in packages:
        for scan in _package_scans(package):
            package_scans.append({**scan, "package_id": int(package.id), "package_no": package.package_no})
    package_scans.sort(key=lambda row: (str(row.get("scanned_at") or ""), int(row.get("id") or 0)))

    cutting = data.get("cutting_records") or []
    printing = data.get("printing_records") or []
    sewing = data.get("sewing_records") or []
    packaging = data.get("packaging_records") or []
    planned = int(batch.planned_quantity or 0)
    quantities = {
        "planned": planned,
        "cut_created": int(_sum_rows(cutting, "cut_pieces")),
        "cut_usable": int(_sum_rows(cutting, "passed_pieces")),
        "cut_defective": int(_sum_rows(cutting, "defective_pieces")),
        "sewn": int(_sum_rows(sewing, "sewn_qty")),
        "sewing_passed": int(_sum_rows(sewing, "passed_qty")),
        "sewing_failed": int(_sum_rows(sewing, "failed_qty")),
        "packed": int(_sum_rows(packaging, "packed_qty")),
        "packaged": sum(batch_quantity_by_package.values()),
        "warehouse_received": sum(
            batch_quantity_by_package.get(int(package.id), 0)
            for package in packages
            if str(package.status or "") in {"received_in_storage", "reserved", "shipped", "delivered"}
        ),
        "shipped": sum(
            batch_quantity_by_package.get(int(package.id), 0)
            for package in packages
            if str(package.status or "") in {"shipped", "delivered"}
        ),
    }

    work_orders = _work_orders_for_po(db, int(po.id))
    available_operations = {str(row.operation) for row in work_orders}
    route = ["cutting"]
    if "printing" in available_operations:
        route.append("printing")
    route.extend(["sewing", "packaging", "storage_transfer", "shipment"])
    stage_values = {
        "cutting": (quantities["cut_usable"], quantities["cut_defective"], cutting, "passed_pieces"),
        "printing": (int(_sum_rows(printing, "passed_qty")), int(_sum_rows(printing, "rejected_qty")), printing, "passed_qty"),
        "sewing": (quantities["sewing_passed"], quantities["sewing_failed"], sewing, "passed_qty"),
        "packaging": (max(quantities["packed"], quantities["packaged"]), int(_sum_rows(packaging, "damaged_qty")), packaging, "packed_qty"),
        "storage_transfer": (quantities["warehouse_received"], 0, package_payloads, "batch_quantity"),
        "shipment": (quantities["shipped"], 0, shipment_payloads, "id"),
    }
    printing_scan_times = []
    sewing_scan_times = []
    for bundle_payload in data.get("bundles") or []:
        for scan in bundle_payload.get("scan_logs") or []:
            scan_type = str(scan.get("scan_type") or "")
            if scan_type in {"sent_printing", "received_printing"}:
                printing_scan_times.append(scan.get("scanned_at"))
            if scan_type in {"sent_sewing", "received_sewing"}:
                sewing_scan_times.append(scan.get("scanned_at"))
    stage_times: dict[str, list[Any]] = {
        "cutting": [row.get("created_at") for row in cutting],
        "printing": [row.get("created_at") for row in printing] + printing_scan_times,
        "sewing": [row.get("created_at") for row in sewing] + sewing_scan_times,
        "packaging": [row.get("created_at") for row in packaging],
        "storage_transfer": [row.get("received_at") for row in package_payloads if row.get("received_at")],
        "shipment": [row.get("shipped_at") for row in shipment_payloads if row.get("shipped_at")],
    }
    stages = []
    for operation in route:
        completed, failed, _activity_rows, _ = stage_values[operation]
        started_at, last_event_at = _event_bounds(stage_times[operation])
        has_activity = bool(started_at) or completed > 0 or failed > 0
        if planned > 0 and completed >= planned:
            status = "completed"
        elif has_activity:
            status = "in_progress"
        else:
            status = "waiting"
        stages.append(
            {
                "operation": operation,
                "status": status,
                "planned": planned,
                "completed": int(completed),
                "failed": int(failed),
                "progress_pct": round(min(100.0, 100.0 * completed / planned), 1) if planned > 0 else 0.0,
                "started_at": started_at,
                "last_event_at": last_event_at,
                "completed_at": last_event_at if status == "completed" else None,
            }
        )

    active_stage = None
    started_indexes = [index for index, row in enumerate(stages) if row["status"] in {"in_progress", "completed"}]
    if started_indexes:
        index = max(started_indexes)
        active_stage = stages[index]
        if active_stage["status"] == "completed" and index + 1 < len(stages):
            active_stage = stages[index + 1]
    elif stages:
        active_stage = stages[0]
    current_process = {
        "operation": active_stage["operation"] if active_stage else "completed",
        "status": active_stage["status"] if active_stage else "completed",
        "as_of": data["generated_at"],
    }

    accessory_rows = []
    for row in accessory_issue_summary(db, production_order_id=int(po.id)):
        issued = float(row.get("issued_quantity") or 0)
        returned = float(row.get("returned_quantity") or 0)
        accessory_rows.append(
            {
                "item_id": row.get("item_id"),
                "item_sku": row.get("item_sku"),
                "item_name": row.get("item_name"),
                "issued_quantity": issued,
                "returned_quantity": returned,
                "used_quantity": max(0.0, issued - returned),
                "unit": row.get("unit"),
                "first_issued_at": _dt(row.get("first_issued_at")),
                "last_issued_at": _dt(row.get("last_issued_at")),
                "scope": "production_order",
            }
        )

    integrity_gaps: list[str] = []
    if cutting and any(not row.get("fabric_batch_id") for row in cutting):
        integrity_gaps.append("A cutting record has no fabric batch link")
    if quantities["cut_usable"] > 0 and not data.get("bundles"):
        integrity_gaps.append("Cut output has no batch-linked bundles")
    if quantities["packed"] > 0 and not packages:
        integrity_gaps.append("Packaging output has no batch allocation")

    data.update(
        {
            "subject_id": int(batch.id),
            "production_batch": {
                "id": int(batch.id),
                "batch_no": batch.batch_no,
                "batch_index": int(batch.batch_index or 0),
                "name": batch.name,
                "planned_quantity": planned,
                "start_date": _dt(batch.start_date),
                "deadline": _dt(batch.deadline),
                "notes": batch.notes,
            },
            "current_process": current_process,
            "quantity_summary": quantities,
            "stage_summary": stages,
            "material_usage": _batch_material_usage(db, data),
            "accessory_usage": accessory_rows,
            "accessory_scope": "production_order",
            "packages": package_payloads,
            "package": None,
            "package_scan_history": package_scans,
            "shipments": shipment_payloads,
            "shipment": shipment_payloads[-1] if shipment_payloads else None,
            "shipment_packages": [
                row for row in _shipment_packages(db, shipment_ids) if int(row.get("package_id") or 0) in package_ids
            ],
            "shipment_package_scan_logs": [
                row for row in _shipment_scan_logs(db, shipment_ids) if int(row.get("package_id") or 0) in package_ids
            ],
            "gaps": integrity_gaps,
            "trace_gap": bool(integrity_gaps),
        }
    )
    return data


def shipment_traceability(db: Session, shipment: Shipment) -> dict:
    packages = (
        db.query(Package)
        .join(ShipmentPackage, ShipmentPackage.package_id == Package.id)
        .filter(ShipmentPackage.shipment_id == shipment.id)
        .options(selectinload(Package.items), selectinload(Package.scan_logs), selectinload(Package.batch_allocations))
        .order_by(Package.id.asc())
        .all()
    )
    po = db.get(ProductionOrder, packages[0].production_order_id) if packages else None
    data = build_traceability(db, subject_type="shipment", production_order=po, package=packages[0] if packages else None, shipment=shipment)
    data["package"] = None
    data["package_items"] = []
    data["package_scan_history"] = []
    data["packages"] = [_package_payload(db, pkg) for pkg in packages]
    data["shipment"] = _shipment_payload(db, shipment)
    data["shipments"] = [data["shipment"]] if data["shipment"] else []
    data["shipment_packages"] = _shipment_packages(db, [int(shipment.id)])
    data["shipment_package_scan_logs"] = _shipment_scan_logs(db, [int(shipment.id)])
    data["delivery_status"] = {
        "status": shipment.status,
        "shipped_at": _dt(shipment.shipped_at),
        "delivered_at": _dt(shipment.delivered_at),
    }
    if not packages:
        data["gaps"].append("Shipment has no packages")
    if not shipment.delivered_at:
        data["gaps"].append("Shipment has no delivery timestamp")
    data["gaps"] = list(dict.fromkeys(data["gaps"]))
    data["trace_gap"] = bool(data["gaps"])
    return data


def _row(label: str, value: Any) -> str:
    return f"<div class='row'><b>{_h(label)}</b><span>{_h(value) if value not in (None, '') else '-'}</span></div>"


def passport_html(data: dict, *, title: str = "Product Passport") -> str:
    company = data.get("company") or {}
    package = data.get("package") or {}
    po = data.get("production_order") or {}
    so = data.get("sales_order") or {}
    customer = data.get("customer") or {}
    model = data.get("model") or {}
    brand = data.get("brand") or {}
    collection = data.get("collection") or {}
    shipment = data.get("shipment") or {}
    warehouse = data.get("warehouse_location") or {}

    def table(headers: list[str], rows: list[list[Any]]) -> str:
        if not rows:
            return "<p class='empty'>No records.</p>"
        head = "".join(f"<th>{_h(h)}</th>" for h in headers)
        body = "".join("<tr>" + "".join(f"<td>{_h(cell)}</td>" for cell in row) + "</tr>" for row in rows)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    qty_rows = [[r.get("color"), r.get("size"), r.get("quantity")] for r in data.get("color_size_quantities") or []]
    material_rows = [[r.get("batch_no"), r.get("item_sku"), r.get("item_name"), r.get("color"), r.get("quantity"), r.get("unit"), r.get("qc_status")] for r in data.get("material_batches") or []]
    timeline_rows: list[list[Any]] = []
    for row in data.get("cutting_records") or []:
        timeline_rows.append(["Cutting", row.get("created_at"), f"{row.get('passed_pieces', 0)} passed / {row.get('defective_pieces', 0)} defective", row.get("fabric_batch_id")])
    for row in data.get("printing_records") or []:
        timeline_rows.append(["Printing", row.get("created_at"), f"{row.get('passed_qty', 0)} passed / {row.get('rejected_qty', 0)} rejected", row.get("print_type")])
    for row in data.get("sewing_records") or []:
        timeline_rows.append(["Sewing", row.get("created_at"), f"{row.get('passed_qty', 0)} passed / {row.get('failed_qty', 0)} failed", row.get("line_name")])
    for row in data.get("packaging_records") or []:
        timeline_rows.append(["Packaging", row.get("created_at"), f"{row.get('packed_qty', 0)} packed / {row.get('damaged_qty', 0)} damaged", row.get("packaging_material_used")])
    for row in data.get("package_scan_history") or []:
        timeline_rows.append(["Package scan", row.get("scanned_at"), row.get("scan_type"), row.get("location")])
    for row in data.get("shipment_package_scan_logs") or []:
        timeline_rows.append(["Shipment scan", row.get("scanned_at"), row.get("scan_result"), row.get("message")])

    quality_rows = [[r.get("checked_at"), r.get("checked_qty"), r.get("passed_qty"), r.get("failed_qty"), r.get("defect_type"), r.get("severity")] for r in data.get("quality_checks") or []]
    waste_rows = [[r.get("waste_type"), r.get("quantity"), r.get("unit")] for r in data.get("waste_summary") or []]
    gap_items = "".join(f"<li>{_h(gap)}</li>" for gap in data.get("gaps") or [])
    if not gap_items:
        gap_items = "<li>No traceability gaps detected from available records.</li>"

    package_rows = [[p.get("package_no"), p.get("barcode"), p.get("total_quantity"), p.get("status"), p.get("storage_location")] for p in data.get("packages") or []]

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{_h(title)}</title>
  <style>
    @page {{ margin: 10mm; }}
    body {{ font-family: Arial, sans-serif; margin: 0; padding: 10mm; color: #111; }}
    h1 {{ font-size: 20pt; margin: 0 0 2mm; }}
    h2 {{ font-size: 12pt; margin: 7mm 0 2mm; border-bottom: 1px solid #111; padding-bottom: 1mm; }}
    .meta {{ font-size: 9pt; color: #444; margin-bottom: 6mm; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 4mm; }}
    .box {{ border: 1px solid #111; padding: 4mm; break-inside: avoid; }}
    .row {{ display: flex; justify-content: space-between; gap: 4mm; font-size: 9.5pt; margin: 1mm 0; }}
    .row b {{ color: #333; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 8.5pt; }}
    th, td {{ border: 1px solid #888; padding: 1.5mm; text-align: left; vertical-align: top; }}
    th {{ background: #eee; }}
    .empty {{ font-size: 9pt; color: #555; }}
    ul {{ margin: 0; padding-left: 5mm; font-size: 9pt; }}
    button {{ margin-top: 6mm; }}
    @media print {{ button {{ display: none; }} body {{ padding: 0; }} }}
  </style>
</head>
<body>
  <h1>{_h(title)}</h1>
  <div class="meta">{_h(company.get("name"))} · Generated {_h(data.get("generated_at"))}</div>
  <div class="grid">
    <div class="box">
      <h2>Product identity</h2>
      {_row("Package", package.get("package_no"))}
      {_row("Barcode", package.get("barcode"))}
      {_row("Production order", po.get("production_no") or po.get("order_no"))}
      {_row("Sales order", so.get("order_no"))}
      {_row("Customer", customer.get("name"))}
      {_row("Brand", brand.get("name"))}
      {_row("Collection", collection.get("name"))}
      {_row("Model", f"{model.get('code') or ''} {model.get('name') or ''}".strip())}
    </div>
    <div class="box">
      <h2>Warehouse / shipment</h2>
      {_row("Warehouse", warehouse.get("warehouse_name"))}
      {_row("Location", warehouse.get("location"))}
      {_row("Shipment", shipment.get("shipment_no"))}
      {_row("Shipment status", shipment.get("status"))}
      {_row("Shipped at", shipment.get("shipped_at"))}
      {_row("Delivered at", shipment.get("delivered_at"))}
    </div>
  </div>
  <h2>Color / size quantities</h2>
  {table(["Color", "Size", "Quantity"], qty_rows)}
  <h2>Packages</h2>
  {table(["Package", "Barcode", "Qty", "Status", "Location"], package_rows)}
  <h2>Material origin / batch</h2>
  {table(["Batch", "SKU", "Item", "Color", "Qty", "Unit", "QC"], material_rows)}
  <h2>Production route timeline</h2>
  {table(["Stage", "When", "Quantity / result", "Reference"], timeline_rows)}
  <h2>Quality summary</h2>
  {table(["Checked at", "Checked", "Passed", "Failed", "Defect", "Severity"], quality_rows)}
  <h2>Waste summary</h2>
  {table(["Type", "Quantity", "Unit"], waste_rows)}
  <h2>Traceability gaps</h2>
  <ul>{gap_items}</ul>
  <button onclick="window.print()">Print</button>
</body>
</html>"""
