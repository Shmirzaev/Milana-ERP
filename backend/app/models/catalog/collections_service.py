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
from app.libs.dto.catalog.collection_input import CollectionCreateIn, CollectionIn
from app.libs.dto.catalog.collection_output import CollectionCreateOut, CollectionOut
from app.libs.enums.catalog import CollectionStatus
from app.libs.types.catalog import (
    BrandUpdateCommand,
    CollectionUpdateCommand,
    CollectionUpdateFields,
)
from app.models.audit_service import log_action
from app.models.catalog.models_service import _pagination_payload, _standard_model
from app.schemas import Brand, Collection, CollectionModel, User
from app.schemas.catalog.brand_persistence import apply_brand_update, insert_brand
from app.schemas.catalog.collection_persistence import apply_collection_update, insert_collection

COLLECTION_STATUSES = frozenset(status.value for status in CollectionStatus)


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
    b = insert_brand(
        db, name=name, description=payload.description,
        logo_url=payload.logo_url, is_active=payload.is_active,
    )
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
    fields: BrandUpdateCommand = {"name": payload.name}
    if "description" in payload.model_fields_set:
        fields["description"] = payload.description
    if "logo_url" in payload.model_fields_set:
        fields["logo_url"] = payload.logo_url
    if "is_active" in payload.model_fields_set:
        fields["is_active"] = payload.is_active
    apply_brand_update(db, b, fields)
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
    payload: CollectionCreateIn,
) -> CollectionCreateOut:
    if not payload.year:
        raise HTTPException(400, "Year is required")
    c = insert_collection(
        db,
        brand_id=payload.brand_id,
        name=payload.name,
        season=payload.season,
        year=payload.year,
        description=payload.description,
        status=payload.status,
    )
    log_action(db, current, "create", "Collection", c.id)
    db.commit(); db.refresh(c)
    return CollectionCreateOut.model_validate(c)


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
    fields: CollectionUpdateFields = payload.model_dump(exclude_unset=True)
    if "year" in fields and not fields["year"]:
        raise HTTPException(400, "Year is required")
    if "status" in fields and fields["status"] != c.status and fields["status"] not in COLLECTION_STATUSES:
        raise HTTPException(400, "Invalid collection status")
    command: CollectionUpdateCommand = {
        key: value for key, value in fields.items() if key != "status"
    }
    if "status" in fields:
        submitted_status = fields["status"]
        if submitted_status in COLLECTION_STATUSES:
            # Preserve the mapped attribute assignment/event even for an
            # explicit same-value PATCH; persistence receives a real enum.
            command["status"] = CollectionStatus(submitted_status)
        else:
            # Only the exact stored legacy value passed the equality check
            # above. Keep that compatibility path distinct from canonical
            # lifecycle input rather than weakening the enum field to str.
            command["unchanged_legacy_status"] = submitted_status
    apply_collection_update(db, c, command)
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
