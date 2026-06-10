from fastapi import APIRouter, HTTPException, Depends, Query

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models.cutting_passport import CuttingPassport
from app.models import User
from app.models.catalog import Model as CatalogModel
from app.schemas.cutting_passport import CuttingPassportIn, CuttingPassportOut
from app.services.audit import log_action

router = APIRouter(prefix="/cutting-passports", tags=["cutting_passports"])


_IMAGE_FILE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def _is_displayable_image(img) -> bool:
    return (
        str(img.content_type or "").lower().startswith("image/")
        or str(img.file_name or img.file_url or "").lower().endswith(_IMAGE_FILE_SUFFIXES)
    )


def _model_preview_image_url(model: CatalogModel | None) -> str | None:
    if not model:
        return None
    images = [img for img in (model.images or []) if _is_displayable_image(img)]
    primary = (
        next((img for img in images if img.image_type == "model"), None)
        or next((img for img in images if img.is_primary), None)
        or (images[0] if images else None)
    )
    return primary.file_url if primary else None


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
    per_piece_weight = None
    if pieces_per_layer:
        per_piece_weight = round(
            width * length * gramage / pieces_per_layer + beka_per + other_beka_per, 6
        )
    theoretical_kg = round(per_piece_weight * pieces + total_beka + scrap, 6) if per_piece_weight is not None else None
    actual_kg_per_piece = round(actual_kg / pieces, 6) if pieces else None
    gross_kg_per_piece = round(planned_kg / pieces, 6) if pieces else None

    return {
        "total_beka_kg": total_beka,
        "other_beka_kg": other_beka,
        "total_ribana_kg": total_ribana,
        "actual_kg": actual_kg,
        "pieces_per_layer": pieces_per_layer,
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
                model_image_url = _model_preview_image_url(m)
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
        "order_no": po.production_no if po else p.order_no,
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
        "production_order_no": po.production_no if po else None,
        "model_name": model_name or model_code,
        "model_image_url": model_image_url,
        "operator_name": op.name if op else p.operator_name_manual,
    }
    d.update(_compute(p))
    return d


@router.get("", response_model=list[CuttingPassportOut])
def list_passports(
    db: DbSession,
    _: CurrentUser,
    q: str | None = None,
    limit: int = Query(200, ge=1, le=500),
):
    qry = db.query(CuttingPassport).order_by(CuttingPassport.date.desc(), CuttingPassport.id.desc())
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
