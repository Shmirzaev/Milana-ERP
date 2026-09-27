"""Sequential business number generators."""
from datetime import datetime, timezone
import re

from fastapi import HTTPException
from sqlalchemy import Integer, Numeric, func, text
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


def _next_many(
    db: Session,
    model,
    attr: str,
    prefix: str,
    count: int,
    *,
    width: int = 6,
) -> list[str]:
    if count <= 0:
        return []
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
    # Deleted manual-label identities remain retired: old printed QR codes must
    # never resolve to a new physical pack or print run.
    if model.__tablename__ in {"packages", "package_print_runs"}:
        floor = db.query(SystemSetting.value_json).filter_by(key=f"retired_number:{prefix}:{year}").scalar()
        if floor:
            next_num = max(next_num, int(floor.get("number", 0)) + 1)
    return [
        f"{prefix}-{year}-{number:0{width}d}"
        for number in range(next_num, next_num + count)
    ]


def _next(db: Session, model, attr: str, prefix: str, *, width: int = 6) -> str:
    return _next_many(db, model, attr, prefix, 1, width=width)[0]


def _next_order(db: Session, model, attr: str, prefix: str) -> str:
    """Issue a canonical reference with four-digit minimum padding."""
    column = getattr(model, attr)
    _acquire_numbering_lock(db, f"{model.__tablename__}:{attr}:{prefix}:compact")
    # Include all historical years so removing the year does not restart the
    # business sequence or reuse a historical order's numeric part.
    pattern = rf"^{re.escape(prefix)}-([0-9]{{4}}-)?[0-9]+$"
    if _is_postgresql(db):
        suffix = func.substring(column, r"([0-9]+)$").cast(Numeric)
        highest = int(db.query(func.max(suffix)).filter(column.op("~")(pattern)).scalar() or 0)
    else:
        highest = max(
            (int(value.rsplit("-", 1)[-1]) for (value,) in
             db.query(column).filter(column.like(f"{prefix}-%")).all()
             if value and re.fullmatch(pattern, value)),
            default=0,
        )
    from app.models import BusinessOrderAlias
    aliases = db.query(
        BusinessOrderAlias.reference,
        BusinessOrderAlias.canonical_reference,
    ).filter(BusinessOrderAlias.namespace == prefix).all()
    # Canonical references keep a four-digit minimum, while allowing the
    # numeric suffix to grow without truncation after 9999.
    alias_pattern = re.compile(rf"{re.escape(prefix)}-([0-9]{{4,}})")
    for reference, canonical_reference in aliases:
        for value in (reference, canonical_reference):
            match = alias_pattern.fullmatch(str(value or ""))
            if match:
                highest = max(highest, int(match.group(1)))
    return f"{prefix}-{highest + 1:04d}"


def next_sales_order_no(db: Session) -> str:
    return _next_order(db, SalesOrder, "order_no", "SO")


def next_production_order_no(db: Session) -> str:
    return _next_order(db, ProductionOrder, "production_no", "PO")


def next_usluga_order_no(db: Session) -> str:
    """Return a visibly separate number for Eco Cotton outside-service work."""
    return _next_order(db, ProductionOrder, "production_no", "USL")


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
    from app.models import BusinessOrderAlias

    reference = _next_order(db, Bundle, "bundle_no", "BND")
    # Reserve in the caller's transaction, including after a future bundle deletion.
    # Bundle creation attaches its actual ID after flush; zero is reservation-only.
    db.add(BusinessOrderAlias(namespace="BND", entity_id=0, reference=reference, canonical_reference=reference))
    db.flush()
    return reference


def next_package_no(db: Session) -> str:
    return _next(db, Package, "package_no", "PKG")


def next_package_nos(db: Session, count: int) -> list[str]:
    """Reserve a consecutive package-number range in the caller's transaction."""
    return _next_many(db, Package, "package_no", "PKG", count)


def next_shipment_no(db: Session) -> str:
    return _next(db, Shipment, "shipment_no", "SH")


def next_invoice_no(db: Session) -> str:
    return _next(db, Invoice, "invoice_no", "INV")


def next_purchase_request_no(db: Session) -> str:
    return _next_order(db, PurchaseRequest, "request_no", "PR")


def next_purchase_order_no(db: Session) -> str:
    return _next_order(db, PurchaseOrder, "po_no", "PUR")


def next_material_reservation_no(db: Session) -> str:
    return _next(db, MaterialReservation, "reservation_no", "MR")


def next_material_reservation_nos(db: Session, count: int) -> list[str]:
    """Reserve a consecutive material-reservation number range."""
    return _next_many(db, MaterialReservation, "reservation_no", "MR", count)


def retire_label_numbers(db: Session, package_numbers: list[str], run_number: str) -> None:
    from app.models import PackagePrintRun
    for model, attr, prefix, numbers in ((Package, "package_no", "PKG", package_numbers),
                                         (PackagePrintRun, "run_no", "PRN", [run_number])):
        by_year: dict[str, int] = {}
        for number in numbers:
            match = re.fullmatch(rf"{prefix}-(\d{{4}})-(\d+)", number)
            if not match:
                raise HTTPException(409, "Unrecognized manual label number; deletion requires review")
            year, suffix = match.groups()
            by_year[year] = max(by_year.get(year, 0), int(suffix))
        for year, number in sorted(by_year.items()):
            _acquire_numbering_lock(db, f"{model.__tablename__}:{attr}:{prefix}:{year}")
            key = f"retired_number:{prefix}:{year}"
            row = db.query(SystemSetting).filter_by(key=key).populate_existing().first()
            if row:
                row.value_json = {"number": max(number, int(row.value_json.get("number", 0)))}
            else:
                db.add(SystemSetting(key=key, value_json={"number": number}))
    db.flush()
