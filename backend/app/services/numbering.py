"""Sequential business number generators (SO-, PO-, WO-, BND-, PKG-, SH-, INV-)."""
from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    SalesOrder, ProductionOrder, WorkOrder, Bundle, Package, Shipment, Invoice,
)


def _next(db: Session, model, attr: str, prefix: str) -> str:
    year = datetime.utcnow().year
    count = db.query(func.count()).select_from(model).scalar() or 0
    return f"{prefix}-{year}-{(count + 1):06d}"


def next_sales_order_no(db: Session) -> str:
    return _next(db, SalesOrder, "order_no", "SO")


def next_production_order_no(db: Session) -> str:
    return _next(db, ProductionOrder, "production_no", "PO")


def next_bundle_no(db: Session) -> str:
    return _next(db, Bundle, "bundle_no", "BND")


def next_package_no(db: Session) -> str:
    return _next(db, Package, "package_no", "PKG")


def next_shipment_no(db: Session) -> str:
    return _next(db, Shipment, "shipment_no", "SH")


def next_invoice_no(db: Session) -> str:
    return _next(db, Invoice, "invoice_no", "INV")
