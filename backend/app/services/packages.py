"""Package service: build packages of finished goods with QR/barcode."""
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    Package, PackageItem, PackageScanLog, ProductionOrder, FinishedGoodsStock,
    Warehouse, ModelBOM, StockBatch, Model,
)
from app.services.barcode import generate_barcode_value, save_qr_image, save_barcode_image
from app.services.numbering import next_package_no


def _compute_cost(db: Session, model_id: int) -> float:
    """Estimate cost-per-piece from BOM × avg batch cost. Used for finished goods valuation."""
    cost = 0.0
    bom = db.query(ModelBOM).filter(ModelBOM.model_id == model_id).all()
    for b in bom:
        avg_cost_row = db.query(StockBatch).filter(StockBatch.item_id == b.item_id).order_by(StockBatch.id.desc()).first()
        unit_cost = float(avg_cost_row.cost_per_unit) if avg_cost_row else 0.0
        cost += float(b.quantity_per_piece) * unit_cost * (1.0 + float(b.waste_percent) / 100.0)
    return round(cost, 4)


def create_package(
    db: Session,
    *,
    production_order_id: int,
    model_id: int,
    color: str,
    items: list[dict],
    sales_order_id: int | None = None,
    brand_id: int | None = None,
    collection_id: int | None = None,
    package_type: str = "bag",
    capacity: int = 60,
    warehouse_id: int | None = None,
    override_capacity: bool = False,
    is_admin: bool = False,
    user_id: int | None = None,
    notes: str | None = None,
) -> Package:
    if not items:
        raise HTTPException(400, "Package must contain at least one size line")

    total = sum(int(it.get("quantity", 0)) for it in items)
    if total <= 0:
        raise HTTPException(400, "Total package quantity must be > 0")
    if total > capacity and not (override_capacity and is_admin):
        raise HTTPException(400, f"Package quantity {total} exceeds capacity {capacity}. Admin override required.")

    # All items must share the same model unless admin override
    distinct_models = {int(it.get("model_id", model_id)) for it in items}
    if len(distinct_models) > 1 and not (override_capacity and is_admin):
        raise HTTPException(400, "Package contains different models — admin override required")
    # All items must share the same color (rule)
    distinct_colors = {it["color"] for it in items}
    if len(distinct_colors) > 1 and not (override_capacity and is_admin):
        raise HTTPException(400, "Package contains different colors — admin override required")

    po = db.get(ProductionOrder, production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")

    pkg_no = next_package_no(db)
    barcode_value = generate_barcode_value("PKG")
    pkg = Package(
        package_no=pkg_no,
        barcode=barcode_value,
        production_order_id=production_order_id,
        sales_order_id=sales_order_id,
        brand_id=brand_id,
        collection_id=collection_id,
        model_id=model_id,
        color=color,
        package_type=package_type,
        total_quantity=total,
        capacity=capacity,
        warehouse_id=warehouse_id,
        status="packed",
        packed_by=user_id,
        packed_at=datetime.now(timezone.utc),
        notes=notes,
    )
    db.add(pkg)
    db.flush()

    for it in items:
        db.add(PackageItem(
            package_id=pkg.id,
            model_id=int(it.get("model_id", model_id)),
            color=it["color"],
            size=it["size"],
            quantity=int(it["quantity"]),
        ))

    qr_payload = f"PACKAGE:{pkg_no}|{barcode_value}"
    pkg.qr_code_url = save_qr_image(qr_payload, f"package_qr_{pkg_no}")
    save_barcode_image(barcode_value, f"package_bc_{pkg_no}")

    db.add(PackageScanLog(
        package_id=pkg.id, scanned_by=user_id, scan_type="packed",
    ))

    # Add to finished goods stock (per size line)
    cost = _compute_cost(db, model_id)
    for it in items:
        db.add(FinishedGoodsStock(
            production_order_id=production_order_id,
            sales_order_id=sales_order_id,
            package_id=pkg.id,
            model_id=int(it.get("model_id", model_id)),
            brand_id=brand_id,
            collection_id=collection_id,
            color=it["color"],
            size=it["size"],
            quantity=int(it["quantity"]),
            available_qty=int(it["quantity"]),
            cost_per_piece=cost,
            warehouse_id=warehouse_id,
            status="available",
        ))

    db.flush()
    return pkg


def receive_at_storage(db: Session, pkg: Package, warehouse_id: int | None, user_id: int | None):
    if pkg.status not in ("packed",):
        raise HTTPException(400, f"Package in status '{pkg.status}' cannot be received at storage")
    pkg.status = "received_in_storage"
    pkg.received_by = user_id
    pkg.received_at = datetime.now(timezone.utc)
    if warehouse_id:
        pkg.warehouse_id = warehouse_id
    db.add(PackageScanLog(package_id=pkg.id, scanned_by=user_id, scan_type="received_storage"))
    db.flush()


def reserve_package(db: Session, pkg: Package, user_id: int | None):
    if pkg.status not in ("received_in_storage", "packed"):
        raise HTTPException(400, f"Package cannot be reserved from status '{pkg.status}'")
    pkg.status = "reserved"
    db.add(PackageScanLog(package_id=pkg.id, scanned_by=user_id, scan_type="reserved"))
    db.flush()


def ship_package(db: Session, pkg: Package, user_id: int | None):
    if pkg.status not in ("received_in_storage", "reserved"):
        raise HTTPException(400, f"Package cannot be shipped from status '{pkg.status}'")
    pkg.status = "shipped"
    pkg.shipped_at = datetime.now(timezone.utc)
    db.add(PackageScanLog(package_id=pkg.id, scanned_by=user_id, scan_type="shipped"))
    db.flush()


def mark_delivered(db: Session, pkg: Package, user_id: int | None):
    if pkg.status != "shipped":
        raise HTTPException(400, f"Package not in 'shipped' status (was '{pkg.status}')")
    pkg.status = "delivered"
    db.add(PackageScanLog(package_id=pkg.id, scanned_by=user_id, scan_type="delivered"))
    db.flush()


def mark_damaged(db: Session, pkg: Package, user_id: int | None):
    pkg.status = "damaged"
    db.add(PackageScanLog(package_id=pkg.id, scanned_by=user_id, scan_type="audit_check", location="damaged"))
    db.flush()
