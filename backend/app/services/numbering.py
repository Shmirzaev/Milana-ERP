"""Sequential business number generators."""
from datetime import datetime, timezone

from sqlalchemy import Integer, func, text
from sqlalchemy.orm import Session

from app.models import (
    SalesOrder, BrandedPlanningOrder, ProductionOrder, Bundle, Package, Shipment, Invoice, Model,
    PurchaseRequest, PurchaseOrder, MaterialReservation, SystemSetting,
)

MODEL_VARIANT_START = 5648
MODEL_VARIANT_SETTING_KEY = "model_variant_numbering"
_NUMBERING_LOCK_NAMESPACE = 1_297_047_632


def _is_postgresql(db: Session) -> bool:
    return bool(db.bind and db.bind.dialect.name == "postgresql")


def _acquire_numbering_lock(db: Session, resource: str) -> None:
    """Serialize one number stream without blocking unrelated table writes."""
    if not _is_postgresql(db):
        return
    db.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, hashtext(:resource))"),
        {"namespace": _NUMBERING_LOCK_NAMESPACE, "resource": resource},
    )


def _model_variant_number_is_occupied(db: Session, variant_no: str) -> bool:
    """Check one candidate from the narrow code column, never the large model JSON."""
    return (
        db.query(Model.id)
        .filter(Model.code.ilike(f"%{variant_no.strip()}"))
        .first()
        is not None
    )


def _next(db: Session, model, attr: str, prefix: str, *, width: int = 6) -> str:
    year = datetime.now(timezone.utc).year
    column = getattr(model, attr)
    _acquire_numbering_lock(db, f"{model.__tablename__}:{attr}:{prefix}:{year}")
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


def next_usluga_order_no(db: Session) -> str:
    """Return a visibly separate number for Eco Cotton outside-service work."""
    return _next(db, ProductionOrder, "production_no", "USL")


def next_branded_planning_order_no(db: Session) -> str:
    _acquire_numbering_lock(db, f"{BrandedPlanningOrder.__tablename__}:order_no")
    if _is_postgresql(db):
        highest = int(
            db.query(func.max(BrandedPlanningOrder.order_no.cast(Integer)))
            .filter(BrandedPlanningOrder.order_no.op("~")(r"^[0-9]+$"))
            .scalar()
            or 0
        )
    else:
        values = db.query(BrandedPlanningOrder.order_no).all()
        highest = 0
        for (value,) in values:
            raw = str(value or "").strip()
            if raw.isdigit():
                highest = max(highest, int(raw))
    return f"{highest + 1:04d}"


def next_model_variant_no(db: Session, *, reserve: bool = False) -> str:
    """Return or reserve the next automatic V-number, starting at V-5648."""
    if reserve:
        _acquire_numbering_lock(db, MODEL_VARIANT_SETTING_KEY)

    setting_query = db.query(SystemSetting).filter(SystemSetting.key == MODEL_VARIANT_SETTING_KEY)
    if reserve and _is_postgresql(db):
        setting_query = setting_query.with_for_update()
    setting = setting_query.one_or_none()
    setting_value = setting.value_json if setting and isinstance(setting.value_json, dict) else {}
    try:
        last_assigned = int(setting_value.get("last_assigned") or MODEL_VARIANT_START - 1)
    except (TypeError, ValueError):
        last_assigned = MODEL_VARIANT_START - 1

    candidate = max(MODEL_VARIANT_START, last_assigned + 1)
    while _model_variant_number_is_occupied(db, f"V-{candidate}"):
        candidate += 1

    if reserve:
        next_value = {"last_assigned": candidate}
        if setting:
            setting.value_json = next_value
        else:
            db.add(SystemSetting(key=MODEL_VARIANT_SETTING_KEY, value_json=next_value))
        db.flush()
    return f"V-{candidate}"


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
