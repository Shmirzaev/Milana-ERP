from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import Bundle, Model, ProductionOrder, User
from app.schemas.tracking import BundleIn, BundleOut, BundleDetail
from app.services.bundles import (
    create_bundle, send_to_printing, receive_at_printing, send_to_sewing, receive_at_sewing,
)
from app.services.audit import log_action

router = APIRouter(prefix="/bundles", tags=["bundles"])


@router.get("", response_model=list[BundleOut])
def list_bundles(db: DbSession, _: CurrentUser,
                 production_order_id: int | None = None, status: str | None = None,
                 model_id: int | None = None, page: int = 1, page_size: int = 100):
    qry = db.query(Bundle, ProductionOrder.production_no).outerjoin(
        ProductionOrder, Bundle.production_order_id == ProductionOrder.id
    )
    if production_order_id: qry = qry.filter(Bundle.production_order_id == production_order_id)
    if status: qry = qry.filter(Bundle.status == status)
    if model_id: qry = qry.filter(Bundle.model_id == model_id)
    rows = qry.order_by(Bundle.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    out: list[dict] = []
    for bundle, production_no in rows:
        row = BundleOut.model_validate(bundle).model_dump()
        row["production_no"] = production_no
        out.append(row)
    return out


@router.post("", response_model=BundleOut, status_code=201)
def create_bundle_api(payload: BundleIn, db: DbSession, current: User = Depends(require_permissions("cutting.bundles", "*"))):
    b = create_bundle(
        db,
        production_order_id=payload.production_order_id,
        model_id=payload.model_id,
        color=payload.color,
        size=payload.size,
        quantity=payload.quantity,
        sales_order_id=payload.sales_order_id,
        brand_id=payload.brand_id,
        collection_id=payload.collection_id,
        user_id=current.id,
        notes=payload.notes,
    )
    log_action(db, current, "create", "Bundle", b.id, new_value={"bundle_no": b.bundle_no})
    db.commit(); db.refresh(b)
    return b


@router.get("/{bid}", response_model=BundleDetail)
def get_bundle(bid: int, db: DbSession, _: CurrentUser):
    b = db.get(Bundle, bid)
    if not b: raise HTTPException(404, "Bundle not found")
    return b


@router.get("/barcode/{code}", response_model=BundleDetail)
def get_by_barcode(code: str, db: DbSession, _: CurrentUser):
    b = db.query(Bundle).filter((Bundle.barcode == code) | (Bundle.bundle_no == code)).first()
    if not b: raise HTTPException(404, "Bundle not found")
    return b


@router.post("/{bid}/send-printing", response_model=BundleDetail)
def api_send_printing(bid: int, db: DbSession, current: User = Depends(require_permissions("cutting.bundles", "*"))):
    b = db.get(Bundle, bid)
    if not b: raise HTTPException(404, "Bundle not found")
    send_to_printing(db, b, current.id)
    log_action(db, current, "send_to_printing", "Bundle", b.id)
    db.commit(); db.refresh(b)
    return b


@router.post("/{bid}/receive-printing", response_model=BundleDetail)
def api_receive_printing(bid: int, db: DbSession, current: User = Depends(require_permissions("printing.bundles", "*"))):
    b = db.get(Bundle, bid)
    if not b: raise HTTPException(404, "Bundle not found")
    receive_at_printing(db, b, current.id)
    log_action(db, current, "receive_at_printing", "Bundle", b.id)
    db.commit(); db.refresh(b)
    return b


@router.post("/{bid}/send-sewing", response_model=BundleDetail)
def api_send_sewing(bid: int, db: DbSession, current: CurrentUser):
    b = db.get(Bundle, bid)
    if not b: raise HTTPException(404, "Bundle not found")
    send_to_sewing(db, b, current.id)
    log_action(db, current, "send_to_sewing", "Bundle", b.id)
    db.commit(); db.refresh(b)
    return b


@router.post("/{bid}/receive-sewing", response_model=BundleDetail)
def api_receive_sewing(bid: int, db: DbSession, current: User = Depends(require_permissions("sewing.bundles", "*"))):
    b = db.get(Bundle, bid)
    if not b: raise HTTPException(404, "Bundle not found")
    receive_at_sewing(db, b, current.id)
    log_action(db, current, "receive_at_sewing", "Bundle", b.id)
    db.commit(); db.refresh(b)
    return b


@router.get("/{bid}/history")
def get_history(bid: int, db: DbSession, _: CurrentUser):
    b = db.get(Bundle, bid)
    if not b: raise HTTPException(404, "Bundle not found")
    return [
        {
            "id": s.id, "scan_type": s.scan_type, "scanned_by": s.scanned_by,
            "from_department_id": s.from_department_id, "to_department_id": s.to_department_id,
            "scanned_at": s.scanned_at,
        }
        for s in b.scan_logs
    ]


@router.get("/{bid}/label", response_class=HTMLResponse)
def bundle_label(bid: int, db: DbSession, _: CurrentUser):
    """Returns a printable HTML label."""
    b = db.get(Bundle, bid)
    if not b: raise HTTPException(404, "Bundle not found")
    model = db.get(Model, b.model_id)
    qr = b.qr_code_url or ""
    return f"""<!doctype html>
<html><head><title>Bundle Label {b.bundle_no}</title>
<style>body{{font-family:Arial;margin:0;padding:8mm}} .label{{border:1px solid #000;padding:6mm;width:80mm}} .row{{display:flex;justify-content:space-between;font-size:10pt}} img{{max-width:32mm}} h2{{margin:0 0 4mm 0;font-size:14pt}}@media print{{body{{margin:0}}}}</style></head>
<body><div class=\"label\">
<h2>MILANA ERP</h2>
<div class=\"row\"><b>Bundle</b><span>{b.bundle_no}</span></div>
<div class=\"row\"><b>Model</b><span>{model.code if model else ''}</span></div>
<div class=\"row\"><b>Color</b><span>{b.color}</span></div>
<div class=\"row\"><b>Size</b><span>{b.size}</span></div>
<div class=\"row\"><b>Qty</b><span>{b.quantity}</span></div>
<div class=\"row\"><b>Barcode</b><span>{b.barcode}</span></div>
<div style=\"text-align:center;margin-top:4mm\"><img src=\"{qr}\" alt=\"QR\"/></div>
<button onclick=\"window.print()\">Print</button>
</div></body></html>"""
