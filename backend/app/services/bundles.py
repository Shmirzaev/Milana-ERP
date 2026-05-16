"""Bundle service: create cutting bundles with QR/barcode, manage scan transitions."""
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    Bundle, BundleScanLog, ProductionOrder, Department, SalesOrder, WorkOrder,
)
from app.services.barcode import generate_barcode_value, save_qr_image, save_barcode_image
from app.services.numbering import next_bundle_no
from app.services.workflow import notify_department, sync_production_order_status


DEPT_CUT = "CUT"
DEPT_PRT = "PRT"
DEPT_SEW = "SEW"


def _dept(db: Session, code: str) -> Department | None:
    return db.query(Department).filter(Department.code == code).first()


def create_bundle(
    db: Session,
    *,
    production_order_id: int,
    model_id: int,
    color: str,
    size: str,
    quantity: int,
    sales_order_id: int | None = None,
    brand_id: int | None = None,
    collection_id: int | None = None,
    next_department_code: str = DEPT_SEW,
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

    cut = _dept(db, DEPT_CUT)
    nxt = _dept(db, next_department_code)

    bundle_no = next_bundle_no(db)
    barcode_value = generate_barcode_value("BND")
    b = Bundle(
        bundle_no=bundle_no,
        barcode=barcode_value,
        production_order_id=production_order_id,
        sales_order_id=sales_order_id,
        brand_id=brand_id,
        collection_id=collection_id,
        model_id=model_id,
        color=color,
        size=size,
        quantity=quantity,
        current_department_id=cut.id if cut else None,
        next_department_id=nxt.id if nxt else None,
        status="created",
        created_by=user_id,
        notes=notes,
    )
    db.add(b)
    db.flush()

    qr_payload = f"BUNDLE:{bundle_no}|{barcode_value}"
    b.qr_code_url = save_qr_image(qr_payload, f"bundle_qr_{bundle_no}")
    # also persist a barcode image for printing labels
    save_barcode_image(barcode_value, f"bundle_bc_{bundle_no}")

    db.add(BundleScanLog(
        bundle_id=b.id, scanned_by=user_id, scan_type="created",
        from_department_id=None, to_department_id=cut.id if cut else None,
    ))
    db.flush()
    return b


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
    if bundle.status not in ("created",):
        raise HTTPException(400, f"Bundle in status '{bundle.status}' cannot be sent to printing")
    bundle.next_department_id = _dept(db, DEPT_PRT).id if _dept(db, DEPT_PRT) else None
    _transition(db, bundle, "sent_printing", "sent_to_printing", DEPT_CUT, DEPT_PRT, user_id)
    wo = db.query(WorkOrder).filter(
        WorkOrder.production_order_id == bundle.production_order_id,
        WorkOrder.operation == "printing",
    ).first()
    if wo and wo.status in ("new", "planning", "waiting"):
        wo.status = "in_progress"
    notify_department(
        db,
        department_code=DEPT_PRT,
        title="Bundle sent to printing",
        message=f"{bundle.bundle_no} is on the way to printing.",
        exclude_user_id=user_id,
    )
    sync_production_order_status(db, bundle.production_order_id)


def receive_at_printing(db: Session, bundle: Bundle, user_id: int | None = None):
    if bundle.status != "sent_to_printing":
        raise HTTPException(400, f"Bundle in status '{bundle.status}' cannot be received at printing")
    _transition(db, bundle, "received_printing", "received_printing", DEPT_CUT, DEPT_PRT, user_id)
    wo = db.query(WorkOrder).filter(
        WorkOrder.production_order_id == bundle.production_order_id,
        WorkOrder.operation == "printing",
    ).first()
    if wo and wo.status in ("new", "planning", "waiting"):
        wo.status = "in_progress"
    sync_production_order_status(db, bundle.production_order_id)


def send_to_sewing(db: Session, bundle: Bundle, user_id: int | None = None):
    if bundle.status not in ("created", "received_printing"):
        raise HTTPException(400, f"Bundle in status '{bundle.status}' cannot be sent to sewing")
    from_code = DEPT_PRT if bundle.status == "received_printing" else DEPT_CUT
    bundle.next_department_id = _dept(db, DEPT_SEW).id if _dept(db, DEPT_SEW) else None
    _transition(db, bundle, "sent_sewing", "sent_to_sewing", from_code, DEPT_SEW, user_id)
    wo = db.query(WorkOrder).filter(
        WorkOrder.production_order_id == bundle.production_order_id,
        WorkOrder.operation == "sewing",
    ).first()
    if wo and wo.status in ("new", "planning", "waiting"):
        wo.status = "in_progress"
    notify_department(
        db,
        department_code=DEPT_SEW,
        title="Bundle sent to sewing",
        message=f"{bundle.bundle_no} is ready for sewing receive scan.",
        exclude_user_id=user_id,
    )
    sync_production_order_status(db, bundle.production_order_id)


def receive_at_sewing(db: Session, bundle: Bundle, user_id: int | None = None):
    if bundle.status != "sent_to_sewing":
        raise HTTPException(400, f"Bundle in status '{bundle.status}' cannot be received at sewing")
    _transition(db, bundle, "received_sewing", "received_sewing", None, DEPT_SEW, user_id)
    wo = db.query(WorkOrder).filter(
        WorkOrder.production_order_id == bundle.production_order_id,
        WorkOrder.operation == "sewing",
    ).first()
    if wo and wo.status in ("new", "planning", "waiting"):
        wo.status = "in_progress"
    sync_production_order_status(db, bundle.production_order_id)
