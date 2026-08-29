from fastapi import APIRouter, HTTPException, Depends, Header
from fastapi.responses import HTMLResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload
import base64
from datetime import date
from html import escape
import os

from app.core.deps import DbSession, CurrentUser, PRODUCTION_READ_PERMISSIONS, require_permissions, is_admin
from app.core.config import settings
from app.core.dt import date_filter_bounds
from app.core.model_search import (
    model_code_contains,
    normalized_model_code_column,
    normalized_model_code_pattern,
)
from app.models import (
    Customer,
    Package,
    PackageBarcodeAlias,
    PackageChangeRequest,
    PackageScanLog,
    Model,
    ModelBOM,
    ProductionOrder,
    ProductionBatch,
    SalesOrder,
    StockBatch,
    User,
)
from app.schemas.tracking import (
    PackageIn,
    PackageBulkIn,
    PackageOut,
    PackageDetail,
    PackageBatchReceiveStorageIn,
    PackageReceivingQueueRemoveIn,
    PackageReceivingQueueScanIn,
    PackageBatchStoragePlacementIn,
    PackageReceiveStorageIn,
    PackageStoragePlacementIn,
    PackageChangeRequestIn,
    PackageChangeDecisionIn,
    PackageChangeRequestOut,
)
from app.services.packages import (
    WAREHOUSE_MAP_LAYOUT,
    create_package,
    create_packages_bulk,
    receive_at_storage,
    reserve_package,
    ship_package,
    mark_delivered,
    mark_damaged,
    place_on_storage_map,
    format_storage_location,
    create_package_change_request,
    approve_package_change_request,
    reject_package_change_request,
)
from app.services.barcode import save_qr_image
from app.services.label_images import variant_label_image_src
from app.services.model_images import model_display_image_url
from app.services.audit import log_action
from app.services.idempotency import replay_idempotent_response, store_idempotent_response
from app.services.packaging_scope import (
    packaging_department_for_order,
    packaging_department_scope,
    require_package_access,
)

router = APIRouter(prefix="/packages", tags=["packages"])
_RECEIVING_QUEUE_EVENTS = (
    "queued_storage",
    "removed_storage_queue",
    "received_storage",
)


def _package_context(db: DbSession, pkg: Package) -> dict:
    po = db.get(ProductionOrder, pkg.production_order_id) if pkg.production_order_id else None
    so = db.get(SalesOrder, pkg.sales_order_id) if pkg.sales_order_id else None
    customer = db.get(Customer, so.customer_id) if so and so.customer_id else None
    model = (
        db.query(Model)
        .options(selectinload(Model.images), selectinload(Model.bom).joinedload(ModelBOM.item))
        .filter(Model.id == pkg.model_id)
        .first()
        if pkg.model_id
        else None
    )
    return {
        "production_no": po.production_no if po else None,
        "sales_order_no": so.order_no if so else None,
        "order_no": so.order_no if so else (po.order_no if po else None),
        "customer_name": customer.name if customer else None,
        "order_type": so.order_type if so else (po.production_type if po else None),
        "model_code": model.code if model else None,
        "model_name": model.name if model else None,
        "model_image_url": model_display_image_url(model),
    }


def _package_out_payload(db: DbSession, pkg: Package) -> dict:
    data = PackageOut.model_validate(pkg).model_dump(mode="json")
    data.update(_package_context(db, pkg))
    return data


def _package_detail_payload(db: DbSession, pkg: Package) -> dict:
    data = PackageDetail.model_validate(pkg).model_dump(mode="json")
    data.update(_package_context(db, pkg))
    return data


def _receiving_queue_packages(db: DbSession) -> list[Package]:
    latest_event = (
        db.query(
            PackageScanLog.package_id.label("package_id"),
            func.max(PackageScanLog.id).label("event_id"),
        )
        .filter(PackageScanLog.scan_type.in_(_RECEIVING_QUEUE_EVENTS))
        .group_by(PackageScanLog.package_id)
        .subquery()
    )
    return (
        db.query(Package)
        .join(latest_event, latest_event.c.package_id == Package.id)
        .join(PackageScanLog, PackageScanLog.id == latest_event.c.event_id)
        .filter(
            Package.status == "packed",
            PackageScanLog.scan_type == "queued_storage",
        )
        .order_by(PackageScanLog.id.desc())
        .all()
    )


def _package_for_receiving_scan(db: DbSession, raw_code: str) -> Package | None:
    for candidate in _package_lookup_candidates(raw_code):
        pkg = (
            db.query(Package)
            .filter((Package.barcode == candidate) | (Package.package_no == candidate))
            .first()
        )
        if pkg:
            return pkg

        alias_ids = [
            int(package_id)
            for (package_id,) in (
                db.query(PackageBarcodeAlias.package_id)
                .filter(PackageBarcodeAlias.code == candidate)
                .order_by(PackageBarcodeAlias.package_id.asc())
                .all()
            )
        ]
        if len(alias_ids) == 1:
            return db.get(Package, alias_ids[0])
        if len(alias_ids) > 1:
            raise HTTPException(409, "This legacy barcode matches more than one package. Scan the package QR label instead.")
    return None


def _latest_receiving_queue_event(db: DbSession, package_id: int) -> PackageScanLog | None:
    return (
        db.query(PackageScanLog)
        .filter(
            PackageScanLog.package_id == package_id,
            PackageScanLog.scan_type.in_(_RECEIVING_QUEUE_EVENTS),
        )
        .order_by(PackageScanLog.id.desc())
        .first()
    )


def _h(value) -> str:
    escaped = escape(str(value or ""), quote=True)
    # Label sheets are opened through Blob URLs before printing. Some Windows
    # print-preview paths decode those Blob documents with a legacy code page,
    # corrupting Cyrillic model and product names. Numeric references keep the
    # dynamic HTML source ASCII while rendering the exact Unicode text.
    return escaped.encode("ascii", "xmlcharrefreplace").decode("ascii")


def _qr_data_uri_for_package(db: DbSession, pkg: Package) -> str:
    """Return a render-safe QR src for HTML labels (data URI).

    Label pages are opened via Blob URLs in the frontend, so relative image URLs
    like /storage/barcodes/... can fail to resolve. We embed QR as base64 PNG to
    keep printing reliable in all browsers.
    """
    qr_rel = (pkg.qr_code_url or "").strip()
    qr_path = ""
    if qr_rel.startswith("/storage/barcodes/"):
        fname = qr_rel.split("/storage/barcodes/", 1)[1]
        qr_path = os.path.join(settings.BARCODE_STORAGE_DIR, fname)

    if not qr_path or not os.path.isfile(qr_path):
        payload = f"PACKAGE:{pkg.package_no}|{pkg.barcode}"
        qr_rel = save_qr_image(payload, f"package_qr_{pkg.package_no}")
        if pkg.qr_code_url != qr_rel:
            pkg.qr_code_url = qr_rel
            db.add(pkg)
            db.commit()
            db.refresh(pkg)
        fname = qr_rel.split("/storage/barcodes/", 1)[1]
        qr_path = os.path.join(settings.BARCODE_STORAGE_DIR, fname)

    with open(qr_path, "rb") as fh:
        png = fh.read()
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _label_model(db: DbSession, model_id: int | None) -> Model | None:
    if not model_id:
        return None
    return (
        db.query(Model)
        .options(selectinload(Model.images), selectinload(Model.bom).joinedload(ModelBOM.item))
        .filter(Model.id == model_id)
        .first()
    )


def _variant_picture_html(model: Model | None) -> str:
    src = variant_label_image_src(model)
    if not src:
        return "<div class='variant-picture variant-picture--empty' aria-label='No variant picture'>No picture</div>"
    return f"<div class='variant-picture'><img src='{_h(src)}' alt='Variant picture'/></div>"


def _format_weight_kg(value) -> str:
    if value is None:
        return ""
    try:
        weight = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{weight:.4f}".rstrip("0").rstrip(".") + " kg"


def _model_general_value(model: Model | None, *keys: str) -> str:
    details = model.details_json if model and isinstance(model.details_json, dict) else {}
    general = details.get("general") if isinstance(details.get("general"), dict) else {}
    for key in keys:
        value = str(general.get(key) or "").strip()
        if value:
            return value
    return ""


def _composition_label(item) -> str:
    parts = []
    rows = item.composition_json if item and isinstance(item.composition_json, list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        try:
            percentage = float(row.get("percentage") or 0)
        except (TypeError, ValueError):
            percentage = 0.0
        if name:
            number = str(int(percentage)) if percentage.is_integer() else f"{percentage:g}"
            parts.append(f"{number}% {name}" if percentage else name)
    return ", ".join(parts)


def _package_label_details(db: DbSession, pkg: Package, model: Model | None) -> dict[str, str]:
    po = db.get(ProductionOrder, pkg.production_order_id) if pkg.production_order_id else None
    sales_order_id = pkg.sales_order_id or (po.sales_order_id if po else None)
    so = db.get(SalesOrder, sales_order_id) if sales_order_id else None
    customer = db.get(Customer, so.customer_id) if so and so.customer_id else None

    fabric_item = None
    if po and po.fabric_batch_id:
        fabric_batch = db.get(StockBatch, po.fabric_batch_id)
        fabric_item = fabric_batch.item if fabric_batch else None
    if not fabric_item and model:
        fabric_row = next(
            (
                row
                for row in (model.bom or [])
                if row.item and str(row.item.category or "").lower() in {"fabric", "semi_finished"}
            ),
            None,
        )
        fabric_item = fabric_row.item if fabric_row else None

    fabric_name = str((fabric_item.name or fabric_item.sku) if fabric_item else "").strip()
    composition = _composition_label(fabric_item)
    fabric = " - ".join(part for part in (fabric_name, composition) if part)
    model_code = _model_general_value(model, "model_no", "modelNo") or (model.code if model else "")
    article = _model_general_value(model, "variant_no", "variantNo", "article", "artikul")
    product = (model.product_type or model.name) if model else ""
    order_no = (so.order_no if so else None) or (po.production_no if po else None)
    return {
        "client": customer.name if customer else "MILANA",
        "order": str(order_no or "-"),
        "model": str(model_code or "-"),
        "article": article or "-",
        "product": str(product or "-"),
        "fabric": fabric or "-",
    }


def _size_breakdown_html(pkg: Package) -> str:
    cells = "".join(
        f"<span class='size-cell'><b>{_h(item.size)}</b></span>"
        for item in pkg.items
    )
    return f"<div class='size-grid'>{cells}</div>" if cells else "-"


_PACKAGE_LABEL_CSS = """
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:#fff;color:#111;font-family:"DejaVu Sans",sans-serif}
.label{width:98.5mm;height:142mm;border:1.1px solid #111;display:grid;grid-template-rows:6mm 97mm 1fr;overflow:hidden;break-inside:avoid;page-break-inside:avoid;background:#fff}
.label-head{padding:0 2mm;background:#f0f0f0;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #111;font-size:9pt;font-weight:700;line-height:1}
.label-head span:last-child{font-size:6.8pt;letter-spacing:.04em}
.details{width:100%;height:97mm;border-collapse:collapse;table-layout:fixed;font-size:8.2pt}
.details tr{height:7mm}
.details tr.h8{height:8mm}.details tr.h10{height:10mm}.details tr.h12{height:12mm}.details tr.h22{height:22mm}
.details th,.details td{border-bottom:1px solid #111;padding:.8mm 1.5mm;vertical-align:middle;text-align:left;line-height:1.08}
.details th{width:28mm;border-right:1px solid #111;font-weight:700;white-space:nowrap}
.details td{font-weight:700;overflow-wrap:anywhere}
.details tr:last-child th,.details tr:last-child td{border-bottom:0}
.details .value-right{text-align:right;font-size:10pt}.details .value-large{font-size:13pt}
.size-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));border:1px solid #111;border-right:0;border-bottom:0}
.size-cell{min-width:0;border-right:1px solid #111;border-bottom:1px solid #111;text-align:center;padding:.7mm .35mm;line-height:1}
.size-cell b{display:block;font-size:10pt;overflow-wrap:anywhere}
.scan-panel{min-height:0;border-top:1px solid #111;padding:2mm;display:grid;grid-template-columns:31mm 24mm minmax(0,1fr);gap:2mm;align-items:center}
.qr img{display:block;width:31mm;height:31mm;object-fit:contain}
.variant-wrap{height:31mm;display:flex;flex-direction:column;align-items:stretch;justify-content:center;min-width:0}
.variant-caption{height:4mm;display:flex;align-items:center;justify-content:center;font-size:6.5pt;font-weight:700;line-height:1}
.variant-picture{height:27mm;border:1px solid #777;padding:1mm;display:flex;align-items:center;justify-content:center;overflow:hidden}
.variant-picture img{display:block;width:100%;height:100%;object-fit:contain}
.variant-picture--empty{font-size:6.5pt;color:#666;text-align:center}
.package-code{min-width:0;align-self:stretch;display:flex;flex-direction:column;justify-content:center;overflow-wrap:anywhere;line-height:1.15}
.package-code small{font-size:6.3pt;font-weight:700}.package-code b{margin-top:1.4mm;font-size:9pt}.package-code span{margin-top:1.2mm;font-size:7.4pt;font-weight:700}
.print-button{margin:4mm 0;padding:2mm 4mm;border:1px solid #111;background:#fff;border-radius:5px;font:9pt "DejaVu Sans",sans-serif;cursor:pointer}
@media print{.print-button{display:none}}
"""


def _package_label_card_html(db: DbSession, pkg: Package) -> str:
    model = _label_model(db, pkg.model_id)
    details = _package_label_details(db, pkg, model)
    qr = _qr_data_uri_for_package(db, pkg)
    picture = _variant_picture_html(model)
    batches = _batch_allocations_html(db, pkg) or "-"
    weight = _format_weight_kg(pkg.weight_kg) or "-"
    return f"""
<article class='label' data-package='{_h(pkg.package_no)}'>
  <header class='label-head'><span>MILANA ERP</span><span>PACKAGE LABEL</span></header>
  <table class='details'>
    <tr><th>Client</th><td class='value-right'>{_h(details['client'])}</td></tr>
    <tr><th>Order number</th><td class='value-right'>{_h(details['order'])}</td></tr>
    <tr class='h8'><th>Model number</th><td class='value-right value-large'>{_h(details['model'])}</td></tr>
    <tr class='h8'><th>Article</th><td class='value-right value-large'>{_h(details['article'])}</td></tr>
    <tr class='h8'><th>Color</th><td class='value-right'>{_h(pkg.color)}</td></tr>
    <tr class='h10'><th>Product</th><td>{_h(details['product'])}</td></tr>
    <tr class='h12'><th>Fabric</th><td>{_h(details['fabric'])}</td></tr>
    <tr class='h8'><th>Batch</th><td class='value-right'>{batches}</td></tr>
    <tr class='h22'><th>Size</th><td>{_size_breakdown_html(pkg)}</td></tr>
    <tr><th>Weight</th><td class='value-right'>{_h(weight)}</td></tr>
  </table>
  <section class='scan-panel'>
    <div class='qr'><img src='{qr}' alt='Package QR'></div>
    <div class='variant-wrap'><div class='variant-caption'>VARIANT</div>{picture}</div>
    <div class='package-code'><small>SCAN PACKAGE QR</small><b>{_h(pkg.package_no)}</b><span>{_h(pkg.barcode)}</span></div>
  </section>
</article>"""


def _ensure_package_qr_url(db: DbSession, pkg: Package) -> str:
    qr_rel = (pkg.qr_code_url or "").strip()
    qr_exists = False
    if qr_rel.startswith("/storage/barcodes/"):
        fname = qr_rel.split("/storage/barcodes/", 1)[1]
        qr_exists = os.path.isfile(os.path.join(settings.BARCODE_STORAGE_DIR, fname))
    elif qr_rel:
        qr_exists = True
    if qr_exists:
        return qr_rel
    payload = f"PACKAGE:{pkg.package_no}|{pkg.barcode}"
    qr_rel = save_qr_image(payload, f"package_qr_{pkg.package_no}")
    pkg.qr_code_url = qr_rel
    db.add(pkg)
    return qr_rel


def _package_lookup_candidates(raw_code: str) -> list[str]:
    code = (raw_code or "").strip()
    if not code:
        return []

    candidates: list[str] = [code]
    if "|" in code:
        candidates.extend([part.strip() for part in code.split("|") if part.strip()])
    if code.upper().startswith("PACKAGE:"):
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


def _batch_allocations_html(db: DbSession, pkg: Package) -> str:
    rows = [
        (int(alloc.production_batch_id), int(alloc.quantity or 0))
        for alloc in (pkg.batch_allocations or [])
    ]
    if not rows and pkg.production_batch_id:
        rows = [(int(pkg.production_batch_id), int(pkg.total_quantity or 0))]
    if not rows:
        return ""

    parts = []
    for batch_id, _quantity in rows:
        batch = db.get(ProductionBatch, batch_id)
        if batch:
            label = batch.batch_no
            if batch.name:
                label = f"{label} - {batch.name}"
        else:
            label = f"Batch #{batch_id}"
        parts.append(_h(label))
    return "<br>".join(parts)


@router.get("")
def list_packages(db: DbSession, current: CurrentUser,
                  status: str | None = None, production_order_id: int | None = None,
                  created_from: date | None = None, created_to: date | None = None,
                  page: int = 1, page_size: int = 50, include_total: bool = False,
                  packaging_department_code: str | None = None):
    department_code = packaging_department_scope(current, packaging_department_code)
    qry = db.query(Package).filter(Package.packaging_department_code == department_code)
    if status: qry = qry.filter(Package.status == status)
    if production_order_id: qry = qry.filter(Package.production_order_id == production_order_id)
    start, end = date_filter_bounds(created_from, created_to)
    if start: qry = qry.filter(Package.created_at >= start)
    if end: qry = qry.filter(Package.created_at <= end)
    total = qry.count() if include_total else 0
    safe_page = max(1, page)
    safe_size = max(1, min(page_size, 500))
    rows = qry.order_by(Package.id.desc()).offset((safe_page - 1) * safe_size).limit(safe_size).all()
    po_ids = {int(p.production_order_id) for p in rows if p.production_order_id}
    so_ids = {int(p.sales_order_id) for p in rows if p.sales_order_id}
    production_by_id = {
        int(po.id): po
        for po in db.query(ProductionOrder).filter(ProductionOrder.id.in_(po_ids)).all()
    } if po_ids else {}
    sales_by_id = {
        int(so.id): so
        for so in db.query(SalesOrder).filter(SalesOrder.id.in_(so_ids)).all()
    } if so_ids else {}
    customer_ids = {int(so.customer_id) for so in sales_by_id.values() if so.customer_id}
    customer_by_id = {
        int(customer.id): customer
        for customer in db.query(Customer).filter(Customer.id.in_(customer_ids)).all()
    } if customer_ids else {}

    out = []
    for p in rows:
        qr_url = _ensure_package_qr_url(db, p)
        row = _package_out_payload(db, p)
        row["qr_code_url"] = qr_url
        po = production_by_id.get(int(p.production_order_id or 0))
        so = sales_by_id.get(int(p.sales_order_id or 0))
        customer = customer_by_id.get(int(so.customer_id or 0)) if so else None
        row["production_no"] = po.production_no if po else None
        row["sales_order_no"] = so.order_no if so else None
        row["order_no"] = so.order_no if so else (po.order_no if po else None)
        row["customer_name"] = customer.name if customer else None
        row["order_type"] = so.order_type if so else (po.production_type if po else None)
        out.append(row)
    db.commit()
    if include_total:
        return {"rows": out, "total": total, "page": safe_page, "page_size": safe_size}
    return out


@router.post("", response_model=PackageOut, status_code=201)
def create_pkg(
    payload: PackageIn,
    db: DbSession,
    current: User = Depends(require_permissions("packaging.packages", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    department_code = packaging_department_for_order(
        db, payload.production_order_id, payload.production_batch_id
    )
    packaging_department_scope(current, department_code)
    fingerprint_payload = payload.model_dump(mode="json")
    replay = replay_idempotent_response(db, scope="packages.create", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay
    pkg = create_package(
        db,
        production_order_id=payload.production_order_id,
        production_batch_id=payload.production_batch_id,
        model_id=payload.model_id,
        color=payload.color,
        items=[i.model_dump() for i in payload.items],
        sales_order_id=payload.sales_order_id,
        brand_id=payload.brand_id,
        collection_id=payload.collection_id,
        package_type=payload.package_type,
        capacity=payload.capacity,
        weight_kg=payload.weight_kg,
        batch_allocations=[a.model_dump() for a in payload.batch_allocations],
        warehouse_id=payload.warehouse_id,
        override_capacity=payload.override_capacity,
        is_admin=is_admin(current),
        user_id=current.id,
        notes=payload.notes,
        packaging_department_code=department_code,
    )
    log_action(db, current, "create", "Package", pkg.id, new_value={"package_no": pkg.package_no})
    response = _package_out_payload(db, pkg)
    store_idempotent_response(
        db,
        scope="packages.create",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
        status_code=201,
    )
    db.commit(); db.refresh(pkg)
    return response


@router.post("/bulk")
def create_pkg_bulk(
    payload: PackageBulkIn,
    db: DbSession,
    current: User = Depends(require_permissions("packaging.packages", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    department_code = packaging_department_for_order(
        db, payload.production_order_id, payload.production_batch_id
    )
    packaging_department_scope(current, department_code)
    fingerprint_payload = payload.model_dump(mode="json")
    replay = replay_idempotent_response(db, scope="packages.bulk-create", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay
    pkgs = create_packages_bulk(
        db,
        count=payload.count,
        production_order_id=payload.production_order_id,
        production_batch_id=payload.production_batch_id,
        model_id=payload.model_id,
        color=payload.color,
        items=[i.model_dump() for i in payload.items],
        sales_order_id=payload.sales_order_id,
        brand_id=payload.brand_id,
        collection_id=payload.collection_id,
        package_type=payload.package_type,
        capacity=payload.capacity,
        weight_kg=payload.weight_kg,
        weight_kg_values=payload.weight_kg_values,
        batch_allocations=[a.model_dump() for a in payload.batch_allocations],
        warehouse_id=payload.warehouse_id,
        override_capacity=payload.override_capacity,
        is_admin=is_admin(current),
        user_id=current.id,
        notes=payload.notes,
        packaging_department_code=department_code,
    )
    for p in pkgs:
        log_action(db, current, "create", "Package", p.id, new_value={"package_no": p.package_no, "mode": "bulk"})
    response = {
        "count": len(pkgs),
        "package_ids": [p.id for p in pkgs],
        "package_nos": [p.package_no for p in pkgs],
    }
    store_idempotent_response(
        db,
        scope="packages.bulk-create",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
        status_code=201,
    )
    db.commit()
    return response


@router.get("/storage-map")
def storage_map(
    db: DbSession,
    _: CurrentUser,
    model_query: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    include_unplaced: bool = False,
):
    start, end = date_filter_bounds(created_from, created_to)
    ready_statuses = ["packed", "received_in_storage", "reserved"]
    query = (
        db.query(Package, Model, SalesOrder, ProductionOrder)
        .join(Model, Model.id == Package.model_id)
        .outerjoin(SalesOrder, SalesOrder.id == Package.sales_order_id)
        .outerjoin(ProductionOrder, ProductionOrder.id == Package.production_order_id)
        .options(selectinload(Model.images), selectinload(Model.bom).joinedload(ModelBOM.item))
        .filter(Package.status.in_(ready_statuses))
        .order_by(Package.storage_cell.asc(), Package.storage_shelf.asc(), Package.id.desc())
    )
    if include_unplaced:
        query = query.filter(
            or_(
                Package.storage_cell.isnot(None),
                Package.legacy_receipt_id.is_(None),
            )
        )
    else:
        query = query.filter(Package.storage_cell.isnot(None))
    if start:
        query = query.filter(Package.created_at >= start)
    if end:
        query = query.filter(Package.created_at <= end)

    q = (model_query or "").strip().lower()
    placements: list[dict] = []
    matches: list[dict] = []
    by_cell: dict[str, list[dict]] = {}
    for pkg, model, sales_order, production_order in query.all():
        model_code = model.code if model else None
        model_name = model.name if model else None
        fields = [
            model_code or "",
            model_name or "",
            sales_order.order_no if sales_order else "",
            production_order.production_no if production_order else "",
            pkg.package_no or "",
            pkg.barcode or "",
            pkg.storage_cell or "",
            pkg.storage_shelf or "",
        ]
        matched = bool(q) and (
            model_code_contains(model_code, q)
            or any(q in f.lower() for f in fields[1:])
        )
        row = {
            "id": pkg.id,
            "package_no": pkg.package_no,
            "barcode": pkg.barcode,
            "production_order_id": pkg.production_order_id,
            "production_no": production_order.production_no if production_order else None,
            "sales_order_id": pkg.sales_order_id,
            "sales_order_no": sales_order.order_no if sales_order else None,
            "order_no": sales_order.order_no if sales_order else (production_order.order_no if production_order else None),
            "model_id": pkg.model_id,
            "model_code": model_code,
            "model_name": model_name,
            "model_image_url": model_display_image_url(model),
            "color": pkg.color,
            "package_type": pkg.package_type,
            "total_quantity": pkg.total_quantity,
            "status": pkg.status,
            "created_at": pkg.created_at,
            "storage_cell": pkg.storage_cell,
            "storage_shelf": pkg.storage_shelf,
            "storage_placed_at": pkg.storage_placed_at,
            "location": format_storage_location(pkg.storage_cell, pkg.storage_shelf),
            "matched": matched,
        }
        placements.append(row)
        if matched:
            matches.append(row)
        if pkg.storage_cell:
            by_cell.setdefault(pkg.storage_cell, []).append(row)

    if include_unplaced:
        aggregate_query = (
            db.query(
                Package.model_id,
                Package.color,
                Package.package_type,
                Package.status,
                func.count(Package.id),
                func.sum(Package.total_quantity),
                func.min(Package.id),
                func.min(Package.created_at),
            )
            .filter(
                Package.legacy_receipt_id.isnot(None),
                Package.storage_cell.is_(None),
                Package.status.in_(ready_statuses),
            )
            .group_by(
                Package.model_id,
                Package.color,
                Package.package_type,
                Package.status,
            )
        )
        if start:
            aggregate_query = aggregate_query.filter(Package.created_at >= start)
        if end:
            aggregate_query = aggregate_query.filter(Package.created_at <= end)
        aggregate_rows = aggregate_query.all()
        model_ids = {int(row[0]) for row in aggregate_rows if row[0] is not None}
        representative_ids = {int(row[6]) for row in aggregate_rows if row[6] is not None}
        models_by_id = {
            int(model.id): model
            for model in (
                db.query(Model)
                .options(selectinload(Model.images), selectinload(Model.bom).joinedload(ModelBOM.item))
                .filter(Model.id.in_(model_ids))
                .all()
                if model_ids
                else []
            )
        }
        representatives = {
            int(pkg.id): pkg
            for pkg in (
                db.query(Package).filter(Package.id.in_(representative_ids)).all()
                if representative_ids
                else []
            )
        }
        for (
            model_id,
            color,
            package_type,
            status,
            package_count,
            total_quantity,
            representative_id,
            created_at,
        ) in aggregate_rows:
            model = models_by_id.get(int(model_id)) if model_id is not None else None
            representative = representatives.get(int(representative_id))
            model_code = model.code if model else None
            model_name = model.name if model else None
            fields = [
                model_code or "",
                model_name or "",
                representative.package_no if representative else "",
                representative.barcode if representative else "",
                color or "",
            ]
            matched = bool(q) and any(q in field.lower() for field in fields)
            row = {
                "id": representative.id if representative else int(representative_id),
                "package_no": representative.package_no if representative else "",
                "barcode": representative.barcode if representative else None,
                "production_order_id": None,
                "production_no": None,
                "sales_order_id": None,
                "sales_order_no": None,
                "order_no": None,
                "model_id": model_id,
                "model_code": model_code,
                "model_name": model_name,
                "model_image_url": model_display_image_url(model),
                "color": color,
                "package_type": package_type,
                "total_quantity": int(total_quantity or 0),
                "package_count": int(package_count or 0),
                "status": status,
                "created_at": created_at,
                "storage_cell": None,
                "storage_shelf": None,
                "storage_placed_at": None,
                "location": "",
                "matched": matched,
                "aggregated": True,
            }
            placements.append(row)
            if matched:
                matches.append(row)

    cells: list[dict] = []
    for zone, size in WAREHOUSE_MAP_LAYOUT:
        for idx in range(1, size + 1):
            code = f"{zone}-{idx:02d}"
            packs = by_cell.get(code, [])
            count = len(packs)
            matched_count = sum(1 for p in packs if p["matched"])
            if count == 0:
                status = "free"
            elif count == 1:
                status = "partial"
            else:
                status = "full"
            cells.append(
                {
                    "code": code,
                    "zone": zone,
                    "count": count,
                    "status": status,
                    "matched_count": matched_count,
                    "package_nos": [p["package_no"] for p in packs],
                    "model_codes": [p["model_code"] for p in packs if p.get("model_code")],
                }
            )

    return {
        "query": model_query or "",
        "summary": {
            "cells_total": len(cells),
            "cells_occupied": sum(1 for c in cells if c["count"] > 0),
            "packages_on_map": sum(
                int(p.get("package_count") or 1)
                for p in placements
                if p.get("storage_cell")
            ),
            "packages_in_storage": sum(int(p.get("package_count") or 1) for p in placements),
            "matched_packages": sum(int(p.get("package_count") or 1) for p in matches),
        },
        "zones": [{"id": zone, "size": size} for zone, size in WAREHOUSE_MAP_LAYOUT],
        "cells": cells,
        "placements": placements,
        "matches": matches,
    }


@router.get("/storage-map/find")
def find_on_storage_map(
    db: DbSession,
    _: CurrentUser,
    q: str,
):
    needle = q.strip()
    if not needle:
        raise HTTPException(400, "q is required")
    like = f"%{needle}%"
    model_code_like = normalized_model_code_pattern(needle)
    rows = (
        db.query(Package, Model)
        .join(Model, Model.id == Package.model_id)
        .filter(
            Package.storage_cell.isnot(None),
            Package.status.in_(["packed", "received_in_storage", "reserved"]),
            or_(
                normalized_model_code_column(Model.code).ilike(model_code_like),
                Model.name.ilike(like),
                Package.package_no.ilike(like),
                Package.barcode.ilike(like),
            ),
        )
        .order_by(Package.storage_cell.asc(), Package.storage_shelf.asc(), Package.id.desc())
        .all()
    )
    return [
        {
            "id": pkg.id,
            "package_no": pkg.package_no,
            "barcode": pkg.barcode,
            "model_id": pkg.model_id,
            "model_code": model.code if model else None,
            "model_name": model.name if model else None,
            "color": pkg.color,
            "total_quantity": pkg.total_quantity,
            "status": pkg.status,
            "storage_cell": pkg.storage_cell,
            "storage_shelf": pkg.storage_shelf,
            "location": format_storage_location(pkg.storage_cell, pkg.storage_shelf),
        }
        for pkg, model in rows
    ]


@router.get("/change-requests", response_model=list[PackageChangeRequestOut])
def list_package_change_requests(
    db: DbSession,
    current: CurrentUser,
    status: str | None = "pending",
    package_id: int | None = None,
    packaging_department_code: str | None = None,
):
    department_code = packaging_department_scope(current, packaging_department_code)
    qry = db.query(PackageChangeRequest).join(Package, Package.id == PackageChangeRequest.package_id).filter(
        Package.packaging_department_code == department_code
    )
    if status and status != "all":
        qry = qry.filter(PackageChangeRequest.status == status)
    if package_id is not None:
        qry = qry.filter(PackageChangeRequest.package_id == package_id)
    return qry.order_by(PackageChangeRequest.id.desc()).limit(500).all()


@router.post("/{pid}/change-requests", response_model=PackageChangeRequestOut, status_code=201)
def request_package_change(
    pid: int,
    payload: PackageChangeRequestIn,
    db: DbSession,
    current: User = Depends(require_permissions("packaging.packages", "storage.packages", "*")),
):
    p = db.get(Package, pid)
    if not p:
        raise HTTPException(404, "Package not found")
    require_package_access(current, p)
    payload_dict = payload.payload.model_dump(exclude_unset=True) if payload.payload else None
    req = create_package_change_request(
        db,
        pkg=p,
        request_type=payload.request_type,
        payload=payload_dict,
        reason=payload.reason,
        user_id=current.id,
    )
    log_action(
        db,
        current,
        f"request_package_{payload.request_type}",
        "PackageChangeRequest",
        req.id,
        old_value=req.before_json,
        new_value=req.payload_json or {"request_type": payload.request_type, "package_no": req.package_no},
    )
    db.commit()
    db.refresh(req)
    return req


@router.post("/change-requests/{request_id}/approve", response_model=PackageChangeRequestOut)
def approve_package_change(
    request_id: int,
    db: DbSession,
    payload: PackageChangeDecisionIn | None = None,
    current: User = Depends(require_permissions("management.approve", "*")),
):
    req = db.get(PackageChangeRequest, request_id)
    if not req:
        raise HTTPException(404, "Package change request not found")
    package = db.get(Package, req.package_id)
    if package:
        require_package_access(current, package)
    old_value = {"status": req.status, "package_no": req.package_no, "request_type": req.request_type}
    approve_package_change_request(db, req, user_id=current.id, notes=payload.notes if payload else None)
    log_action(
        db,
        current,
        f"approve_package_{req.request_type}",
        "PackageChangeRequest",
        req.id,
        old_value=old_value,
        new_value={
            "status": req.status,
            "package_no": req.package_no,
            "request_type": req.request_type,
            "payload": req.payload_json,
        },
    )
    db.commit()
    db.refresh(req)
    return req


@router.post("/change-requests/{request_id}/reject", response_model=PackageChangeRequestOut)
def reject_package_change(
    request_id: int,
    db: DbSession,
    payload: PackageChangeDecisionIn | None = None,
    current: User = Depends(require_permissions("management.approve", "*")),
):
    req = db.get(PackageChangeRequest, request_id)
    if not req:
        raise HTTPException(404, "Package change request not found")
    package = db.get(Package, req.package_id)
    if package:
        require_package_access(current, package)
    old_value = {"status": req.status, "package_no": req.package_no, "request_type": req.request_type}
    reject_package_change_request(db, req, user_id=current.id, notes=payload.notes if payload else None)
    log_action(
        db,
        current,
        f"reject_package_{req.request_type}",
        "PackageChangeRequest",
        req.id,
        old_value=old_value,
        new_value={
            "status": req.status,
            "package_no": req.package_no,
            "request_type": req.request_type,
            "notes": req.decision_notes,
        },
    )
    db.commit()
    db.refresh(req)
    return req


@router.get("/receiving-queue", response_model=list[PackageDetail])
def receiving_queue(
    db: DbSession,
    _: User = Depends(require_permissions("storage.packages", "*")),
):
    return [_package_detail_payload(db, pkg) for pkg in _receiving_queue_packages(db)]


@router.post("/receiving-queue/scan", response_model=PackageDetail)
def scan_into_receiving_queue(
    payload: PackageReceivingQueueScanIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.packages", "*")),
):
    raw_code = str(payload.code or "").strip()
    if not raw_code:
        raise HTTPException(400, "Package barcode is required")

    found = _package_for_receiving_scan(db, raw_code)
    if not found:
        raise HTTPException(404, "Package not found")
    pkg = (
        db.query(Package)
        .filter(Package.id == found.id)
        .with_for_update()
        .first()
    )
    if not pkg:
        raise HTTPException(404, "Package not found")
    if pkg.status != "packed":
        raise HTTPException(
            409,
            f"Package {pkg.package_no} is already in status '{pkg.status}' and cannot be scanned for receiving.",
        )

    latest_event = _latest_receiving_queue_event(db, int(pkg.id))
    if latest_event and latest_event.scan_type == "queued_storage":
        raise HTTPException(409, f"Package {pkg.package_no} is already scanned and waiting for receiving.")

    db.add(
        PackageScanLog(
            package_id=pkg.id,
            scanned_by=current.id,
            scan_type="queued_storage",
        )
    )
    log_action(
        db,
        current,
        "scan_receiving_queue",
        "Package",
        pkg.id,
        new_value={"package_no": pkg.package_no},
    )
    db.commit()
    db.refresh(pkg)
    return _package_detail_payload(db, pkg)


@router.post("/receiving-queue/remove")
def remove_from_receiving_queue(
    payload: PackageReceivingQueueRemoveIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.packages", "*")),
):
    requested_ids = {int(package_id) for package_id in payload.package_ids if int(package_id or 0) > 0}
    if not requested_ids:
        return {"count": 0, "packages": [_package_detail_payload(db, pkg) for pkg in _receiving_queue_packages(db)]}

    active_by_id = {int(pkg.id): pkg for pkg in _receiving_queue_packages(db)}
    removed = 0
    for package_id in sorted(requested_ids):
        pkg = active_by_id.get(package_id)
        if not pkg:
            continue
        db.add(
            PackageScanLog(
                package_id=pkg.id,
                scanned_by=current.id,
                scan_type="removed_storage_queue",
            )
        )
        log_action(
            db,
            current,
            "remove_receiving_queue",
            "Package",
            pkg.id,
            old_value={"package_no": pkg.package_no, "queued": True},
            new_value={"queued": False},
        )
        removed += 1
    db.commit()
    return {
        "count": removed,
        "packages": [_package_detail_payload(db, pkg) for pkg in _receiving_queue_packages(db)],
    }


@router.post("/batch/receive-storage")
def api_batch_receive_storage(
    payload: PackageBatchReceiveStorageIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.packages", "*")),
):
    package_ids = []
    seen: set[int] = set()
    for raw_id in payload.package_ids:
        package_id = int(raw_id or 0)
        if package_id > 0 and package_id not in seen:
            seen.add(package_id)
            package_ids.append(package_id)
    if not package_ids:
        raise HTTPException(400, "package_ids is required")

    packages = db.query(Package).filter(Package.id.in_(package_ids)).all()
    packages_by_id = {int(pkg.id): pkg for pkg in packages}
    missing = [package_id for package_id in package_ids if package_id not in packages_by_id]
    if missing:
        raise HTTPException(404, f"Package not found: {missing[0]}")

    updated: list[dict] = []
    for package_id in package_ids:
        pkg = packages_by_id[package_id]
        receive_at_storage(
            db,
            pkg,
            payload.warehouse_id,
            current.id,
            storage_cell=payload.storage_cell,
            storage_shelf=payload.storage_shelf,
        )
        log_action(
            db,
            current,
            "receive_storage",
            "Package",
            pkg.id,
            new_value={"storage_cell": pkg.storage_cell, "storage_shelf": pkg.storage_shelf, "mode": "batch"},
        )
        updated.append(_package_detail_payload(db, pkg))

    db.commit()
    for pkg in packages:
        db.refresh(pkg)
    return {
        "count": len(updated),
        "packages": updated,
    }


@router.post("/batch/place-on-map")
def api_batch_place_on_map(
    payload: PackageBatchStoragePlacementIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.packages", "storage.shipment", "*")),
):
    package_ids = []
    seen: set[int] = set()
    for raw_id in payload.package_ids:
        package_id = int(raw_id or 0)
        if package_id > 0 and package_id not in seen:
            seen.add(package_id)
            package_ids.append(package_id)
    if not package_ids:
        raise HTTPException(400, "package_ids is required")

    packages = db.query(Package).filter(Package.id.in_(package_ids)).all()
    packages_by_id = {int(pkg.id): pkg for pkg in packages}
    missing = [package_id for package_id in package_ids if package_id not in packages_by_id]
    if missing:
        raise HTTPException(404, f"Package not found: {missing[0]}")

    updated: list[dict] = []
    for package_id in package_ids:
        pkg = packages_by_id[package_id]
        place_on_storage_map(
            db,
            pkg,
            storage_cell=payload.storage_cell,
            storage_shelf=payload.storage_shelf,
            user_id=current.id,
        )
        log_action(
            db,
            current,
            "place_storage_map",
            "Package",
            pkg.id,
            new_value={"storage_cell": pkg.storage_cell, "storage_shelf": pkg.storage_shelf, "mode": "batch"},
        )
        updated.append(_package_detail_payload(db, pkg))

    db.commit()
    for pkg in packages:
        db.refresh(pkg)
    return {
        "count": len(updated),
        "packages": updated,
    }


@router.get("/{pid}", response_model=PackageDetail)
def get_pkg(pid: int, db: DbSession, current: CurrentUser):
    p = db.get(Package, pid)
    if not p: raise HTTPException(404, "Package not found")
    require_package_access(current, p)
    return _package_detail_payload(db, p)


@router.get("/barcode/{code}", response_model=PackageDetail)
def get_pkg_by_barcode(code: str, db: DbSession, current: CurrentUser):
    for candidate in _package_lookup_candidates(code):
        p = db.query(Package).filter((Package.barcode == candidate) | (Package.package_no == candidate)).first()
        if p:
            require_package_access(current, p)
            return _package_detail_payload(db, p)
    raise HTTPException(404, "Package not found")


@router.post("/{pid}/receive-storage", response_model=PackageDetail)
def api_receive(
    pid: int,
    db: DbSession,
    payload: PackageReceiveStorageIn | None = None,
    warehouse_id: int | None = None,
    current: User = Depends(require_permissions("storage.packages", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    fingerprint_payload = {
        "package_id": pid,
        "warehouse_id": warehouse_id,
        "payload": payload.model_dump(mode="json") if payload else None,
    }
    replay = replay_idempotent_response(db, scope="packages.receive-storage", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay
    p = db.get(Package, pid)
    if not p: raise HTTPException(404, "Package not found")
    selected_warehouse_id = warehouse_id
    if payload and payload.warehouse_id is not None:
        selected_warehouse_id = payload.warehouse_id
    receive_at_storage(
        db,
        p,
        selected_warehouse_id,
        current.id,
        storage_cell=payload.storage_cell if payload else None,
        storage_shelf=payload.storage_shelf if payload else None,
    )
    log_action(db, current, "receive_storage", "Package", p.id)
    response = _package_detail_payload(db, p)
    store_idempotent_response(
        db,
        scope="packages.receive-storage",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
    )
    db.commit(); db.refresh(p)
    return response


@router.post("/{pid}/place-on-map", response_model=PackageDetail)
def api_place_on_map(
    pid: int,
    payload: PackageStoragePlacementIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.packages", "storage.shipment", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    fingerprint_payload = {"package_id": pid, **payload.model_dump(mode="json")}
    replay = replay_idempotent_response(db, scope="packages.place-on-map", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay
    p = db.get(Package, pid)
    if not p:
        raise HTTPException(404, "Package not found")
    place_on_storage_map(
        db,
        p,
        storage_cell=payload.storage_cell,
        storage_shelf=payload.storage_shelf,
        user_id=current.id,
    )
    log_action(
        db,
        current,
        "place_storage_map",
        "Package",
        p.id,
        new_value={"storage_cell": p.storage_cell, "storage_shelf": p.storage_shelf},
    )
    response = _package_detail_payload(db, p)
    store_idempotent_response(
        db,
        scope="packages.place-on-map",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
    )
    db.commit(); db.refresh(p)
    return response


@router.post("/{pid}/reserve", response_model=PackageDetail)
def api_reserve(
    pid: int,
    db: DbSession,
    current: User = Depends(require_permissions("sales.orders", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    fingerprint_payload = {"package_id": pid}
    replay = replay_idempotent_response(db, scope="packages.reserve", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay
    p = db.get(Package, pid)
    if not p: raise HTTPException(404, "Package not found")
    reserve_package(db, p, current.id)
    log_action(db, current, "reserve", "Package", p.id)
    response = _package_detail_payload(db, p)
    store_idempotent_response(
        db,
        scope="packages.reserve",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
    )
    db.commit(); db.refresh(p)
    return response


@router.post("/{pid}/ship", response_model=PackageDetail)
def api_ship(
    pid: int,
    db: DbSession,
    current: User = Depends(require_permissions("storage.shipment", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    fingerprint_payload = {"package_id": pid}
    replay = replay_idempotent_response(db, scope="packages.ship", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay
    p = db.get(Package, pid)
    if not p: raise HTTPException(404, "Package not found")
    ship_package(db, p, current.id)
    log_action(db, current, "ship", "Package", p.id)
    response = _package_detail_payload(db, p)
    store_idempotent_response(
        db,
        scope="packages.ship",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
    )
    db.commit(); db.refresh(p)
    return response


@router.post("/{pid}/mark-delivered", response_model=PackageDetail)
def api_delivered(
    pid: int,
    db: DbSession,
    current: User = Depends(require_permissions("storage.shipment", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    fingerprint_payload = {"package_id": pid}
    replay = replay_idempotent_response(db, scope="packages.mark-delivered", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay
    p = db.get(Package, pid)
    if not p: raise HTTPException(404, "Package not found")
    mark_delivered(db, p, current.id)
    log_action(db, current, "delivered", "Package", p.id)
    response = _package_detail_payload(db, p)
    store_idempotent_response(
        db,
        scope="packages.mark-delivered",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
    )
    db.commit(); db.refresh(p)
    return response


@router.post("/{pid}/mark-damaged", response_model=PackageDetail)
def api_damaged(
    pid: int,
    db: DbSession,
    current: User = Depends(require_permissions("storage.packages", "storage.shipment", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    fingerprint_payload = {"package_id": pid}
    replay = replay_idempotent_response(db, scope="packages.mark-damaged", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay
    p = db.get(Package, pid)
    if not p: raise HTTPException(404, "Package not found")
    mark_damaged(db, p, current.id)
    log_action(db, current, "damaged", "Package", p.id)
    response = _package_detail_payload(db, p)
    store_idempotent_response(
        db,
        scope="packages.mark-damaged",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
    )
    db.commit(); db.refresh(p)
    return response


@router.get("/{pid}/history")
def history(pid: int, db: DbSession, current: CurrentUser):
    p = db.get(Package, pid)
    if not p: raise HTTPException(404, "Package not found")
    require_package_access(current, p)
    return [
        {"id": s.id, "scan_type": s.scan_type, "scanned_by": s.scanned_by, "scanned_at": s.scanned_at, "location": s.location}
        for s in p.scan_logs
    ]


@router.get("/{pid}/label", response_class=HTMLResponse)
def label(pid: int, db: DbSession, current: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS))):
    p = db.get(Package, pid)
    if not p: raise HTTPException(404, "Package not found")
    require_package_access(current, p)
    package_no = _h(p.package_no)
    card = _package_label_card_html(db, p)
    cards = card * 4
    return f"""<!doctype html>
<html><head><meta charset='utf-8'><title>Package Label {package_no}</title>
<style>
@page{{size:A4 portrait;margin:5mm}}
{_PACKAGE_LABEL_CSS}
.sheet{{display:grid;grid-template-columns:repeat(2,98.5mm);grid-template-rows:repeat(2,142mm);gap:3mm;justify-content:center;align-content:start}}
</style></head>
<body>
<div class='sheet'>{cards}</div>
<button class='print-button' onclick='window.print()'>Print</button>
</body></html>"""


@router.get("/label-sheet/by-ids", response_class=HTMLResponse)
def label_sheet(ids: str, db: DbSession, current: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS))):
    raw_ids = [s.strip() for s in (ids or "").split(",") if s.strip()]
    try:
        parsed_ids = [int(v) for v in raw_ids]
    except ValueError:
        raise HTTPException(400, "ids must be comma-separated integers")
    if not parsed_ids:
        raise HTTPException(400, "Provide at least one package id")
    rows = (
        db.query(Package)
        .options(selectinload(Package.items))
        .filter(Package.id.in_(parsed_ids))
        .order_by(Package.id.asc())
        .all()
    )
    if not rows:
        raise HTTPException(404, "No packages found")
    for package in rows:
        require_package_access(current, package)

    cards = [_package_label_card_html(db, p) for p in rows]
    return f"""<!doctype html>
<html><head><meta charset='utf-8'><title>Package Label Sheet</title>
<style>
@page{{size:A4 portrait;margin:5mm}}
{_PACKAGE_LABEL_CSS}
.sheet{{display:grid;grid-template-columns:repeat(2,98.5mm);grid-template-rows:repeat(2,142mm);gap:3mm;justify-content:center;align-content:start}}
</style></head>
<body>
<div class='sheet'>{''.join(cards)}</div>
<button class='print-button' onclick='window.print()'>Print</button>
</body></html>"""
