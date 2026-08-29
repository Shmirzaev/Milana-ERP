"""Bundle service: create cutting bundles with QR/barcode, manage scan transitions."""
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Bundle, BundleScanLog, CuttingRecord, ProductionOrder, ProductionBatch, Department, SalesOrder, WorkOrder,
)
from app.services.barcode import generate_barcode_value, save_qr_image, save_barcode_image
from app.services.numbering import next_bundle_no
from app.services.workflow import notify_department, sync_production_order_status


DEPT_CUT = "CUT"
DEPT_PRT = "PRT"
DEPT_SEW = "SEW"
DEPT_PKG = "PKG"
DEPT_MILANA = "MIL"
DEPT_BESTTEX = "BST"
DEPT_BESTTEX_PACKAGING = "BPK"
DEPT_ECO_COTTON = "ECO"
DEPT_ECO_COTTON_PACKAGING = "ECP"
DEPT_ECO_COTTON_CUTTING = "ECT"
DEFAULT_SEWING_FACTORY_CODE = DEPT_MILANA
SEWING_FACTORY_CODES = (DEPT_MILANA, DEPT_BESTTEX, DEPT_ECO_COTTON)
SEWING_DEPARTMENT_CODES = (DEPT_SEW, *SEWING_FACTORY_CODES)
SEWING_FACTORY_ALIASES = {
    "MIL": DEPT_MILANA,
    "MILANA": DEPT_MILANA,
    "SML": DEPT_MILANA,
    "BST": DEPT_BESTTEX,
    "BESTTEX": DEPT_BESTTEX,
    "BTX": DEPT_BESTTEX,
    "ECO": DEPT_ECO_COTTON,
    "ECO COTTON": DEPT_ECO_COTTON,
    "ECO_COTTON": DEPT_ECO_COTTON,
    "ECOCOTTON": DEPT_ECO_COTTON,
}


def _dept(db: Session, code: str) -> Department | None:
    return db.query(Department).filter(Department.code == code).first()


def resolve_sewing_factory_code(value: str | None = None) -> str:
    normalized = str(value or "").strip().upper()
    if normalized == DEPT_SEW or not normalized:
        return DEFAULT_SEWING_FACTORY_CODE
    return SEWING_FACTORY_ALIASES.get(normalized, DEFAULT_SEWING_FACTORY_CODE)


def is_sewing_department_code(code: str | None) -> bool:
    normalized = str(code or "").strip().upper()
    return normalized in SEWING_DEPARTMENT_CODES or normalized in SEWING_FACTORY_ALIASES


def _sewing_factory_dept(db: Session, code: str | None) -> Department | None:
    factory_code = resolve_sewing_factory_code(code)
    return _dept(db, factory_code) or _dept(db, DEPT_SEW)


def _factory_codes_for_scope(
    db: Session,
    production_order_id: int,
    production_batch_id: int | None = None,
) -> set[str]:
    qry = db.query(Bundle.sewing_factory_code).filter(Bundle.production_order_id == production_order_id)
    if production_batch_id is not None:
        qry = qry.filter(Bundle.production_batch_id == production_batch_id)
    return {
        resolve_sewing_factory_code(code)
        for (code,) in qry.all()
        if code is not None
    }


def sewing_department_code_for_bundle_route(
    db: Session,
    production_order_id: int,
    production_batch_id: int | None = None,
) -> str:
    codes = _factory_codes_for_scope(db, production_order_id, production_batch_id)
    if codes == {DEPT_MILANA}:
        return DEPT_MILANA
    if codes == {DEPT_BESTTEX}:
        return DEPT_BESTTEX
    if codes == {DEPT_ECO_COTTON}:
        return DEPT_ECO_COTTON
    return DEPT_SEW


def packaging_department_code_for_bundle_route(
    db: Session,
    production_order_id: int,
    production_batch_id: int | None = None,
) -> str:
    codes = _factory_codes_for_scope(db, production_order_id, production_batch_id)
    if codes == {DEPT_BESTTEX}:
        return DEPT_BESTTEX_PACKAGING
    if codes == {DEPT_ECO_COTTON}:
        return DEPT_ECO_COTTON_PACKAGING
    return DEPT_PKG


def _work_orders_for_route(
    db: Session,
    production_order_id: int,
    production_batch_id: int | None,
    operation: str,
) -> list[WorkOrder]:
    base = db.query(WorkOrder).filter(
        WorkOrder.production_order_id == production_order_id,
        WorkOrder.operation == operation,
    )
    if production_batch_id is not None:
        rows = base.filter(WorkOrder.production_batch_id == production_batch_id).all()
        if rows:
            return rows
    rows = base.filter(WorkOrder.production_batch_id.is_(None)).all()
    return rows or base.all()


def _assign_work_order_department(
    db: Session,
    production_order_id: int,
    production_batch_id: int | None,
    operation: str,
    department_code: str,
    fallback_code: str,
) -> str:
    target = _dept(db, department_code) or _dept(db, fallback_code)
    if not target:
        return fallback_code
    for wo in _work_orders_for_route(db, production_order_id, production_batch_id, operation):
        if wo.department_id != target.id:
            wo.department_id = target.id
    return target.code


def sync_sewing_department_for_bundle_route(
    db: Session,
    production_order_id: int,
    production_batch_id: int | None = None,
) -> str:
    return _assign_work_order_department(
        db,
        production_order_id,
        production_batch_id,
        "sewing",
        sewing_department_code_for_bundle_route(db, production_order_id, production_batch_id),
        DEPT_SEW,
    )


def sync_packaging_department_for_bundle_route(
    db: Session,
    production_order_id: int,
    production_batch_id: int | None = None,
) -> str:
    return _assign_work_order_department(
        db,
        production_order_id,
        production_batch_id,
        "packaging",
        packaging_department_code_for_bundle_route(db, production_order_id, production_batch_id),
        DEPT_PKG,
    )


def sync_textile_departments_for_bundle_route(
    db: Session,
    production_order_id: int,
    production_batch_id: int | None = None,
) -> tuple[str, str]:
    sewing_code = sync_sewing_department_for_bundle_route(db, production_order_id, production_batch_id)
    packaging_code = sync_packaging_department_for_bundle_route(db, production_order_id, production_batch_id)
    return sewing_code, packaging_code


def format_batch_passport(batch: ProductionBatch | None, production_order_id: int | None = None) -> str:
    if not batch:
        return ""
    batch_no = str(batch.batch_no or "").strip()
    if batch_no:
        return batch_no[3:] if batch_no.upper().startswith("BT-") else batch_no
    idx = max(1, int(batch.batch_index or 1))
    po_id = max(0, int(production_order_id or batch.production_order_id or 0))
    if po_id:
        return f"{po_id:04d}-{idx:02d}"
    return f"{idx:02d}"


def bundle_qr_payload(db: Session, bundle: Bundle) -> str:
    parts = [f"BUNDLE:{bundle.bundle_no}", str(bundle.barcode or "")]
    po = db.get(ProductionOrder, bundle.production_order_id)
    if po and po.production_no:
        parts.append(f"PO:{po.production_no}")
    if bundle.production_batch_id:
        batch = db.get(ProductionBatch, bundle.production_batch_id)
        if batch:
            passport = format_batch_passport(batch, bundle.production_order_id)
            parts.append(f"BATCH:{passport}")
            parts.append(f"BATCH_ID:{batch.id}")
    return "|".join(part for part in parts if part)


def _work_order_for_bundle(db: Session, bundle: Bundle, operation: str) -> WorkOrder | None:
    base = db.query(WorkOrder).filter(
        WorkOrder.production_order_id == bundle.production_order_id,
        WorkOrder.operation == operation,
    )
    if bundle.production_batch_id is not None:
        batch_wo = base.filter(WorkOrder.production_batch_id == bundle.production_batch_id).first()
        if batch_wo:
            return batch_wo
    generic_wo = base.filter(WorkOrder.production_batch_id.is_(None)).first()
    return generic_wo or base.first()


def create_bundle(
    db: Session,
    *,
    production_order_id: int,
    production_batch_id: int | None = None,
    cutting_record_id: int | None = None,
    model_id: int,
    color: str,
    size: str,
    quantity: int,
    sales_order_id: int | None = None,
    brand_id: int | None = None,
    collection_id: int | None = None,
    next_department_code: str = DEPT_SEW,
    sewing_factory_code: str | None = None,
    user_id: int | None = None,
    notes: str | None = None,
) -> Bundle:
    if quantity <= 0:
        raise HTTPException(400, "Bundle quantity must be > 0")
    po = db.get(ProductionOrder, production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")
    if sales_order_id:
        if not db.get(SalesOrder, sales_order_id):
            raise HTTPException(404, "Sales order not found")
    batch_id = int(production_batch_id) if production_batch_id else None
    if batch_id is not None:
        batch = db.get(ProductionBatch, batch_id)
        if not batch or int(batch.production_order_id) != int(production_order_id):
            raise HTTPException(400, "Production batch does not belong to this production order")

    cut = _dept(db, DEPT_CUT)
    factory_code = resolve_sewing_factory_code(
        sewing_factory_code if sewing_factory_code else next_department_code if is_sewing_department_code(next_department_code) else None
    )
    normalized_next = str(next_department_code or "").strip().upper()
    if is_sewing_department_code(normalized_next):
        normalized_next = factory_code
    nxt = _dept(db, normalized_next)

    bundle_no = next_bundle_no(db)
    barcode_value = generate_barcode_value("BND")
    b = Bundle(
        bundle_no=bundle_no,
        barcode=barcode_value,
        production_order_id=production_order_id,
        production_batch_id=batch_id,
        cutting_record_id=cutting_record_id,
        sales_order_id=sales_order_id,
        brand_id=brand_id,
        collection_id=collection_id,
        model_id=model_id,
        color=color,
        size=size,
        quantity=quantity,
        current_department_id=cut.id if cut else None,
        next_department_id=nxt.id if nxt else None,
        sewing_factory_code=factory_code,
        status="created",
        created_by=user_id,
        notes=notes,
    )
    db.add(b)
    db.flush()

    b.qr_code_url = save_qr_image(bundle_qr_payload(db, b), f"bundle_qr_{bundle_no}")
    # also persist a barcode image for printing labels
    save_barcode_image(barcode_value, f"bundle_bc_{bundle_no}")

    db.add(BundleScanLog(
        bundle_id=b.id, scanned_by=user_id, scan_type="created",
        from_department_id=None, to_department_id=cut.id if cut else None,
    ))
    db.flush()
    return b


def _require_cutting_batch_approved(db: Session, bundle: Bundle) -> None:
    if not bundle.cutting_record_id:
        return
    record = db.get(CuttingRecord, int(bundle.cutting_record_id))
    if not record:
        raise HTTPException(409, "The source cutting batch is unavailable")
    if record.approval_status != "approved":
        raise HTTPException(409, "This cutting batch must be approved before its bundles can move")


def _transition(
    db: Session, bundle: Bundle, scan_type: str, new_status: str,
    from_code: str | None, to_code: str | None, user_id: int | None,
):
    f = _dept(db, from_code) if from_code else None
    t = _dept(db, to_code) if to_code else None
    bundle.status = new_status
    if t:
        bundle.current_department_id = t.id
    db.add(BundleScanLog(
        bundle_id=bundle.id, scanned_by=user_id, scan_type=scan_type,
        from_department_id=f.id if f else None, to_department_id=t.id if t else None,
    ))
    db.flush()


def send_to_printing(db: Session, bundle: Bundle, user_id: int | None = None):
    _require_cutting_batch_approved(db, bundle)
    if bundle.status == "sent_to_printing":
        raise HTTPException(409, "This bundle sticker was already sent to printing")
    if bundle.status in ("received_printing", "sent_to_sewing", "received_sewing"):
        raise HTTPException(409, "This bundle sticker was already processed")
    if bundle.status not in ("created",):
        raise HTTPException(400, f"Bundle in status '{bundle.status}' cannot be sent to printing")
    bundle.next_department_id = _dept(db, DEPT_PRT).id if _dept(db, DEPT_PRT) else None
    _transition(db, bundle, "sent_printing", "sent_to_printing", DEPT_CUT, DEPT_PRT, user_id)
    wo = _work_order_for_bundle(db, bundle, "printing")
    if wo and wo.status in ("new", "planning", "waiting"):
        wo.status = "pending"
    notify_department(
        db,
        department_code=DEPT_PRT,
        title="Bundle sent to printing",
        message=f"{bundle.bundle_no} is on the way to printing.",
        link="/bundles/scan/printing",
        exclude_user_id=user_id,
    )
    sync_production_order_status(db, bundle.production_order_id)


def receive_at_printing(db: Session, bundle: Bundle, user_id: int | None = None):
    if bundle.status == "received_printing":
        raise HTTPException(409, "This bundle sticker was already received at printing")
    if bundle.status in ("sent_to_sewing", "received_sewing"):
        raise HTTPException(409, "This bundle sticker was already processed")
    if bundle.status != "sent_to_printing":
        raise HTTPException(400, f"Bundle in status '{bundle.status}' cannot be received at printing")
    _transition(db, bundle, "received_printing", "received_printing", DEPT_CUT, DEPT_PRT, user_id)
    wo = _work_order_for_bundle(db, bundle, "printing")
    if wo and wo.status in ("new", "planning", "waiting"):
        wo.status = "pending"
    sync_production_order_status(db, bundle.production_order_id)


def send_to_sewing(db: Session, bundle: Bundle, user_id: int | None = None):
    _require_cutting_batch_approved(db, bundle)
    if bundle.status == "sent_to_sewing":
        raise HTTPException(409, "This bundle sticker was already sent to sewing")
    if bundle.status == "received_sewing":
        raise HTTPException(409, "This bundle sticker was already received at sewing")
    if bundle.status not in ("created", "received_printing"):
        raise HTTPException(400, f"Bundle in status '{bundle.status}' cannot be sent to sewing")
    from app.services.inventory import ensure_accessories_issued_for_sewing

    ensure_accessories_issued_for_sewing(db, int(bundle.production_order_id))
    from_code = DEPT_PRT if bundle.status == "received_printing" else DEPT_CUT
    factory_code = resolve_sewing_factory_code(bundle.sewing_factory_code)
    target = _sewing_factory_dept(db, factory_code)
    target_code = target.code if target else factory_code
    bundle.sewing_factory_code = factory_code
    bundle.next_department_id = target.id if target else None
    _transition(db, bundle, "sent_sewing", "sent_to_sewing", from_code, target_code, user_id)
    sync_textile_departments_for_bundle_route(db, bundle.production_order_id, bundle.production_batch_id)
    wo = _work_order_for_bundle(db, bundle, "sewing")
    if wo and wo.status in ("new", "planning", "waiting"):
        wo.status = "in_progress"
    notify_department(
        db,
        department_code=target_code,
        title="Bundle sent to sewing factory",
        message=f"{bundle.bundle_no} is ready for receive scan at {target.name if target else target_code}.",
        link=f"/departments/{target_code}",
        exclude_user_id=user_id,
    )
    sync_production_order_status(db, bundle.production_order_id)


def receive_at_sewing(db: Session, bundle: Bundle, user_id: int | None = None):
    if bundle.status == "received_sewing":
        raise HTTPException(409, "This bundle sticker was already received at sewing")
    from app.services.inventory import ensure_accessories_issued_for_sewing

    ensure_accessories_issued_for_sewing(db, int(bundle.production_order_id))
    target = _sewing_factory_dept(db, bundle.sewing_factory_code)
    generic = _dept(db, DEPT_SEW)
    allowed_ids = {d.id for d in (target, generic) if d}
    target_code = target.code if target else DEPT_SEW
    if bundle.status == "created" and bundle.next_department_id in allowed_ids:
        bundle.sewing_factory_code = resolve_sewing_factory_code(bundle.sewing_factory_code)
        _transition(db, bundle, "received_sewing", "received_sewing", DEPT_CUT, target_code, user_id)
    elif bundle.status == "sent_to_sewing":
        bundle.sewing_factory_code = resolve_sewing_factory_code(bundle.sewing_factory_code)
        _transition(db, bundle, "received_sewing", "received_sewing", None, target_code, user_id)
    else:
        raise HTTPException(400, f"Bundle in status '{bundle.status}' cannot be received at sewing")
    sync_textile_departments_for_bundle_route(db, bundle.production_order_id, bundle.production_batch_id)
    wo = _work_order_for_bundle(db, bundle, "sewing")
    if wo:
        qty_filters = [
            Bundle.production_order_id == bundle.production_order_id,
            Bundle.status == "received_sewing",
        ]
        if wo.production_batch_id is not None:
            qty_filters.append(Bundle.production_batch_id == wo.production_batch_id)
        received_qty = int(
            db.query(func.coalesce(func.sum(Bundle.quantity), 0))
            .filter(*qty_filters)
            .scalar()
            or 0
        )
        wo.actual_input_qty = max(int(wo.actual_input_qty or 0), received_qty)
        if wo.status in ("new", "planning", "waiting"):
            wo.status = "in_progress"
    sync_production_order_status(db, bundle.production_order_id)
