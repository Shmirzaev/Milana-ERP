from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_serializer

from app.libs.dto.catalog.model_bom_output import ModelBOMOut
from app.libs.dto.catalog.model_color_output import ModelColorOut
from app.libs.dto.catalog.model_image_output import ModelImageOut
from app.libs.dto.catalog.model_size_output import ModelSizeOut
from app.libs.dto.common import ORMModel
from app.libs.dto.catalog.model_input import PaidOperationIn
from app.libs.dto.inventory.item_input import ItemComposition


class ModelOut(ORMModel):
    id: int
    code: str
    name: str
    category: Optional[str] = None
    description: Optional[str] = None
    brand_id: Optional[int] = None
    collection_id: Optional[int] = None
    product_type: Optional[str] = None
    season: Optional[str] = None
    constructor_employee_id: Optional[int] = None
    designer_employee_id: Optional[int] = None
    details_json: Optional[dict] = None
    status: str
    sam_minutes: float = 0
    selling_price: Optional[float] = None
    selling_price_currency: Optional[str] = None
    selling_price_source: Optional[str] = None
    selling_price_request_id: Optional[int] = None
    selling_price_updated_at: Optional[datetime] = None
    material_composition: list[ItemComposition] = Field(default_factory=list)
    created_by: Optional[int] = None
    approved_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    created_at: datetime


class PaidOperationOut(PaidOperationIn):
    """Canonical paid-operation row returned after a typed Model CREATE."""

    @model_serializer(mode="wrap")
    def preserve_paid_operation_field_presence(self, handler):
        payload = handler(self)
        for field_name in type(self).model_fields:
            if field_name not in self.model_fields_set:
                payload.pop(field_name, None)
        return payload


class ModelCreateDetailsOut(BaseModel):
    """CREATE response details: typed known rows, preserved open metadata."""

    model_config = {"extra": "allow"}

    paid_operations: list[PaidOperationOut] | None = None
    paidOperations: list[PaidOperationOut] | None = None

    @model_serializer(mode="wrap")
    def preserve_paid_operation_key_presence(self, handler):
        payload = handler(self)
        for key in ("paid_operations", "paidOperations"):
            if key not in self.model_fields_set:
                payload.pop(key, None)
        return payload


class ModelCreateOut(ModelOut):
    """Typed CREATE response; historical GET responses remain opaque ModelOut."""

    details_json: ModelCreateDetailsOut | None = None


class ModelDetail(ModelOut):
    primary_image: Optional[ModelImageOut] = None
    primary_image_url: Optional[str] = None
    variant_picture_url: Optional[str] = None
    images: list[ModelImageOut] = []
    sizes: list[ModelSizeOut] = []
    colors: list[ModelColorOut] = []
    bom: list[ModelBOMOut] = []


class ModelSummaryOut(BaseModel):
    id: int
    code: str
    name: str
    category: Optional[str] = None
    brand_id: Optional[int] = None
    status: str
    thumbnail_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ModelOptionOut(BaseModel):
    id: int
    code: str
    name: str
    thumbnail_url: Optional[str] = None


class ModelSellingPriceOut(BaseModel):
    id: int
    selling_price: Optional[float] = None
    selling_price_currency: Optional[str] = None
    selling_price_source: Optional[str] = None
    selling_price_request_id: Optional[int] = None
    selling_price_updated_at: Optional[datetime] = None


class ModelOptionPage(BaseModel):
    items: list[ModelOptionOut]
    page: int
    page_size: int
    has_more: bool
