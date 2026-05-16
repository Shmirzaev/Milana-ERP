"""Sequential business number generators (SO-, PO-, WO-, BND-, PKG-, SH-, INV-)."""
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import (
    SalesOrder, ProductionOrder, WorkOrder, Bundle, Package, Shipment, Invoice,
)


def _next(db: Session, model, attr: str, prefix: str) -> str:
    year = datetime.utcnow().year
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
    return f"{prefix}-{year}-{next_num:06d}"


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
