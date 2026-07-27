"""Sequential business number generators."""
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import (
    SalesOrder, BrandedPlanningOrder, ProductionOrder, Bundle, Package, Shipment, Invoice,
    PurchaseRequest, PurchaseOrder, MaterialReservation,
)


def _next(db: Session, model, attr: str, prefix: str, *, width: int = 6) -> str:
    year = datetime.now(timezone.utc).year
    column = getattr(model, attr)
    if db.bind and db.bind.dialect.name == "postgresql":
        db.execute(text(f"LOCK TABLE {model.__tablename__} IN EXCLUSIVE MODE"))
    pattern = f"{prefix}-{year}-%"
    last = db.query(column).filter(column.like(pattern)).order_by(column.desc()).first()
    next_num = 1
    if last and last[0]:
        raw = str(last[0])
        try:
            next_num = int(raw.rsplit("-", 1)[-1]) + 1
        except Exception:
            next_num = 1
    return f"{prefix}-{year}-{next_num:0{width}d}"


def next_sales_order_no(db: Session) -> str:
    return _next(db, SalesOrder, "order_no", "SO")


def next_production_order_no(db: Session) -> str:
    return _next(db, ProductionOrder, "production_no", "PO")


def next_branded_planning_order_no(db: Session) -> str:
    if db.bind and db.bind.dialect.name == "postgresql":
        db.execute(text(f"LOCK TABLE {BrandedPlanningOrder.__tablename__} IN EXCLUSIVE MODE"))
    values = db.query(BrandedPlanningOrder.order_no).all()
    highest = 0
    for (value,) in values:
        raw = str(value or "").strip()
        if raw.isdigit():
            highest = max(highest, int(raw))
    return f"{highest + 1:04d}"


def next_bundle_no(db: Session) -> str:
    return _next(db, Bundle, "bundle_no", "BND")


def next_package_no(db: Session) -> str:
    return _next(db, Package, "package_no", "PKG")


def next_shipment_no(db: Session) -> str:
    return _next(db, Shipment, "shipment_no", "SH")


def next_invoice_no(db: Session) -> str:
    return _next(db, Invoice, "invoice_no", "INV")


def next_purchase_request_no(db: Session) -> str:
    return _next(db, PurchaseRequest, "request_no", "PR")


def next_purchase_order_no(db: Session) -> str:
    return _next(db, PurchaseOrder, "po_no", "PUR")


def next_material_reservation_no(db: Session) -> str:
    return _next(db, MaterialReservation, "reservation_no", "MR")
