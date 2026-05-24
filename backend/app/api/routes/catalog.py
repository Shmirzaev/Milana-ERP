from datetime import datetime, timezone
import os
from uuid import uuid4
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from fastapi import UploadFile, File
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.core.config import settings
from app.models import (
    Brand, Collection, CollectionModel, Model, ModelImage, ModelSize, ModelColor, ModelBOM, User,
    Item, SalesOrderItem, ProductionOrder, ProductionOrderItem, Bundle, Package, PackageItem, FinishedGoodsStock,
)
from app.schemas.catalog import (
    BrandIn, BrandOut, CollectionIn, CollectionOut,
    ModelIn, ModelOut, ModelDetail, ModelImageIn, ModelImageOut, ModelSizeIn, ModelColorIn, ModelBOMIn,
)
from app.services.audit import log_action

router = APIRouter(tags=["catalog"])


def _estimate_variant_net_cost_pc(db: DbSession, model: Model) -> float:
    """Estimate per-piece net cost from BOM default costs and costing percentages."""
    item_ids = {int(row.item_id) for row in (model.bom or []) if row.item_id}
    item_cost_map = {
        int(item.id): float(item.default_cost or 0)
        for item in (db.query(Item).filter(Item.id.in_(item_ids)).all() if item_ids else [])
    }
    base_cost = 0.0
    for row in model.bom or []:
        item_cost = item_cost_map.get(int(row.item_id), 0.0)
        base_cost += float(row.quantity_per_piece or 0) * (1.0 + float(row.waste_percent or 0) / 100.0) * item_cost

    details = model.details_json or {}
    costing = details.get("costing", {}) if isinstance(details, dict) else {}
    labor_pct = float(costing.get("labor_pct") or 12)
    electricity_pct = float(costing.get("electricity_pct") or 4)
    other_pct = float(costing.get("other_pct") or 3)
    return round(base_cost * (1.0 + (labor_pct + electricity_pct + other_pct) / 100.0), 2)


def _pagination_payload(rows: list[dict], *, total: int, page: int, page_size: int) -> dict:
    safe_page = max(1, int(page or 1))
    safe_size = max(1, min(int(page_size or 50), 500))
    return {"rows": rows, "total": int(total), "page": safe_page, "page_size": safe_size}


def _collection_payload(c: Collection) -> dict:
    return CollectionOut.model_validate(c).model_dump()


def _is_preview_image(img: ModelImage) -> bool:
    content_type = str(img.content_type or "").lower()
    file_name = str(img.file_name or img.file_url or "").lower()
    return content_type.startswith("image/") or file_name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"))


def _image_payload(img: ModelImage) -> dict:
    return ModelImageOut.model_validate(img).model_dump()


def _model_payload(m: Model) -> dict:
    payload = ModelOut.model_validate(m).model_dump()
    images = list(m.images or [])
    primary_image = next((img for img in images if img.is_primary and _is_preview_image(img)), None)
    if not primary_image:
        primary_image = next((img for img in images if _is_preview_image(img)), None)
    primary_payload = _image_payload(primary_image) if primary_image else None
    payload["primary_image"] = primary_payload
    payload["primary_image_url"] = primary_payload["file_url"] if primary_payload else None
    payload["image_count"] = len(images)
    return payload


def _models_query(db: DbSession):
    return db.query(Model).options(selectinload(Model.images))


# ===== Brands =====
@router.get("/brands", response_model=list[BrandOut])
def list_brands(db: DbSession, _: CurrentUser):
    return db.query(Brand).order_by(Brand.name).all()


@router.post("/brands", response_model=BrandOut, status_code=201)
def create_brand(payload: BrandIn, db: DbSession, current: User = Depends(require_permissions("modeling.brands", "*"))):
    b = Brand(**payload.model_dump())
    db.add(b); db.flush()
    log_action(db, current, "create", "Brand", b.id)
    db.commit(); db.refresh(b)
    return b


@router.get("/brands/{bid}", response_model=BrandOut)
def get_brand(bid: int, db: DbSession, _: CurrentUser):
    b = db.get(Brand, bid)
    if not b: raise HTTPException(404, "Brand not found")
    return b


@router.patch("/brands/{bid}", response_model=BrandOut)
def update_brand(bid: int, payload: BrandIn, db: DbSession, current: User = Depends(require_permissions("modeling.brands", "*"))):
    b = db.get(Brand, bid)
    if not b: raise HTTPException(404, "Brand not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(b, k, v)
    log_action(db, current, "update", "Brand", b.id)
    db.commit(); db.refresh(b)
    return b


# ===== Collections =====
@router.get("/collections")
def list_collections(
    db: DbSession,
    _: CurrentUser,
    brand_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
    include_total: bool = False,
):
    qry = db.query(Collection)
    if brand_id:
        qry = qry.filter(Collection.brand_id == brand_id)
    total = qry.count() if include_total else 0
    qry = qry.order_by(Collection.id.desc())
    if include_total:
        safe_page = max(1, page)
        safe_size = max(1, min(page_size, 500))
        qry = qry.offset((safe_page - 1) * safe_size).limit(safe_size)
    rows = [_collection_payload(c) for c in qry.all()]
    if include_total:
        return _pagination_payload(rows, total=total, page=page, page_size=page_size)
    return rows


@router.post("/collections", response_model=CollectionOut, status_code=201)
def create_collection(payload: CollectionIn, db: DbSession, current: User = Depends(require_permissions("modeling.collections", "*"))):
    if not payload.year:
        raise HTTPException(400, "Year is required")
    c = Collection(**payload.model_dump())
    db.add(c); db.flush()
    log_action(db, current, "create", "Collection", c.id)
    db.commit(); db.refresh(c)
    return c


@router.get("/collections/seasons")
def list_collection_seasons(db: DbSession, _: CurrentUser):
    rows = (
        db.query(Collection.season)
        .filter(Collection.season.isnot(None), Collection.season != "")
        .group_by(Collection.season)
        .order_by(Collection.season.asc())
        .all()
    )
    return [season for (season,) in rows if season]


@router.get("/collections/{cid}", response_model=CollectionOut)
def get_collection(cid: int, db: DbSession, _: CurrentUser):
    c = db.get(Collection, cid)
    if not c: raise HTTPException(404, "Collection not found")
    return c


@router.patch("/collections/{cid}", response_model=CollectionOut)
def update_collection(cid: int, payload: CollectionIn, db: DbSession, current: User = Depends(require_permissions("modeling.collections", "*"))):
    c = db.get(Collection, cid)
    if not c: raise HTTPException(404, "Collection not found")
    data = payload.model_dump(exclude_unset=True)
    if "year" in data and not data["year"]:
        raise HTTPException(400, "Year is required")
    for k, v in data.items():
        setattr(c, k, v)
    log_action(db, current, "update", "Collection", c.id)
    db.commit(); db.refresh(c)
    return c


@router.post("/collections/{cid}/models", status_code=201)
def add_model_to_collection(cid: int, model_id: int, db: DbSession, current: User = Depends(require_permissions("modeling.collections", "*"))):
    if not db.get(Collection, cid):
        raise HTTPException(404, "Collection not found")
    if not db.get(Model, model_id):
        raise HTTPException(404, "Model not found")
    db.add(CollectionModel(collection_id=cid, model_id=model_id))
    db.commit()
    return {"message": "added"}


# ===== Models =====
@router.get("/models")
def list_models(
    db: DbSession,
    _: CurrentUser,
    status: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 50,
    include_total: bool = False,
):
    qry = _models_query(db)
    if status: qry = qry.filter(Model.status == status)
    if q: qry = qry.filter((Model.name.ilike(f"%{q}%")) | (Model.code.ilike(f"%{q}%")))
    total = qry.count() if include_total else 0
    qry = qry.order_by(Model.id.desc())
    if include_total:
        safe_page = max(1, page)
        safe_size = max(1, min(page_size, 500))
        qry = qry.offset((safe_page - 1) * safe_size).limit(safe_size)
    rows = [_model_payload(m) for m in qry.all()]
    if include_total:
        return _pagination_payload(rows, total=total, page=page, page_size=page_size)
    return rows


@router.post("/models", response_model=ModelOut, status_code=201)
def create_model(payload: ModelIn, db: DbSession, current: User = Depends(require_permissions("modeling.models", "*"))):
    if db.query(Model).filter(Model.code == payload.code).first():
        raise HTTPException(400, "Model code already exists")
    m = Model(**payload.model_dump(), created_by=current.id)
    db.add(m); db.flush()
    log_action(db, current, "create", "Model", m.id, new_value={"code": m.code})
    db.commit(); db.refresh(m)
    return m


@router.get("/models/{mid}", response_model=ModelDetail)
def get_model(mid: int, db: DbSession, _: CurrentUser):
    m = db.get(Model, mid)
    if not m: raise HTTPException(404, "Model not found")
    return m


@router.get("/models/{mid}/variants")
def list_model_variants(mid: int, db: DbSession, _: CurrentUser):
    """Return color/size variants for a model with estimated net cost per piece."""
    m = db.query(Model).filter(Model.id == mid).first()
    if not m:
        raise HTTPException(404, "Model not found")

    rows: list[dict] = []
    cost_pc = _estimate_variant_net_cost_pc(db, m)
    index = 1
    colors = [c.color_name for c in (m.colors or [])]
    sizes = [s.size for s in (m.sizes or [])]
    for color in colors:
        for size in sizes:
            rows.append(
                {
                    "id": index,
                    "color": color,
                    "size": size,
                    "estimated_net_cost_pc": cost_pc,
                }
            )
            index += 1
    return rows


@router.patch("/models/{mid}", response_model=ModelOut)
def update_model(mid: int, payload: ModelIn, db: DbSession, current: User = Depends(require_permissions("modeling.models", "*"))):
    m = db.get(Model, mid)
    if not m: raise HTTPException(404, "Model not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(m, k, v)
    log_action(db, current, "update", "Model", m.id)
    db.commit(); db.refresh(m)
    return m


@router.post("/models/{mid}/approve", response_model=ModelOut)
def approve_model(mid: int, db: DbSession, current: User = Depends(require_permissions("modeling.approve", "*"))):
    m = db.get(Model, mid)
    if not m: raise HTTPException(404, "Model not found")
    m.status = "approved"
    m.approved_by = current.id
    m.approved_at = datetime.now(timezone.utc)
    log_action(db, current, "approve", "Model", m.id)
    db.commit(); db.refresh(m)
    return m


@router.post("/models/{mid}/images", status_code=201)
def add_image(mid: int, payload: ModelImageIn, db: DbSession, current: User = Depends(require_permissions("modeling.models", "*"))):
    if not db.get(Model, mid): raise HTTPException(404, "Model not found")
    img = ModelImage(model_id=mid, **payload.model_dump())
    db.add(img)
    db.flush()
    log_action(db, current, "create", "ModelImage", img.id, new_value={"model_id": mid, "file_url": img.file_url})
    db.commit(); db.refresh(img)
    return {"id": img.id}


@router.post("/models/{mid}/images/upload", status_code=201)
async def upload_image(
    mid: int,
    db: DbSession,
    file: UploadFile = File(...),
    current: User = Depends(require_permissions("modeling.models", "*")),
):
    if not db.get(Model, mid):
        raise HTTPException(404, "Model not found")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".dxf", ".ai", ".svg"}:
        raise HTTPException(400, "Unsupported pattern file type")
    os.makedirs(settings.MODEL_FILES_DIR, exist_ok=True)
    safe_name = f"model_{mid}_{uuid4().hex}{ext}"
    abs_path = os.path.join(settings.MODEL_FILES_DIR, safe_name)
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "Empty file")
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 20MB)")
    with open(abs_path, "wb") as f:
        f.write(content)
    file_url = f"/storage/model-files/{safe_name}"
    img = ModelImage(
        model_id=mid,
        file_url=file_url,
        file_name=file.filename or safe_name,
        content_type=file.content_type,
        is_primary=False,
    )
    db.add(img)
    db.flush()
    log_action(db, current, "create", "ModelImage", img.id, new_value={"model_id": mid, "file_url": file_url})
    db.commit()
    return {"id": img.id, "file_url": file_url}


@router.delete("/models/{mid}/images/{image_id}", status_code=204)
def delete_image(
    mid: int,
    image_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
):
    img = db.query(ModelImage).filter(ModelImage.id == image_id, ModelImage.model_id == mid).first()
    if not img:
        raise HTTPException(404, "Pattern file not found")
    file_url = img.file_url
    db.delete(img)
    log_action(db, current, "delete", "ModelImage", image_id, new_value={"model_id": mid, "file_url": file_url})
    db.commit()


@router.post("/models/{mid}/sizes", status_code=201)
def add_size(mid: int, payload: ModelSizeIn, db: DbSession, current: User = Depends(require_permissions("modeling.models", "*"))):
    if not db.get(Model, mid): raise HTTPException(404, "Model not found")
    s = ModelSize(model_id=mid, **payload.model_dump())
    db.add(s)
    db.flush()
    log_action(db, current, "create", "ModelSize", s.id, new_value={"model_id": mid, "size": s.size})
    db.commit(); db.refresh(s)
    return {"id": s.id}


@router.delete("/models/{mid}/sizes/{size_id}", status_code=204)
def delete_size(mid: int, size_id: int, db: DbSession, current: User = Depends(require_permissions("modeling.models", "*"))):
    s = db.query(ModelSize).filter(ModelSize.id == size_id, ModelSize.model_id == mid).first()
    if not s:
        raise HTTPException(404, "Size not found")
    db.delete(s)
    log_action(db, current, "delete", "ModelSize", size_id, new_value={"model_id": mid, "size": s.size})
    db.commit()


@router.post("/models/{mid}/colors", status_code=201)
def add_color(mid: int, payload: ModelColorIn, db: DbSession, current: User = Depends(require_permissions("modeling.models", "*"))):
    if not db.get(Model, mid): raise HTTPException(404, "Model not found")
    c = ModelColor(model_id=mid, **payload.model_dump())
    db.add(c); db.commit(); db.refresh(c)
    return {"id": c.id}


@router.post("/models/{mid}/bom", status_code=201)
def add_bom(mid: int, payload: ModelBOMIn, db: DbSession, current: User = Depends(require_permissions("modeling.bom", "*"))):
    if not db.get(Model, mid): raise HTTPException(404, "Model not found")
    b = ModelBOM(model_id=mid, **payload.model_dump())
    db.add(b); db.flush()
    log_action(db, current, "create", "ModelBOM", b.id, new_value={"model_id": mid})
    db.commit(); db.refresh(b)
    return {"id": b.id}


@router.delete("/models/{mid}", status_code=204)
def delete_model(mid: int, db: DbSession, current: User = Depends(require_permissions("modeling.models", "*"))):
    m = db.get(Model, mid)
    if not m:
        raise HTTPException(404, "Model not found")

    blockers: list[str] = []
    if db.query(SalesOrderItem).filter(SalesOrderItem.model_id == mid).first():
        blockers.append("sales orders")
    if db.query(ProductionOrder).filter(ProductionOrder.model_id == mid).first():
        blockers.append("production orders")
    if db.query(ProductionOrderItem).filter(ProductionOrderItem.model_id == mid).first():
        blockers.append("production order items")
    if db.query(Bundle).filter(Bundle.model_id == mid).first():
        blockers.append("bundles")
    if db.query(Package).filter(Package.model_id == mid).first():
        blockers.append("packages")
    if db.query(PackageItem).filter(PackageItem.model_id == mid).first():
        blockers.append("package items")
    if db.query(FinishedGoodsStock).filter(FinishedGoodsStock.model_id == mid).first():
        blockers.append("finished goods stock")
    if blockers:
        raise HTTPException(409, f"Model is in use by: {', '.join(blockers)}")

    db.query(CollectionModel).filter(CollectionModel.model_id == mid).delete(synchronize_session=False)
    db.delete(m)
    log_action(db, current, "delete", "Model", mid, new_value={"code": m.code, "name": m.name})
    db.commit()
