from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import selectinload
import base64
from functools import lru_cache
from html import escape
import os
from pathlib import Path

from app.core.config import settings
from app.core.deps import DbSession, CurrentUser, PRODUCTION_READ_PERMISSIONS, require_permissions, user_permissions
from app.core.model_search import normalized_model_code_column, normalized_model_code_pattern
from app.models import (
    Bundle,
    BundleScanLog,
    CuttingRecord,
    Department,
    Model,
    ModelBOM,
    ProductionOrder,
    ProductionBatch,
    SalesOrder,
    SewingAssignment,
    SewingFlow,
    User,
    WorkOrder,
    public_production_order_no,
)
from app.schemas.tracking import BundleIn, BundleOut, BundleDetail
from app.services.bundles import (
    create_bundle,
    send_to_printing,
    receive_at_printing,
    send_to_sewing,
    receive_at_sewing,
    bundle_qr_payload,
    format_batch_passport,
    resolve_sewing_factory_code,
)
from app.services.barcode import save_qr_image
from app.services.label_images import material_label_image_src
from app.services.model_images import material_preview_image_url
from app.services.audit import log_action
from app.services.sewing_scope import require_sewing_flow_access, sewing_line_factory_scope

router = APIRouter(prefix="/bundles", tags=["bundles"])

SEWING_RECEIVE_DEPARTMENT_CODES = ("SEW", "MIL", "BST", "ECO")


class SewingManualReceiveIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    production_order_id: int
    model_id: int | None = None
    factory_code: str | None = None


class SewingBatchAcceptIn(BaseModel):
    sewing_flow_id: int


def _scope_to_cutting_department(qry, db: DbSession, current, cutting_department_code: str | None):
    from app.services.factory_scope import cutting_department_scope
    scope = cutting_department_scope(current, cutting_department_code)
    eco_order_ids = (
        db.query(WorkOrder.production_order_id)
        .join(Department, Department.id == WorkOrder.department_id)
        .filter(WorkOrder.operation == "cutting", Department.code == "ECT")
        .distinct()
    )
    if scope == "ECT":
        return qry.filter(Bundle.production_order_id.in_(eco_order_ids))
    return qry.filter(Bundle.production_order_id.notin_(eco_order_ids))


def _material_images_by_model_id(db: DbSession, model_ids) -> dict[int, str | None]:
    ids = {int(model_id) for model_id in model_ids if model_id}
    if not ids:
        return {}
    models = (
        db.query(Model)
        .options(
            selectinload(Model.images),
            selectinload(Model.bom).joinedload(ModelBOM.item),
            selectinload(Model.bom).joinedload(ModelBOM.stock_batch),
        )
        .filter(Model.id.in_(ids))
        .all()
    )
    return {int(model.id): material_preview_image_url(model) for model in models}


def _h(value) -> str:
    return escape(str(value or ""), quote=True)


@lru_cache(maxsize=1)
def _unicode_label_font_css() -> str:
    font_candidates = (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    )
    for font_path in font_candidates:
        if font_path.is_file():
            encoded = base64.b64encode(font_path.read_bytes()).decode("ascii")
            return (
                "@font-face{font-family:'Milana Label Unicode';"
                "src:url(data:font/ttf;base64," + encoded + ") format('truetype');"
                "font-weight:100 900;font-style:normal;font-display:block;}"
            )
    return ""


def _bundle_label_head(title: str, page_css: str) -> str:
    return (
        "<head><meta charset='utf-8'>"
        f"<title>{title}</title><style>{_unicode_label_font_css()}"
        f"{page_css}</style></head>"
    )


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
    if bundle.cutting_record_id:
        row["cutting_record_id"] = int(bundle.cutting_record_id)
        row["cutting_inventory_adjustable"] = True
        return row
    cutting_record_ids = (
        db.query(CuttingRecord.id)
        .join(WorkOrder, WorkOrder.id == CuttingRecord.work_order_id)
        .filter(
            WorkOrder.production_order_id == bundle.production_order_id,
            WorkOrder.operation == "cutting",
        )
    )
    if bundle.production_batch_id is None:
        cutting_record_ids = cutting_record_ids.filter(CuttingRecord.production_batch_id.is_(None))
    else:
        cutting_record_ids = cutting_record_ids.filter(CuttingRecord.production_batch_id == bundle.production_batch_id)
    scoped_record_ids = [int(row_id) for (row_id,) in cutting_record_ids.order_by(CuttingRecord.id.asc()).all()]
    row["cutting_record_id"] = scoped_record_ids[0] if len(scoped_record_ids) == 1 else None
    row["cutting_inventory_adjustable"] = len(scoped_record_ids) == 1
    return row


def _bundle_detail_payload(db: DbSession, bundle: Bundle) -> dict:
    row = BundleDetail.model_validate(bundle).model_dump()
    row.update(_bundle_payload(db, bundle))
    return row


def _label_context(db: DbSession, b: Bundle) -> dict:
    row = _bundle_payload(db, b)
    model = (
        db.query(Model)
        .options(selectinload(Model.images), selectinload(Model.bom).joinedload(ModelBOM.item))
        .filter(Model.id == b.model_id)
        .first()
        if b.model_id
        else None
    )
    return {
        "bundle_no": _h(b.bundle_no),
        "order_no": _h(row.get("order_no") or row.get("production_no") or b.production_order_id),
        "batch_label": _h(row.get("batch_label")),
        "tracking_passport_no": _h(row.get("tracking_passport_no")),
        "model_code": _h(row.get("model_code") or b.model_id),
        "material_image_src": _h(material_label_image_src(model)),
        "color": _h(b.color),
        "size": _h(b.size),
        "quantity": _h(b.quantity),
        "barcode": _h(b.barcode),
    }


def _bundle_label_card(ctx: dict, qr: str) -> str:
    picture = (
        f"<div class='material-picture'><img src='{ctx['material_image_src']}' alt='Material picture'/></div>"
        if ctx.get("material_image_src")
        else ""
    )
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
              <div class='label-visuals'>{picture}<div class='qr'><img src='{qr}' alt='QR'/></div></div>
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


def _sewing_receive_department_ids(db: DbSession) -> list[int]:
    return [
        int(id_)
        for (id_,) in db.query(Department.id)
        .filter(Department.code.in_(SEWING_RECEIVE_DEPARTMENT_CODES))
        .all()
    ]


def _sewing_receive_eligible_filter(db: DbSession):
    department_ids = _sewing_receive_department_ids(db)
    direct_to_sewing = Bundle.status == "sent_to_sewing"
    if not department_ids:
        return direct_to_sewing
    return or_(
        direct_to_sewing,
        and_(Bundle.status == "created", Bundle.next_department_id.in_(department_ids)),
    )


@router.get("")
def list_bundles(db: DbSession, current: CurrentUser,
                 production_order_id: int | None = None, status: str | None = None,
                 production_batch_id: int | None = None,
                 model_id: int | None = None, page: int = 1, page_size: int = 50,
                 include_total: bool = False,
                 cutting_department_code: str | None = None):
    qry = db.query(Bundle, ProductionOrder.production_no, SalesOrder.order_no, Model.code).outerjoin(
        ProductionOrder, Bundle.production_order_id == ProductionOrder.id
    ).outerjoin(
        SalesOrder, SalesOrder.id == ProductionOrder.sales_order_id
    ).outerjoin(
        Model, Bundle.model_id == Model.id
    )
    qry = _scope_to_cutting_department(qry, db, current, cutting_department_code)
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


@router.get("/cutting-inventory")
def cutting_inventory(
    db: DbSession,
    current: User = Depends(require_permissions("cutting.bundles", "cutting.records", "planning.production", "*")),
    q: str | None = None,
    page: int = 1,
    page_size: int = 50,
    cutting_department_code: str | None = None,
):
    received_printing_log = (
        db.query(BundleScanLog.id)
        .filter(
            BundleScanLog.bundle_id == Bundle.id,
            BundleScanLog.scan_type == "received_printing",
        )
        .exists()
    )
    qry = db.query(Bundle, ProductionOrder.production_no, SalesOrder.order_no, Model.code).outerjoin(
        ProductionOrder, Bundle.production_order_id == ProductionOrder.id
    ).outerjoin(
        SalesOrder, SalesOrder.id == ProductionOrder.sales_order_id
    ).outerjoin(
        Model, Bundle.model_id == Model.id
    ).filter(
        or_(
            Bundle.status.in_(("created", "sent_to_printing")),
            and_(Bundle.status == "sent_to_sewing", ~received_printing_log),
        )
    )
    qry = _scope_to_cutting_department(qry, db, current, cutting_department_code)
    search = str(q or "").strip()
    if search:
        like = f"%{search}%"
        model_code_like = normalized_model_code_pattern(search)
        qry = qry.filter(
            or_(
                Bundle.bundle_no.ilike(like),
                Bundle.barcode.ilike(like),
                Bundle.color.ilike(like),
                Bundle.size.ilike(like),
                ProductionOrder.production_no.ilike(like),
                SalesOrder.order_no.ilike(like),
                normalized_model_code_column(Model.code).ilike(model_code_like),
            )
        )

    total = qry.count()
    total_quantity = int(qry.with_entities(func.coalesce(func.sum(Bundle.quantity), 0)).order_by(None).scalar() or 0)
    total_orders = int(qry.with_entities(func.count(func.distinct(Bundle.production_order_id))).order_by(None).scalar() or 0)
    safe_page = max(1, page)
    safe_size = max(1, min(page_size, 2000))
    rows = (
        qry.order_by(
            ProductionOrder.production_no.desc(),
            Bundle.production_order_id.desc(),
            Bundle.production_batch_id.desc(),
            Bundle.id.desc(),
        )
        .offset((safe_page - 1) * safe_size)
        .limit(safe_size)
        .all()
    )
    material_images = _material_images_by_model_id(db, (bundle.model_id for bundle, *_ in rows))
    out: list[dict] = []
    for bundle, production_no, sales_order_no, model_code in rows:
        payload = _bundle_payload(
            db,
            bundle,
            production_no=production_no,
            order_no=sales_order_no or public_production_order_no(production_no),
            model_code=model_code,
        )
        payload["material_image_url"] = material_images.get(int(bundle.model_id))
        out.append(payload)
    return {
        "rows": out,
        "total": total,
        "total_quantity": total_quantity,
        "total_orders": total_orders,
        "page": safe_page,
        "page_size": safe_size,
    }


@router.get("/sewing-receive-options")
def sewing_receive_options(
    db: DbSession,
    current: User = Depends(require_permissions("sewing.bundles", "*")),
    q: str | None = None,
    limit: int = 25,
    factory_code: str | None = None,
):
    factory = sewing_line_factory_scope(current, factory_code)
    qry = db.query(
        Bundle.production_order_id,
        Bundle.model_id,
        ProductionOrder.production_no,
        SalesOrder.order_no,
        Model.code.label("model_code"),
        Model.name.label("model_name"),
        func.count(Bundle.id).label("bundle_count"),
        func.coalesce(func.sum(Bundle.quantity), 0).label("quantity"),
        func.max(Bundle.created_at).label("latest_created_at"),
    ).outerjoin(
        ProductionOrder, Bundle.production_order_id == ProductionOrder.id
    ).outerjoin(
        SalesOrder, SalesOrder.id == ProductionOrder.sales_order_id
    ).outerjoin(
        Model, Bundle.model_id == Model.id
    ).filter(
        _sewing_receive_eligible_filter(db),
        Bundle.sewing_factory_code == factory,
    )
    search = str(q or "").strip()
    if search:
        like = f"%{search}%"
        model_code_like = normalized_model_code_pattern(search)
        qry = qry.filter(
            or_(
                Bundle.bundle_no.ilike(like),
                Bundle.barcode.ilike(like),
                ProductionOrder.production_no.ilike(like),
                SalesOrder.order_no.ilike(like),
                normalized_model_code_column(Model.code).ilike(model_code_like),
                Model.name.ilike(like),
            )
        )

    rows = (
        qry.group_by(
            Bundle.production_order_id,
            Bundle.model_id,
            ProductionOrder.production_no,
            SalesOrder.order_no,
            Model.code,
            Model.name,
        )
        .order_by(func.max(Bundle.created_at).desc())
        .limit(max(1, min(int(limit or 25), 100)))
        .all()
    )
    material_images = _material_images_by_model_id(db, (row.model_id for row in rows))
    return [
        {
            "production_order_id": production_order_id,
            "model_id": model_id,
            "production_no": production_no,
            "order_no": order_no or public_production_order_no(production_no) or production_no,
            "model_code": model_code,
            "model_name": model_name,
            "material_image_url": material_images.get(int(model_id)) if model_id else None,
            "bundle_count": int(bundle_count or 0),
            "quantity": int(quantity or 0),
        }
        for (
            production_order_id,
            model_id,
            production_no,
            order_no,
            model_code,
            model_name,
            bundle_count,
            quantity,
            _latest_created_at,
        ) in rows
    ]


@router.post("/manual-receive-sewing")
def manual_receive_sewing(
    payload: SewingManualReceiveIn,
    db: DbSession,
    current: User = Depends(require_permissions("sewing.bundles", "*")),
):
    factory = sewing_line_factory_scope(current, payload.factory_code)
    qry = db.query(Bundle).filter(
        _sewing_receive_eligible_filter(db),
        Bundle.production_order_id == payload.production_order_id,
        Bundle.sewing_factory_code == factory,
    )
    if payload.model_id is not None:
        qry = qry.filter(Bundle.model_id == payload.model_id)
    bundles = qry.order_by(Bundle.id.asc()).with_for_update().all()
    if not bundles:
        raise HTTPException(404, "No bundles are waiting for sewing receive")

    received_quantity = 0
    received_ids: list[int] = []
    for bundle in bundles:
        receive_at_sewing(db, bundle, current)
        log_action(db, current, "manual_receive_at_sewing", "Bundle", bundle.id)
        received_quantity += int(bundle.quantity or 0)
        received_ids.append(int(bundle.id))
    db.commit()

    return {
        "received_count": len(received_ids),
        "received_quantity": received_quantity,
        "bundle_ids": received_ids,
    }


def _sewing_work_order_for_batch(db: DbSession, batch: ProductionBatch) -> WorkOrder | None:
    qry = db.query(WorkOrder).filter(
        WorkOrder.production_order_id == batch.production_order_id,
        WorkOrder.operation == "sewing",
    )
    scoped = qry.filter(WorkOrder.production_batch_id == batch.id).order_by(WorkOrder.id.asc()).first()
    if scoped:
        return scoped
    return (
        qry.filter(WorkOrder.production_batch_id.is_(None)).order_by(WorkOrder.id.asc()).first()
        or qry.order_by(WorkOrder.id.asc()).first()
    )


def _sewing_batch_payload(db: DbSession, batch: ProductionBatch) -> dict:
    bundles = (
        db.query(Bundle)
        .filter(
            Bundle.production_batch_id == batch.id,
            Bundle.production_order_id == batch.production_order_id,
            Bundle.status != "cancelled",
        )
        .order_by(Bundle.id.asc())
        .all()
    )
    po = db.get(ProductionOrder, batch.production_order_id)
    model = db.get(Model, po.model_id) if po and po.model_id else None
    wo = _sewing_work_order_for_batch(db, batch)
    assignments = []
    if wo:
        assignments = (
            db.query(SewingAssignment, SewingFlow)
            .join(SewingFlow, SewingFlow.id == SewingAssignment.sewing_flow_id)
            .filter(
                SewingAssignment.work_order_id == wo.id,
                SewingAssignment.production_batch_id == batch.id,
                SewingAssignment.status.in_(("planned", "in_progress", "completed")),
            )
            .order_by(SewingAssignment.id.asc())
            .all()
        )
    status_counts: dict[str, int] = {}
    for bundle in bundles:
        status = str(bundle.status or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    batch_meta = _batch_meta(db, batch.production_order_id, batch.id)
    return {
        "production_batch_id": int(batch.id),
        "production_order_id": int(batch.production_order_id),
        "production_no": po.production_no if po else None,
        "order_no": (po.order_no if po else None) or public_production_order_no(po.production_no if po else None),
        "model_code": model.code if model else None,
        **batch_meta,
        "bundle_count": len(bundles),
        "quantity": sum(int(bundle.quantity or 0) for bundle in bundles),
        "status_counts": status_counts,
        "assignment_ids": [int(assignment.id) for assignment, _flow in assignments],
        "assigned_flow_ids": sorted({int(flow.id) for _assignment, flow in assignments}),
        "assigned_flow_names": sorted({str(flow.name or flow.code) for _assignment, flow in assignments}),
    }


@router.get("/sewing-batches/{production_batch_id}")
def get_sewing_batch(
    production_batch_id: int,
    db: DbSession,
    _: User = Depends(require_permissions("sewing.bundles", "*")),
):
    batch = db.get(ProductionBatch, production_batch_id)
    if not batch:
        raise HTTPException(404, "Production batch not found")
    return _sewing_batch_payload(db, batch)


@router.post("/sewing-batches/{production_batch_id}/accept")
def accept_sewing_batch(
    production_batch_id: int,
    payload: SewingBatchAcceptIn,
    db: DbSession,
    current: User = Depends(require_permissions("sewing.bundles", "*")),
):
    batch = (
        db.query(ProductionBatch)
        .filter(ProductionBatch.id == production_batch_id)
        .with_for_update()
        .first()
    )
    if not batch:
        raise HTTPException(404, "Production batch not found")

    flow = db.get(SewingFlow, payload.sewing_flow_id)
    if not flow:
        raise HTTPException(404, "Sewing line not found")
    require_sewing_flow_access(current, flow)
    if not flow.is_active:
        raise HTTPException(400, "Sewing line is inactive")

    bundles = (
        db.query(Bundle)
        .filter(
            Bundle.production_batch_id == batch.id,
            Bundle.production_order_id == batch.production_order_id,
            Bundle.status != "cancelled",
        )
        .order_by(Bundle.id.asc())
        .with_for_update()
        .all()
    )
    if not bundles:
        raise HTTPException(404, "No bundles found for this production batch")

    factory_codes = {resolve_sewing_factory_code(bundle.sewing_factory_code) for bundle in bundles}
    if len(factory_codes) != 1 or factory_codes != {flow.factory_code}:
        raise HTTPException(409, "The selected sewing line belongs to a different sewing factory")

    sewing_department_ids = set(_sewing_receive_department_ids(db))
    blocked = [
        bundle
        for bundle in bundles
        if bundle.status != "received_sewing"
        and bundle.status != "sent_to_sewing"
        and not (bundle.status == "created" and bundle.next_department_id in sewing_department_ids)
    ]
    if blocked:
        statuses = ", ".join(sorted({str(bundle.status) for bundle in blocked}))
        raise HTTPException(
            409,
            f"This batch is not fully ready for sewing acceptance. Blocking bundle status: {statuses}",
        )

    wo = _sewing_work_order_for_batch(db, batch)
    if not wo:
        raise HTTPException(404, "Sewing work order not found for this production batch")

    managed_statuses = ("planned", "in_progress", "completed")
    all_assignments = (
        db.query(SewingAssignment)
        .filter(
            SewingAssignment.work_order_id == wo.id,
            SewingAssignment.status.in_(managed_statuses),
        )
        .with_for_update()
        .all()
    )
    unscoped = [assignment for assignment in all_assignments if assignment.production_batch_id is None]
    if unscoped:
        raise HTTPException(409, "This sewing work order already has an order-level line assignment")

    batch_assignments = [
        assignment
        for assignment in all_assignments
        if int(assignment.production_batch_id or 0) == int(batch.id)
    ]
    has_unreceived_bundles = any(bundle.status != "received_sewing" for bundle in bundles)
    if has_unreceived_bundles and any(assignment.status == "completed" for assignment in batch_assignments):
        raise HTTPException(409, "This batch has a completed sewing assignment and cannot be accepted again")
    assigned_flow_ids = {int(assignment.sewing_flow_id) for assignment in batch_assignments}
    if assigned_flow_ids and assigned_flow_ids != {int(flow.id)}:
        assigned_names = [
            row.name or row.code
            for row in db.query(SewingFlow).filter(SewingFlow.id.in_(assigned_flow_ids)).all()
        ]
        raise HTTPException(409, f"This batch is already assigned to: {', '.join(assigned_names)}")

    if not all_assignments and wo.sewing_flow_id and int(wo.sewing_flow_id) != int(flow.id):
        current_flow = db.get(SewingFlow, wo.sewing_flow_id)
        raise HTTPException(
            409,
            f"This sewing work order is already assigned to {current_flow.name if current_flow else wo.sewing_flow_id}",
        )

    total_quantity = sum(int(bundle.quantity or 0) for bundle in bundles)
    assignment: SewingAssignment
    if batch_assignments:
        assigned_quantity = sum(int(row.quantity or 0) for row in batch_assignments)
        if assigned_quantity != total_quantity:
            can_resize = (
                len(batch_assignments) == 1
                and int(batch_assignments[0].completed_qty or 0) == 0
                and assigned_quantity <= total_quantity
            )
            if not can_resize:
                raise HTTPException(
                    409,
                    f"Existing batch assignment quantity ({assigned_quantity}) does not match bundle quantity ({total_quantity})",
                )
            batch_assignments[0].quantity = total_quantity
        assignment = batch_assignments[0]
    else:
        now = datetime.now(timezone.utc)
        assignment = SewingAssignment(
            work_order_id=wo.id,
            production_batch_id=batch.id,
            sewing_flow_id=flow.id,
            quantity=total_quantity,
            planned_start=now,
            planned_end=batch.deadline,
            actual_start=now,
            status="in_progress",
            notes="Accepted from cutting-sheet batch QR",
            created_by=current.id,
        )
        db.add(assignment)
        db.flush()

    if assignment.status == "planned":
        assignment.status = "in_progress"
    if assignment.actual_start is None:
        assignment.actual_start = datetime.now(timezone.utc)
    if not wo.sewing_flow_id:
        wo.sewing_flow_id = flow.id

    received_ids: list[int] = []
    for bundle in bundles:
        if bundle.status == "received_sewing":
            continue
        receive_at_sewing(db, bundle, current)
        received_ids.append(int(bundle.id))

    log_action(
        db,
        current,
        "accept_sewing_batch_qr",
        "ProductionBatch",
        batch.id,
        new_value={
            "sewing_flow_id": int(flow.id),
            "sewing_assignment_id": int(assignment.id),
            "bundle_ids": [int(bundle.id) for bundle in bundles],
            "received_bundle_ids": received_ids,
            "quantity": total_quantity,
        },
    )
    db.commit()

    result = _sewing_batch_payload(db, batch)
    result.update({
        "sewing_assignment_id": int(assignment.id),
        "sewing_flow_id": int(flow.id),
        "sewing_flow_code": flow.code,
        "sewing_flow_name": flow.name,
        "received_count": len(received_ids),
        "already_accepted": len(received_ids) == 0,
    })
    return result


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


@router.delete("/{bid}", status_code=204)
def delete_own_created_bundle(
    bid: int,
    db: DbSession,
    current: User = Depends(require_permissions("cutting.bundles", "*")),
):
    b = db.query(Bundle).filter(Bundle.id == bid).with_for_update().first()
    if not b:
        raise HTTPException(404, "Bundle not found")

    permissions = set(user_permissions(current))
    if "*" not in permissions and int(b.created_by or 0) != int(current.id):
        raise HTTPException(403, "You can delete only bundles you created")
    if b.status != "created":
        raise HTTPException(409, "Only unprocessed bundles can be deleted")
    if any(str(scan.scan_type or "") != "created" for scan in b.scan_logs):
        raise HTTPException(409, "This bundle already has processing history and cannot be deleted")

    old_value = {
        "bundle_no": b.bundle_no,
        "production_order_id": b.production_order_id,
        "production_batch_id": b.production_batch_id,
        "model_id": b.model_id,
        "color": b.color,
        "size": b.size,
        "quantity": b.quantity,
        "status": b.status,
        "created_by": b.created_by,
    }
    production_order_id = int(b.production_order_id)
    production_batch_id = int(b.production_batch_id) if b.production_batch_id else None
    db.delete(b)
    db.flush()

    cutting_records = (
        db.query(CuttingRecord)
        .join(WorkOrder, WorkOrder.id == CuttingRecord.work_order_id)
        .filter(
            WorkOrder.production_order_id == production_order_id,
            WorkOrder.operation == "cutting",
        )
    )
    if production_batch_id is None:
        cutting_records = cutting_records.filter(CuttingRecord.production_batch_id.is_(None))
    else:
        cutting_records = cutting_records.filter(CuttingRecord.production_batch_id == production_batch_id)
    scoped_records = cutting_records.order_by(CuttingRecord.id.asc()).all()
    if len(scoped_records) == 1:
        remaining = db.query(
            func.count(Bundle.id),
            func.coalesce(func.sum(Bundle.quantity), 0),
        ).filter(Bundle.production_order_id == production_order_id)
        if production_batch_id is None:
            remaining = remaining.filter(Bundle.production_batch_id.is_(None))
        else:
            remaining = remaining.filter(Bundle.production_batch_id == production_batch_id)
        remaining_count, remaining_quantity = remaining.one()
        scoped_records[0].bundle_count = int(remaining_count or 0)
        scoped_records[0].total_bundled_quantity = int(remaining_quantity or 0)

    log_action(db, current, "delete_own_created_bundle", "Bundle", bid, old_value=old_value)
    db.commit()


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
    receive_at_sewing(db, b, current)
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
def bundle_label(bid: int, db: DbSession, _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS))):
    """Returns a printable HTML label."""
    b = db.get(Bundle, bid)
    if not b: raise HTTPException(404, "Bundle not found")
    qr = _qr_data_uri_for_bundle(db, b)
    ctx = _label_context(db, b)
    page_css = "@page{margin:8mm} body{font-family:'Milana Label Unicode','DejaVu Sans',Arial,sans-serif;margin:0;padding:8mm} .label{box-sizing:border-box;break-inside:avoid;page-break-inside:avoid;border:1px solid #000;padding:5mm;width:88mm} .row{display:flex;justify-content:space-between;gap:4mm;font-size:8.5pt;line-height:1.22} .row span{text-align:right;overflow-wrap:anywhere} .label-visuals{display:flex;align-items:center;justify-content:center;gap:4mm;margin-top:2.5mm} .qr img,.material-picture img{display:block;width:25mm;height:25mm;object-fit:contain} .material-picture{box-sizing:border-box;width:27mm;height:27mm;border:1px solid #ddd;padding:1mm;display:flex;align-items:center;justify-content:center} h2{margin:0 0 2mm 0;font-size:12pt;letter-spacing:0}@media print{body{margin:0;padding:0} button{display:none}}"
    return f"""<!doctype html>
<html>{_bundle_label_head(f"Bundle Label {ctx['bundle_no']}", page_css)}
<body>{_bundle_label_card(ctx, qr)}
<button onclick=\"window.print()\">Print</button>
</body></html>"""


@router.get("/label-sheet/by-ids", response_class=HTMLResponse)
def bundle_label_sheet(ids: str, db: DbSession, _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS))):
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

    page_css = """
@page{margin:6mm}
html,body{font-family:'Milana Label Unicode','DejaVu Sans',Arial,sans-serif;margin:0;padding:0}
.sheet{font-size:0}
.label{display:inline-block;vertical-align:top;box-sizing:border-box;width:96mm;min-height:56mm;margin:0 4mm 4mm 0;border:1px solid #000;padding:4mm;font-size:8.5pt;break-inside:avoid;page-break-inside:avoid}
.label:nth-child(2n){margin-right:0}
.row{display:flex;justify-content:space-between;gap:3mm;font-size:8.5pt;line-height:1.18}
.row span{text-align:right;overflow-wrap:anywhere}
.label-visuals{display:flex;align-items:center;justify-content:center;gap:3mm;margin-top:2mm}
.qr img,.material-picture img{display:block;width:23mm;height:23mm;object-fit:contain}
.material-picture{box-sizing:border-box;width:25mm;height:25mm;border:1px solid #ddd;padding:1mm;display:flex;align-items:center;justify-content:center}
h2{margin:0 0 1.5mm 0;font-size:11pt;letter-spacing:0}
@media print{button{display:none} .label{break-inside:avoid;page-break-inside:avoid}}
"""
    return f"""<!doctype html>
<html>{_bundle_label_head("Bundle Label Sheet", page_css)}
<body>
<div class='sheet'>{''.join(cards)}</div>
<button onclick="window.print()" style="margin-top:6mm">Print</button>
</body></html>"""


@router.get("/label-sheet/by-production-order/{production_order_id}", response_class=HTMLResponse)
def bundle_label_sheet_by_production_order(
    production_order_id: int,
    db: DbSession,
    _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS)),
):
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
def bundle_label_sheet_by_batch(
    production_batch_id: int,
    db: DbSession,
    _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS)),
):
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
