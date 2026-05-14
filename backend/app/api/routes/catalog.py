from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import (
    Brand, Collection, CollectionModel, Model, ModelImage, ModelSize, ModelColor, ModelBOM, User,
    SalesOrderItem, ProductionOrder, ProductionOrderItem, Bundle, Package, PackageItem, FinishedGoodsStock,
)
from app.schemas.catalog import (
    BrandIn, BrandOut, CollectionIn, CollectionOut,
    ModelIn, ModelOut, ModelDetail, ModelImageIn, ModelSizeIn, ModelColorIn, ModelBOMIn,
)
from app.services.audit import log_action

router = APIRouter(tags=["catalog"])


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
@router.get("/collections", response_model=list[CollectionOut])
def list_collections(db: DbSession, _: CurrentUser, brand_id: int | None = None):
    qry = db.query(Collection)
    if brand_id:
        qry = qry.filter(Collection.brand_id == brand_id)
    return qry.order_by(Collection.id.desc()).all()


@router.post("/collections", response_model=CollectionOut, status_code=201)
def create_collection(payload: CollectionIn, db: DbSession, current: User = Depends(require_permissions("modeling.collections", "*"))):
    c = Collection(**payload.model_dump())
    db.add(c); db.flush()
    log_action(db, current, "create", "Collection", c.id)
    db.commit(); db.refresh(c)
    return c


@router.get("/collections/{cid}", response_model=CollectionOut)
def get_collection(cid: int, db: DbSession, _: CurrentUser):
    c = db.get(Collection, cid)
    if not c: raise HTTPException(404, "Collection not found")
    return c


@router.patch("/collections/{cid}", response_model=CollectionOut)
def update_collection(cid: int, payload: CollectionIn, db: DbSession, current: User = Depends(require_permissions("modeling.collections", "*"))):
    c = db.get(Collection, cid)
    if not c: raise HTTPException(404, "Collection not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
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
@router.get("/models", response_model=list[ModelOut])
def list_models(db: DbSession, _: CurrentUser, status: str | None = None, q: str | None = None):
    qry = db.query(Model)
    if status: qry = qry.filter(Model.status == status)
    if q: qry = qry.filter((Model.name.ilike(f"%{q}%")) | (Model.code.ilike(f"%{q}%")))
    return qry.order_by(Model.id.desc()).all()


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
    db.add(img); db.commit(); db.refresh(img)
    return {"id": img.id}


@router.post("/models/{mid}/sizes", status_code=201)
def add_size(mid: int, payload: ModelSizeIn, db: DbSession, current: User = Depends(require_permissions("modeling.models", "*"))):
    if not db.get(Model, mid): raise HTTPException(404, "Model not found")
    s = ModelSize(model_id=mid, **payload.model_dump())
    db.add(s); db.commit(); db.refresh(s)
    return {"id": s.id}


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
