"""Brand and collection reference data for the product catalogue.

Contract for the brand and collection operations:
* input: a brand or collection id, a validated contract and the acting user
* output: the serialized brand or collection
* refusals: 404 "Brand not found", 404 "Collection not found", 409 when a
  collection already holds the model
* records: `brands`, `collections` and `collection_models` rows plus the audit
  rows
* transaction owner: every operation below
"""

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.libs.dto.catalog.brand_input import BrandIn
from app.libs.dto.catalog.collection_input import CollectionIn
from app.libs.dto.catalog.collection_output import CollectionOut
from app.models.audit_service import log_action
from app.models.catalog.models_service import _pagination_payload, _standard_model
from app.schemas import Brand, Collection, CollectionModel, User

COLLECTION_STATUSES = frozenset({"draft", "approved", "archived"})


def _collection_payload(c: Collection) -> dict:
    return CollectionOut.model_validate(c).model_dump()


def list_brands(
    current: User,
    db: Session,
):
    return db.query(Brand).order_by(Brand.name).all()


def create_brand(
    current: User,
    db: Session,
    payload: BrandIn,
):
    name = str(payload.name or "").strip()
    if not name:
        raise HTTPException(400, "Brand name is required")
    existing = db.query(Brand).filter(func.lower(Brand.name) == name.lower()).first()
    if existing:
        raise HTTPException(409, "Brand already exists")
    values = payload.model_dump()
    values["name"] = name
    b = Brand(**values)
    db.add(b); db.flush()
    log_action(db, current, "create", "Brand", b.id)
    db.commit(); db.refresh(b)
    return b


def get_brand(
    current: User,
    db: Session,
    bid: int,
):
    b = db.get(Brand, bid)
    if not b: raise HTTPException(404, "Brand not found")
    return b


def update_brand(
    current: User,
    db: Session,
    bid: int,
    payload: BrandIn,
):
    b = db.get(Brand, bid)
    if not b: raise HTTPException(404, "Brand not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(b, k, v)
    log_action(db, current, "update", "Brand", b.id)
    db.commit(); db.refresh(b)
    return b


def list_collections(
    current: User,
    db: Session,
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


def create_collection(
    current: User,
    db: Session,
    payload: CollectionIn,
):
    if not payload.year:
        raise HTTPException(400, "Year is required")
    if payload.status not in COLLECTION_STATUSES:
        raise HTTPException(400, "Invalid collection status")
    c = Collection(**payload.model_dump())
    db.add(c); db.flush()
    log_action(db, current, "create", "Collection", c.id)
    db.commit(); db.refresh(c)
    return c


def list_collection_seasons(
    current: User,
    db: Session,
):
    rows = (
        db.query(Collection.season)
        .filter(Collection.season.isnot(None), Collection.season != "")
        .group_by(Collection.season)
        .order_by(Collection.season.asc())
        .all()
    )
    return [season for (season,) in rows if season]


def get_collection(
    current: User,
    db: Session,
    cid: int,
):
    c = db.get(Collection, cid)
    if not c: raise HTTPException(404, "Collection not found")
    return c


def update_collection(
    current: User,
    db: Session,
    cid: int,
    payload: CollectionIn,
):
    c = db.get(Collection, cid)
    if not c: raise HTTPException(404, "Collection not found")
    data = payload.model_dump(exclude_unset=True)
    if "year" in data and not data["year"]:
        raise HTTPException(400, "Year is required")
    if "status" in data and data["status"] != c.status and data["status"] not in COLLECTION_STATUSES:
        raise HTTPException(400, "Invalid collection status")
    for k, v in data.items():
        setattr(c, k, v)
    log_action(db, current, "update", "Collection", c.id)
    db.commit(); db.refresh(c)
    return c


def add_model_to_collection(
    current: User,
    db: Session,
    cid: int,
    model_id: int,
):
    if not db.get(Collection, cid):
        raise HTTPException(404, "Collection not found")
    if not _standard_model(db, model_id):
        raise HTTPException(404, "Model not found")
    db.add(CollectionModel(collection_id=cid, model_id=model_id))
    db.commit()
    return {"message": "added"}
