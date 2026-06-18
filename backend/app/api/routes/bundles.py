from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import or_
import base64
from html import escape
import os

from app.core.config import settings
from app.core.deps import DbSession, CurrentUser, require_permissions, user_permissions
from app.models import Bundle, Model, ProductionOrder, ProductionBatch, SalesOrder, User, public_production_order_no
from app.schemas.tracking import BundleIn, BundleOut, BundleDetail
from app.services.bundles import (
    create_bundle,
    send_to_printing,
    receive_at_printing,
    send_to_sewing,
    receive_at_sewing,
    bundle_qr_payload,
    format_batch_passport,
)
from app.services.barcode import save_qr_image
from app.services.audit import log_action

router = APIRouter(prefix="/bundles", tags=["bundles"])


def _h(value) -> str:
    return escape(str(value or ""), quote=True)


def _qr_data_uri_for_bundle(db: DbSession, b: Bundle) -> str:
    qr_rel = save_qr_image(bundle_qr_payload(db, b), f"bundle_qr_{b.bundle_no}")
    if b.qr_code_url != qr_rel:
        b.qr_code_url = qr_rel
        db.add(b)
        db.commit()
        db.refresh(b)
    fname = qr_rel.split("/storage/barcodes/", 1)[1]
    qr_path = os.path.join(settings.BARCODE_STORAGE_DIR, fname)

    with open(qr_path, "rb") as fh:
        png = fh.read()
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _batch_meta(db: DbSession, production_order_id: int | None, production_batch_id: int | None) -> dict:
    if not production_batch_id:
        return {
            "batch_no": None,
            "batch_name": None,
            "batch_index": None,
            "batch_label": None,
            "tracking_passport_no": None,
        }
    batch = db.get(ProductionBatch, production_batch_id)
    if not batch:
        label = f"Batch #{production_batch_id}"
        return {
            "batch_no": None,
            "batch_name": None,
            "batch_index": None,
            "batch_label": label,
            "tracking_passport_no": label,
        }
    passport = format_batch_passport(batch, production_order_id)
    name = str(batch.name or "").strip() or None
    label = f"{passport} - {name}" if name else passport
    return {
        "batch_no": batch.batch_no,
        "batch_name": name,
        "batch_index": batch.batch_index,
        "batch_label": label,
        "tracking_passport_no": passport,
    }


def _bundle_payload(
    db: DbSession,
    bundle: Bundle,
    production_no: str | None = None,
    order_no: str | None = None,
    model_code: str | None = None,
) -> dict:
    row = BundleOut.model_validate(bundle).model_dump()
    if production_no is None or order_no is None:
        po = db.get(ProductionOrder, bundle.production_order_id)
        if po:
            production_no = production_no or po.production_no
            order_no = order_no or po.order_no
    if order_no is None and bundle.sales_order_id:
        so = db.get(SalesOrder, bundle.sales_order_id)
        order_no = so.order_no if so else None
    if model_code is None:
        model = db.get(Model, bundle.model_id)
        model_code = model.code if model else None
    row["production_no"] = production_no
    row["order_no"] = order_no or public_production_order_no(production_no) or production_no
    row["model_code"] = model_code
    row.update(_batch_meta(db, bundle.production_order_id, bundle.production_batch_id))
    return row


def _bundle_detail_payload(db: DbSession, bundle: Bundle) -> dict:
    row = BundleDetail.model_validate(bundle).model_dump()
    row.update(_bundle_payload(db, bundle))
    return row


def _label_context(db: DbSession, b: Bundle) -> dict:
    row = _bundle_payload(db, b)
    return {
        "bundle_no": _h(b.bundle_no),
        "order_no": _h(row.get("order_no") or row.get("production_no") or b.production_order_id),
        "batch_label": _h(row.get("batch_label")),
        "tracking_passport_no": _h(row.get("tracking_passport_no")),
        "model_code": _h(row.get("model_code") or b.model_id),
        "color": _h(b.color),
        "size": _h(b.size),
        "quantity": _h(b.quantity),
        "barcode": _h(b.barcode),
    }


def _bundle_label_card(ctx: dict, qr: str) -> str:
    batch_row = (
        f"<div class='row'><b>Batch</b><span>{ctx['batch_label']}</span></div>"
        if ctx.get("batch_label")
        else ""
    )
    passport_row = (
        f"<div class='row'><b>Tracking passport</b><span>{ctx['tracking_passport_no']}</span></div>"
        if ctx.get("tracking_passport_no")
        else ""
    )
    return f"""
            <div class='label'>
              <h2>MILANA ERP</h2>
              <div class='row'><b>Bundle</b><span>{ctx['bundle_no']}</span></div>
              <div class='row'><b>Order</b><span>{ctx['order_no']}</span></div>
              {batch_row}
              {passport_row}
              <div class='row'><b>Model</b><span>{ctx['model_code']}</span></div>
              <div class='row'><b>Color / Size</b><span>{ctx['color']} / {ctx['size']}</span></div>
              <div class='row'><b>Qty</b><span>{ctx['quantity']}</span></div>
              <div class='row'><b>Barcode</b><span>{ctx['barcode']}</span></div>
              <div class='qr'><img src='{qr}' alt='QR'/></div>
            </div>
            """


def _bundle_lookup_candidates(raw_code: str) -> list[str]:
    code = (raw_code or "").strip()
    if not code:
        return []

    candidates: list[str] = [code]
    if "|" in code:
        candidates.extend([part.strip() for part in code.split("|") if part.strip()])
    if code.upper().startswith("BUNDLE:"):
        payload = code.split(":", 1)[1]
        candidates.extend([part.strip() for part in payload.split("|") if part.strip()])

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        token = candidate.strip()
        if token and token not in seen:
            seen.add(token)
            unique.append(token)
    return unique


def _find_bundle_by_scanned_code(db: DbSession, code: str) -> Bundle | None:
    candidates = _bundle_lookup_candidates(code)
    if not candidates:
        return None
    return (
        db.query(Bundle)
        .filter(or_(Bundle.barcode.in_(candidates), Bundle.bundle_no.in_(candidates)))
        .order_by(Bundle.id.desc())
        .first()
    )


def _get_bundle_for_update(db: DbSession, bid: int) -> Bundle:
    b = db.query(Bundle).filter(Bundle.id == bid).with_for_update().first()
    if not b:
        raise HTTPException(404, "Bundle not found")
    return b


@router.get("")
def list_bundles(db: DbSession, _: CurrentUser,
                 production_order_id: int | None = None, status: str | None = None,
                 production_batch_id: int | None = None,
                 model_id: int | None = None, page: int = 1, page_size: int = 50,
                 include_total: bool = False):
    qry = db.query(Bundle, ProductionOrder.production_no, SalesOrder.order_no, Model.code).outerjoin(
        ProductionOrder, Bundle.production_order_id == ProductionOrder.id
    ).outerjoin(
        SalesOrder, SalesOrder.id == ProductionOrder.sales_order_id
    ).outerjoin(
        Model, Bundle.model_id == Model.id
    )
    if production_order_id: qry = qry.filter(Bundle.production_order_id == production_order_id)
    if production_batch_id is not None: qry = qry.filter(Bundle.production_batch_id == production_batch_id)
    if status: qry = qry.filter(Bundle.status == status)
    if model_id: qry = qry.filter(Bundle.model_id == model_id)
    total = qry.count() if include_total else 0
    safe_page = max(1, page)
    safe_size = max(1, min(page_size, 2000))
    rows = (
        qry.order_by(
            Bundle.production_order_id.desc(),
            Bundle.production_batch_id.desc(),
            Bundle.id.desc(),
        )
        .offset((safe_page - 1) * safe_size)
        .limit(safe_size)
        .all()
    )
    out: list[dict] = []
    for bundle, production_no, sales_order_no, model_code in rows:
        out.append(_bundle_payload(
            db,
            bundle,
            production_no=production_no,
            order_no=sales_order_no or public_production_order_no(production_no),
            model_code=model_code,
        ))
    if include_total:
        return {"rows": out, "total": total, "page": safe_page, "page_size": safe_size}
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
        production_batch_id=payload.production_batch_id,
        user_id=current.id,
        notes=payload.notes,
    )
    log_action(db, current, "create", "Bundle", b.id, new_value={"bundle_no": b.bundle_no})
    db.commit(); db.refresh(b)
    return _bundle_payload(db, b)


@router.get("/lookup", response_model=BundleDetail)
def lookup_bundle(code: str, db: DbSession, _: CurrentUser):
    b = _find_bundle_by_scanned_code(db, code)
    if not b:
        raise HTTPException(404, "Bundle not found")
    return _bundle_detail_payload(db, b)


@router.get("/barcode/{code}", response_model=BundleDetail)
def get_by_barcode(code: str, db: DbSession, _: CurrentUser):
    b = _find_bundle_by_scanned_code(db, code)
    if not b:
        raise HTTPException(404, "Bundle not found")
    return _bundle_detail_payload(db, b)


@router.get("/{bid}", response_model=BundleDetail)
def get_bundle(bid: int, db: DbSession, _: CurrentUser):
    b = db.get(Bundle, bid)
    if not b: raise HTTPException(404, "Bundle not found")
    return _bundle_detail_payload(db, b)


@router.post("/{bid}/send-printing", response_model=BundleDetail)
def api_send_printing(bid: int, db: DbSession, current: User = Depends(require_permissions("cutting.bundles", "*"))):
    b = _get_bundle_for_update(db, bid)
    send_to_printing(db, b, current.id)
    log_action(db, current, "send_to_printing", "Bundle", b.id)
    db.commit(); db.refresh(b)
    return _bundle_detail_payload(db, b)


@router.post("/{bid}/receive-printing", response_model=BundleDetail)
def api_receive_printing(bid: int, db: DbSession, current: User = Depends(require_permissions("printing.bundles", "*"))):
    b = _get_bundle_for_update(db, bid)
    receive_at_printing(db, b, current.id)
    log_action(db, current, "receive_at_printing", "Bundle", b.id)
    db.commit(); db.refresh(b)
    return _bundle_detail_payload(db, b)


@router.post("/{bid}/send-sewing", response_model=BundleDetail)
def api_send_sewing(
    bid: int,
    db: DbSession,
    current: User = Depends(require_permissions("cutting.bundles", "printing.bundles", "*")),
):
    b = _get_bundle_for_update(db, bid)
    perms = set(user_permissions(current))
    if "*" not in perms:
        if b.status == "created" and "cutting.bundles" not in perms:
            raise HTTPException(403, "Only Cutting department can send newly created bundles to sewing")
        if b.status == "received_printing" and "printing.bundles" not in perms:
            raise HTTPException(403, "Only Printing department can send printed bundles to sewing")
    send_to_sewing(db, b, current.id)
    log_action(db, current, "send_to_sewing", "Bundle", b.id)
    db.commit(); db.refresh(b)
    return _bundle_detail_payload(db, b)


@router.post("/{bid}/receive-sewing", response_model=BundleDetail)
def api_receive_sewing(bid: int, db: DbSession, current: User = Depends(require_permissions("sewing.bundles", "*"))):
    b = _get_bundle_for_update(db, bid)
    receive_at_sewing(db, b, current.id)
    log_action(db, current, "receive_at_sewing", "Bundle", b.id)
    db.commit(); db.refresh(b)
    return _bundle_detail_payload(db, b)


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
    qr = _qr_data_uri_for_bundle(db, b)
    ctx = _label_context(db, b)
    return f"""<!doctype html>
<html><head><title>Bundle Label {ctx['bundle_no']}</title>
<style>@page{{margin:8mm}} body{{font-family:Arial;margin:0;padding:8mm}} .label{{box-sizing:border-box;break-inside:avoid;page-break-inside:avoid;border:1px solid #000;padding:5mm;width:88mm}} .row{{display:flex;justify-content:space-between;gap:4mm;font-size:8.5pt;line-height:1.22}} .row span{{text-align:right;overflow-wrap:anywhere}} .qr{{text-align:center;margin-top:2.5mm}} img{{max-width:25mm;max-height:25mm}} h2{{margin:0 0 2mm 0;font-size:12pt;letter-spacing:0}}@media print{{body{{margin:0;padding:0}} button{{display:none}}}}</style></head>
<body>{_bundle_label_card(ctx, qr)}
<button onclick=\"window.print()\">Print</button>
</body></html>"""


@router.get("/label-sheet/by-ids", response_class=HTMLResponse)
def bundle_label_sheet(ids: str, db: DbSession, _: CurrentUser):
    raw_ids = [s.strip() for s in (ids or "").split(",") if s.strip()]
    try:
        parsed_ids = [int(v) for v in raw_ids]
    except ValueError:
        raise HTTPException(400, "ids must be comma-separated integers")
    if not parsed_ids:
        raise HTTPException(400, "Provide at least one bundle id")

    bundles = (
        db.query(Bundle)
        .filter(Bundle.id.in_(parsed_ids))
        .order_by(Bundle.production_order_id.asc(), Bundle.production_batch_id.asc(), Bundle.id.asc())
        .all()
    )
    if not bundles:
        raise HTTPException(404, "No bundles found")

    cards = []
    for b in bundles:
        qr = _qr_data_uri_for_bundle(db, b)
        cards.append(_bundle_label_card(_label_context(db, b), qr))

    return f"""<!doctype html>
<html><head><title>Bundle Label Sheet</title>
<style>
@page{{margin:6mm}}
html,body{{font-family:Arial;margin:0;padding:0}}
.sheet{{font-size:0}}
.label{{display:inline-block;vertical-align:top;box-sizing:border-box;width:96mm;min-height:56mm;margin:0 4mm 4mm 0;border:1px solid #000;padding:4mm;font-size:8.5pt;break-inside:avoid;page-break-inside:avoid}}
.label:nth-child(2n){{margin-right:0}}
.row{{display:flex;justify-content:space-between;gap:3mm;font-size:8.5pt;line-height:1.18}}
.row span{{text-align:right;overflow-wrap:anywhere}}
.qr{{text-align:center;margin-top:2mm}}
img{{max-width:23mm;max-height:23mm}}
h2{{margin:0 0 1.5mm 0;font-size:11pt;letter-spacing:0}}
@media print{{button{{display:none}} .label{{break-inside:avoid;page-break-inside:avoid}}}}
</style></head>
<body>
<div class='sheet'>{''.join(cards)}</div>
<button onclick="window.print()" style="margin-top:6mm">Print</button>
</body></html>"""


@router.get("/label-sheet/by-production-order/{production_order_id}", response_class=HTMLResponse)
def bundle_label_sheet_by_production_order(production_order_id: int, db: DbSession, _: CurrentUser):
    bundles = (
        db.query(Bundle)
        .filter(Bundle.production_order_id == production_order_id)
        .order_by(Bundle.production_batch_id.asc(), Bundle.id.asc())
        .all()
    )
    if not bundles:
        raise HTTPException(404, "No bundles found")

    ids = ",".join(str(int(b.id)) for b in bundles)
    return bundle_label_sheet(ids=ids, db=db, _=_)


@router.get("/label-sheet/by-batch/{production_batch_id}", response_class=HTMLResponse)
def bundle_label_sheet_by_batch(production_batch_id: int, db: DbSession, _: CurrentUser):
    bundles = (
        db.query(Bundle)
        .filter(Bundle.production_batch_id == production_batch_id)
        .order_by(Bundle.id.asc())
        .all()
    )
    if not bundles:
        raise HTTPException(404, "No bundles found")

    ids = ",".join(str(int(b.id)) for b in bundles)
    return bundle_label_sheet(ids=ids, db=db, _=_)
