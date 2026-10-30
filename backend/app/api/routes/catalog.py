from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile

from app.core.deps import CurrentUser, DbSession, require_permissions
from app.libs.dto.catalog.brand_input import BrandIn
from app.libs.dto.catalog.brand_output import BrandOut
from app.libs.dto.catalog.collection_input import CollectionCreateIn, CollectionIn
from app.libs.dto.catalog.collection_output import CollectionCreateOut, CollectionOut
from app.libs.dto.catalog.model_bom_input import ModelBOMIn
from app.libs.dto.catalog.model_bom_output import ModelBOMCreateOut
from app.libs.dto.catalog.model_bom_update import ModelBOMUpdate
from app.libs.dto.catalog.model_color_input import ModelColorIn
from app.libs.dto.catalog.model_image_input import ModelImageIn, ModelImageUploadInput
from app.libs.dto.catalog.model_input import (
    ModelCreateIn,
    ModelPaidOperationsIn,
    ModelUpdateIn,
    ModelVariantCreateIn,
    ModelVariantUpdateIn,
)
from app.libs.dto.catalog.model_output import (
    ModelDetail,
    ModelOptionPage,
    ModelCreateOut,
    ModelOut,
    ModelSellingPriceOut,
)
from app.libs.dto.catalog.model_size_input import ModelSizeIn
from app.libs.dto.inventory.item_output import ItemOut
from app.libs.enums.catalog import CatalogScope
from app.models.catalog import collections_service, models_service
from app.schemas import User

router = APIRouter(tags=["catalog"])


def _standard_catalog_scope() -> str:
    """FastAPI dependency that keeps the shared PLM routes standard-only."""
    return "standard"


# ===== Brands =====
@router.get("/brands", response_model=list[BrandOut])
def list_brands(db: DbSession, _: CurrentUser):
    return collections_service.list_brands(_, db)


@router.post("/brands", response_model=BrandOut, status_code=201)
def create_brand(
    payload: BrandIn,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.brands", "planning.production", "*")),
):
    return collections_service.create_brand(current, db, payload)


@router.get("/brands/{bid}", response_model=BrandOut)
def get_brand(bid: int, db: DbSession, _: CurrentUser):
    return collections_service.get_brand(_, db, bid)


@router.patch("/brands/{bid}", response_model=BrandOut)
def update_brand(bid: int, payload: BrandIn, db: DbSession, current: User = Depends(require_permissions("modeling.brands", "*"))):
    return collections_service.update_brand(current, db, bid, payload)


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
    return collections_service.list_collections(_, db, brand_id, page, page_size, include_total)


@router.post("/collections", response_model=CollectionCreateOut, status_code=201)
def create_collection(payload: CollectionCreateIn, db: DbSession, current: User = Depends(require_permissions("modeling.collections", "*"))):
    return collections_service.create_collection(current, db, payload)


@router.get("/collections/seasons")
def list_collection_seasons(db: DbSession, _: CurrentUser):
    return collections_service.list_collection_seasons(_, db)


@router.get("/collections/{cid}", response_model=CollectionOut)
def get_collection(cid: int, db: DbSession, _: CurrentUser):
    return collections_service.get_collection(_, db, cid)


@router.patch("/collections/{cid}", response_model=CollectionOut)
def update_collection(cid: int, payload: CollectionIn, db: DbSession, current: User = Depends(require_permissions("modeling.collections", "*"))):
    return collections_service.update_collection(current, db, cid, payload)


@router.post("/collections/{cid}/models", status_code=201)
def add_model_to_collection(cid: int, model_id: int, db: DbSession, current: User = Depends(require_permissions("modeling.collections", "*"))):
    return collections_service.add_model_to_collection(current, db, cid, model_id)


# ===== Models =====
@router.get("/model-options", response_model=ModelOptionPage, description=models_service.list_model_options.__doc__)
def list_model_options(
    db: DbSession,
    _: CurrentUser,
    status: str | None = Query(default=None, max_length=32),
    search: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=50),
    ids: list[int] | None = Query(default=None),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return models_service.list_model_options(_, db, status, search, page, page_size, ids, catalog_scope)


@router.get("/models")
def list_models(
    db: DbSession,
    current: CurrentUser,
    response: Response,
    status: str | None = None,
    q: str | None = None,
    code: str | None = None,
    name: str | None = None,
    category: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    include_total: bool = False,
    include_legacy_import: bool = False,
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    result = models_service.list_models(
        current, db, status, q, code, name, category, created_from, created_to,
        page, page_size, include_total, include_legacy_import, catalog_scope,
    )
    response.headers.update(models_service.model_page_headers(
        result["page"], result["page_size"], result["has_more"], result["total"],
    ))
    if include_total:
        return {
            "rows": result["rows"],
            "total": result["total"],
            "page": result["page"],
            "page_size": result["page_size"],
            "has_more": result["has_more"],
        }
    return result["rows"]


@router.get("/models/variant-groups")
def list_model_variant_groups(
    db: DbSession,
    current: CurrentUser,
    status: str | None = None,
    q: str | None = None,
    code: str | None = None,
    name: str | None = None,
    category: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    page: int = 1,
    page_size: int = 50,
    include_total: bool = False,
    include_legacy_import: bool = False,
    compact: bool = False,
    catalog_scope: str = Depends(_standard_catalog_scope),
    qolip_no: str | None = None,
):
    return models_service.list_model_variant_groups(
        current, db, status, q, code, name, category, created_from, created_to,
        page, page_size, include_total, include_legacy_import, compact, catalog_scope, qolip_no,
    )


@router.get("/models/bom-items", response_model=list[ItemOut], description=models_service.list_model_bom_items.__doc__)
def list_model_bom_items(
    db: DbSession,
    _: User = Depends(require_permissions("modeling.bom", "modeling.models", "*")),
):
    return models_service.list_model_bom_items(_, db)


@router.get("/models/next-number")
def get_next_model_number(
    db: DbSession,
    prefix: str = Query(default="XJ", min_length=2, max_length=2),
    _: User = Depends(require_permissions("modeling.models", "*")),
):
    return models_service.get_next_model_number(_, db, prefix)


@router.post("/models", response_model=ModelCreateOut, status_code=201)
def create_model(
    payload: ModelCreateIn,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return models_service.create_model(current, db, payload, catalog_scope)


@router.get("/models/{mid}/selling-price", response_model=ModelSellingPriceOut)
def get_model_selling_price(
    mid: int,
    db: DbSession,
    _: CurrentUser,
):
    return models_service.get_model_selling_price(_, db, mid)


@router.get("/models/{mid}/resolved-sizes", description=models_service.get_process_qr_model_sizes.__doc__)
@router.get("/models/{mid}/process-qr-sizes", description=models_service.get_process_qr_model_sizes.__doc__)
def get_process_qr_model_sizes(
    mid: int,
    db: DbSession,
    _: CurrentUser,
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return models_service.get_process_qr_model_sizes(_, db, mid, catalog_scope)


@router.get("/models/{mid}", response_model=ModelDetail)
def get_model(
    mid: int,
    db: DbSession,
    current: CurrentUser,
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return models_service.get_model(current, db, mid, catalog_scope)


@router.post("/models/{mid}/clone", response_model=ModelOut, status_code=201)
def clone_model(
    mid: int,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return models_service.clone_model(current, db, mid, catalog_scope)


@router.get("/models/{mid}/variants", description=models_service.list_model_variants.__doc__)
def list_model_variants(
    mid: int,
    response: Response,
    db: DbSession,
    current: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    result = models_service.list_model_variants(current, db, mid, page, page_size, catalog_scope)
    response.headers.update(models_service.model_page_headers(
        result["page"], result["page_size"], result["has_more"],
    ))
    return result["rows"]


@router.get("/models/{mid}/variants/next-number")
def get_next_model_variant_number(
    mid: int,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return models_service.get_next_model_variant_number(current, db, mid, catalog_scope)


@router.post("/models/{mid}/variants", response_model=ModelOut, status_code=201)
def create_model_variant(
    mid: int,
    payload: ModelVariantCreateIn,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return models_service.create_model_variant(current, db, mid, payload, catalog_scope)


@router.patch("/models/{mid}/variants/{variant_id}", response_model=ModelOut)
def update_model_variant(
    mid: int,
    variant_id: int,
    payload: ModelVariantUpdateIn,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return models_service.update_model_variant(current, db, mid, variant_id, payload, catalog_scope)


@router.delete("/models/{mid}/variants/{variant_id}", status_code=204)
def delete_model_variant(
    mid: int,
    variant_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return models_service.delete_model_variant(current, db, mid, variant_id, catalog_scope)


@router.patch("/models/{mid}", response_model=ModelOut)
def update_model(
    mid: int,
    payload: ModelUpdateIn,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return models_service.update_model(current, db, mid, payload, catalog_scope)


@router.patch("/models/{mid}/paid-operations", response_model=ModelOut)
def update_model_paid_operations(
    mid: int,
    payload: ModelPaidOperationsIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return models_service.update_model_paid_operations(current, db, mid, payload, catalog_scope)


@router.post("/models/{mid}/approve", response_model=ModelOut)
def approve_model(
    mid: int,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.approve", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return models_service.approve_model(current, db, mid, catalog_scope)


@router.post("/models/{mid}/images", status_code=201)
def add_image(
    mid: int,
    payload: ModelImageIn,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return models_service.add_image(current, db, mid, payload, catalog_scope)


@router.post("/models/{mid}/images/upload", status_code=201)
async def upload_image(
    mid: int,
    db: DbSession,
    file: UploadFile = File(...),
    image_type: Annotated[ModelImageUploadInput, Form()] = None,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return await models_service.upload_image(current, db, mid, file, image_type, catalog_scope)


@router.delete("/models/{mid}/images/{image_id}", status_code=204)
def delete_image(
    mid: int,
    image_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return models_service.delete_image(current, db, mid, image_id, catalog_scope)


@router.post("/models/{mid}/sizes", status_code=201)
def add_size(
    mid: int,
    payload: ModelSizeIn,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return models_service.add_size(current, db, mid, payload, catalog_scope)


@router.delete("/models/{mid}/sizes/{size_id}", status_code=204)
def delete_size(
    mid: int,
    size_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return models_service.delete_size(current, db, mid, size_id, catalog_scope)


@router.post("/models/{mid}/colors", status_code=201)
def add_color(
    mid: int,
    payload: ModelColorIn,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return models_service.add_color(current, db, mid, payload, catalog_scope)


@router.post("/models/{mid}/bom", status_code=201, response_model=ModelBOMCreateOut)
def add_bom(
    mid: int,
    payload: ModelBOMIn,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.bom", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return models_service.add_bom(current, db, mid, payload, CatalogScope(catalog_scope))


@router.post("/models/{mid}/bom-photo/upload", status_code=201)
async def upload_bom_photo(
    mid: int,
    db: DbSession,
    file: UploadFile = File(...),
    current: User = Depends(require_permissions("modeling.bom", "modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return await models_service.upload_bom_photo(current, db, mid, file, catalog_scope)


@router.patch("/models/{mid}/bom/{bom_id}", status_code=200)
def update_bom(
    mid: int,
    bom_id: int,
    payload: ModelBOMUpdate,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.bom", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return models_service.update_bom(current, db, mid, bom_id, payload, catalog_scope)


@router.delete("/models/{mid}/bom/{bom_id}", status_code=204)
def delete_bom(
    mid: int,
    bom_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.bom", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return models_service.delete_bom(current, db, mid, bom_id, catalog_scope)


@router.delete("/models/{mid}", status_code=204)
def delete_model(
    mid: int,
    db: DbSession,
    current: User = Depends(require_permissions("modeling.models", "*")),
    catalog_scope: str = Depends(_standard_catalog_scope),
):
    return models_service.delete_model(current, db, mid, catalog_scope)
