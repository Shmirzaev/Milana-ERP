from fastapi import APIRouter, HTTPException, Depends, Query

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models.cutting_passport import CuttingPassport
from app.models import Item, ModelBOM, ProductionOrder, ProductionOrderItem, StockBatch, User, WorkOrder
from app.models.catalog import Model as CatalogModel
from app.schemas.cutting_passport import CuttingPassportIn, CuttingPassportOut
from app.services.audit import log_action
from app.services.model_images import model_display_image_url

router = APIRouter(prefix="/cutting-passports", tags=["cutting_passports"])
_MATERIAL_CATEGORIES = ("fabric", "semi_finished")


def _size_count_from_range(value: str | None) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    if "," in text:
        return len({part.strip() for part in text.split(",") if part.strip()})
    if "-" not in text:
        return 1
    start_text, end_text = [part.strip() for part in text.split("-", 1)]
    try:
        start = float(start_text)
        end = float(end_text)
    except ValueError:
        return 1
    if start >= end:
        return 1
    step = 2 if start.is_integer() and end.is_integer() and end - start >= 2 else 1
    count = 0
    current = start
    while current <= end:
        count += 1
        current += step
    return count


def _compute(p: CuttingPassport) -> dict:
    pieces = p.pieces or 0
    beka_per = float(p.beka_per_piece_kg or 0)
    other_beka_per = float(p.other_beka_per_piece_kg or 0)
    ribana_per = float(p.ribana_per_piece_kg or 0)
    scrap = float(p.scrap_kg or 0)
    layer_weight = float(p.layer_weight_kg or 0)
    total_layers = p.total_layers or 0
    width = float(p.fabric_width_m or 0)
    length = float(p.lay_length_m or 0)
    gramage = float(p.gramage or 0)
    planned_kg = float(p.planned_kg or 0)

    total_beka = round(pieces * beka_per, 6)
    other_beka = round(pieces * other_beka_per, 6)
    total_ribana = round(pieces * ribana_per, 6)
    actual_kg = round(layer_weight * total_layers + scrap + total_beka, 6)

    pieces_per_layer = round(pieces / total_layers, 4) if total_layers else None
    size_count = _size_count_from_range(p.size_range)
    per_piece_weight = None
    if size_count:
        per_piece_weight = round(
            width * length * gramage / size_count + beka_per + other_beka_per, 6
        )
    theoretical_kg = round(per_piece_weight * pieces + scrap, 6) if per_piece_weight is not None else None
    actual_kg_per_piece = round(actual_kg / pieces, 6) if pieces else None
    gross_kg_per_piece = round(planned_kg / pieces, 6) if pieces else None

    return {
        "total_beka_kg": total_beka,
        "other_beka_kg": other_beka,
        "total_ribana_kg": total_ribana,
        "actual_kg": actual_kg,
        "pieces_per_layer": pieces_per_layer,
        "size_count": size_count or None,
        "per_piece_weight_kg": per_piece_weight,
        "theoretical_kg": theoretical_kg,
        "actual_kg_per_piece": actual_kg_per_piece,
        "gross_kg_per_piece": gross_kg_per_piece,
    }


def _serialize(p: CuttingPassport, db=None, model_cache: dict | None = None) -> dict:
    po = p.production_order
    op = p.operator
    model_code = p.model_code
    model_name = None
    model_image_url = None
    if po and po.model_id and db is not None:
        if model_cache is not None and po.model_id in model_cache:
            model_code, model_name, model_image_url = model_cache[po.model_id]
            model_code = model_code or p.model_code
        else:
            m = db.get(CatalogModel, po.model_id)
            if m:
                model_code = m.code or model_code
                model_name = m.name
                model_image_url = model_display_image_url(m)
            if model_cache is not None:
                model_cache[po.model_id] = (m.code if m else None, model_name, model_image_url)
    d = {
        "id": p.id,
        "passport_no": p.passport_no,
        "date": p.date,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
        "production_order_id": p.production_order_id,
        "operator_id": p.operator_id,
        "model_code": model_code,
        "variant": p.variant,
        "mold_no": p.mold_no,
        "image_ref": p.image_ref,
        "operator_name_manual": p.operator_name_manual,
        "fabric_type": p.fabric_type,
        "has_print": p.has_print,
        "order_no": po.order_no if po else p.order_no,
        "lot_no": p.lot_no,
        "size_range": p.size_range,
        "rolls_count": p.rolls_count,
        "layer_weight_kg": float(p.layer_weight_kg) if p.layer_weight_kg is not None else None,
        "total_layers": p.total_layers,
        "planned_kg": float(p.planned_kg) if p.planned_kg is not None else None,
        "pieces": p.pieces,
        "fabric_width_m": float(p.fabric_width_m) if p.fabric_width_m is not None else None,
        "lay_length_m": float(p.lay_length_m) if p.lay_length_m is not None else None,
        "gramage": float(p.gramage) if p.gramage is not None else None,
        "waste_pct": float(p.waste_pct) if p.waste_pct is not None else None,
        "beka_per_piece_kg": float(p.beka_per_piece_kg) if p.beka_per_piece_kg is not None else None,
        "other_beka_per_piece_kg": float(p.other_beka_per_piece_kg) if p.other_beka_per_piece_kg is not None else None,
        "scrap_kg": float(p.scrap_kg) if p.scrap_kg is not None else None,
        "ribana_per_piece_kg": float(p.ribana_per_piece_kg) if p.ribana_per_piece_kg is not None else None,
        "notes": p.notes,
        "production_order_no": po.order_no if po else None,
        "model_name": model_name or model_code,
        "model_image_url": model_image_url,
        "operator_name": op.name if op else p.operator_name_manual,
    }
    d.update(_compute(p))
    return d


def _order_reference_set(po: ProductionOrder) -> set[str]:
    refs = {
        po.production_no,
        po.order_no,
        po.sales_order_no,
    }
    out = {str(ref).strip().lower() for ref in refs if str(ref or "").strip()}
    if po.production_no and po.production_no.upper().startswith("PO-"):
        out.add(f"so-{po.production_no[3:]}".lower())
    return out


def _text(value) -> str | None:
    text = str(value or "").strip()
    return text or None


def _split_model_code(code: str | None) -> tuple[str | None, str | None]:
    value = str(code or "").strip()
    dash_index = value.rfind("-")
    if 0 < dash_index < len(value) - 1:
        return _text(value[:dash_index]), _text(value[dash_index + 1:])
    return _text(value), None


def _model_general(model: CatalogModel | None) -> dict:
    details = model.details_json if model else None
    if not isinstance(details, dict):
        return {}
    general = details.get("general")
    return general if isinstance(general, dict) else {}


def _first_general_text(general: dict, *keys: str) -> str | None:
    for key in keys:
        value = _text(general.get(key))
        if value:
            return value
    return None


def _model_code_parts(model: CatalogModel | None) -> tuple[str | None, str | None]:
    model_no, variant_no = _split_model_code(model.code if model else None)
    general = _model_general(model)
    return (
        _first_general_text(general, "model_no", "modelNo") or model_no,
        _first_general_text(general, "variant_no", "variantNo") or variant_no,
    )


def _model_mold_no(model: CatalogModel | None, batch: StockBatch | None = None) -> str | None:
    general = _model_general(model)
    return (
        _first_general_text(
            general,
            "mold_no",
            "moldNo",
            "pattern_no",
            "patternNo",
            "qolip_no",
            "qolipNo",
            "qolip",
            "pattern",
        )
        or _text(batch.old_code if batch else None)
    )


def _size_options(db: DbSession, po: ProductionOrder, model: CatalogModel | None) -> list[str]:
    sizes: list[str] = []
    for (size,) in (
        db.query(ProductionOrderItem.size)
        .filter(ProductionOrderItem.production_order_id == po.id)
        .order_by(ProductionOrderItem.id.asc())
        .all()
    ):
        value = str(size or "").strip()
        if value:
            sizes.append(value)
    if not sizes and model:
        sizes = [str(row.size or "").strip() for row in (model.sizes or []) if str(row.size or "").strip()]
    return list(dict.fromkeys(sizes))


def _size_range_from_options(sizes: list[str]) -> str | None:
    unique = list(dict.fromkeys(str(size or "").strip() for size in sizes if str(size or "").strip()))
    if not unique:
        return None
    numeric = []
    for value in unique:
        try:
            numeric.append(float(value))
        except (TypeError, ValueError):
            numeric = []
            break
    if numeric:
        first = min(numeric)
        last = max(numeric)
        fmt = lambda n: str(int(n)) if float(n).is_integer() else f"{n:g}"
        return fmt(first) if first == last else f"{fmt(first)}-{fmt(last)}"
    return ", ".join(unique)


def _size_range(db: DbSession, po: ProductionOrder, model: CatalogModel | None) -> str | None:
    return _size_range_from_options(_size_options(db, po, model))


def _passport_defaults_payload(
    *,
    db: DbSession,
    po: ProductionOrder,
    model: CatalogModel | None,
    item: Item | None,
    batch: StockBatch | None,
) -> dict:
    model_no, variant_no = _model_code_parts(model)
    has_print = bool(
        db.query(WorkOrder.id)
        .filter(WorkOrder.production_order_id == po.id, WorkOrder.operation == "printing")
        .first()
    )
    planned_kg = (
        float(po.estimated_material_amount)
        if po.estimated_material_amount is not None
        and str(po.estimated_material_unit or "").strip().lower() in {"", "kg", "kgs", "kilogram", "kilograms"}
        else None
    )
    sizes = _size_options(db, po, model)
    return {
        "production_order_id": int(po.id),
        "production_order_no": po.production_no,
        "order_no": po.order_no,
        "sales_order_no": po.sales_order_no,
        "model_id": int(po.model_id),
        "model_code": model.code if model else model_no,
        "model_no": model_no,
        "model_name": model.name if model else None,
        "variant": variant_no,
        "mold_no": _model_mold_no(model, batch),
        "image_ref": model_display_image_url(model),
        "has_print": has_print,
        "size_range": _size_range_from_options(sizes),
        "sizes": sizes,
        "size_count": len(sizes),
        "pieces": int(po.planned_quantity or 0) or None,
        "planned_kg": planned_kg,
        "fabric_type": item.name if item else None,
        "material_item_id": int(item.id) if item else None,
        "material_item_sku": item.sku if item else None,
        "material_item_name": item.name if item else None,
        "batch_id": int(batch.id) if batch else None,
        "batch_no": batch.batch_no if batch else None,
        "lot_no": batch.batch_no if batch else None,
        "material_order_no": batch.order_no if batch else None,
        "gramage": float(batch.gsm) if batch and batch.gsm is not None else None,
        "width": float(batch.width) if batch and batch.width is not None else None,
        "fabric_width_m": float(batch.width) if batch and batch.width is not None else None,
    }


@router.get("/material-defaults")
def material_defaults(
    production_order_id: int,
    db: DbSession,
    _: CurrentUser,
):
    po = db.get(ProductionOrder, production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")
    model = db.get(CatalogModel, po.model_id)

    bom_rows = (
        db.query(ModelBOM, Item)
        .join(Item, Item.id == ModelBOM.item_id)
        .filter(
            ModelBOM.model_id == po.model_id,
            Item.category.in_(_MATERIAL_CATEGORIES),
        )
        .order_by(ModelBOM.id.asc())
        .all()
    )
    if not bom_rows:
        return _passport_defaults_payload(db=db, po=po, model=model, item=None, batch=None)

    item_priority = {int(bom.item_id): idx for idx, (bom, _) in enumerate(bom_rows)}
    item_ids = sorted(item_priority.keys())
    candidates = (
        db.query(StockBatch, Item)
        .join(Item, Item.id == StockBatch.item_id)
        .filter(
            StockBatch.item_id.in_(item_ids),
            StockBatch.quantity > 0,
        )
        .order_by(StockBatch.id.desc())
        .limit(200)
        .all()
    )
    if not candidates:
        bom, item = bom_rows[0]
        return _passport_defaults_payload(db=db, po=po, model=model, item=item, batch=None)

    order_refs = _order_reference_set(po)

    def score(row: tuple[StockBatch, Item]) -> tuple[int, int, int, int]:
        batch, _item = row
        order_no = str(batch.order_no or "").strip().lower()
        order_match = 0 if order_no and order_no in order_refs else 1
        has_gramage = 0 if batch.gsm is not None else 1
        return (order_match, item_priority.get(int(batch.item_id), 999), has_gramage, -int(batch.id))

    batch, item = min(candidates, key=score)
    return _passport_defaults_payload(db=db, po=po, model=model, item=item, batch=batch)


@router.get("", response_model=list[CuttingPassportOut])
def list_passports(
    db: DbSession,
    _: CurrentUser,
    q: str | None = None,
    production_order_id: int | None = None,
    limit: int = Query(200, ge=1, le=500),
):
    qry = db.query(CuttingPassport).order_by(CuttingPassport.date.desc(), CuttingPassport.id.desc())
    if production_order_id:
        qry = qry.filter(CuttingPassport.production_order_id == production_order_id)
    if q:
        like = f"%{q}%"
        qry = qry.filter(
            CuttingPassport.passport_no.ilike(like)
            | CuttingPassport.lot_no.ilike(like)
            | CuttingPassport.variant.ilike(like)
            | CuttingPassport.model_code.ilike(like)
            | CuttingPassport.order_no.ilike(like)
            | CuttingPassport.operator_name_manual.ilike(like)
        )
    rows = qry.limit(limit).all()
    model_cache: dict = {}
    return [_serialize(r, db, model_cache) for r in rows]


@router.get("/{pid}", response_model=CuttingPassportOut)
def get_passport(pid: int, db: DbSession, _: CurrentUser):
    p = db.get(CuttingPassport, pid)
    if not p:
        raise HTTPException(404, "Cutting passport not found")
    return _serialize(p, db)


@router.post("", response_model=CuttingPassportOut, status_code=201)
def create_passport(
    payload: CuttingPassportIn,
    db: DbSession,
    current: User = Depends(require_permissions("cutting.records", "*")),
):
    p = CuttingPassport(**payload.model_dump())
    db.add(p)
    db.flush()
    log_action(db, current, "create", "CuttingPassport", p.id, new_value={"passport_no": p.passport_no})
    db.commit()
    db.refresh(p)
    return _serialize(p, db)


@router.put("/{pid}", response_model=CuttingPassportOut)
@router.patch("/{pid}", response_model=CuttingPassportOut)
def update_passport(
    pid: int,
    payload: CuttingPassportIn,
    db: DbSession,
    current: User = Depends(require_permissions("cutting.records", "*")),
):
    p = db.get(CuttingPassport, pid)
    if not p:
        raise HTTPException(404, "Cutting passport not found")
    for k, v in payload.model_dump().items():
        setattr(p, k, v)
    log_action(db, current, "update", "CuttingPassport", p.id, new_value={"passport_no": p.passport_no})
    db.commit()
    db.refresh(p)
    return _serialize(p, db)


@router.delete("/{pid}", status_code=204)
def delete_passport(
    pid: int,
    db: DbSession,
    current: User = Depends(require_permissions("cutting.records", "*")),
):
    p = db.get(CuttingPassport, pid)
    if not p:
        raise HTTPException(404, "Cutting passport not found")
    log_action(db, current, "delete", "CuttingPassport", p.id, new_value={"passport_no": p.passport_no})
    db.delete(p)
    db.commit()
