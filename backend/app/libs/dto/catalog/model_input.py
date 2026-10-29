from typing import Literal, Optional

from pydantic import BaseModel, Field


class ModelIn(BaseModel):
    code: str
    automatic_model_prefix: Optional[str] = Field(default=None, min_length=2, max_length=2)
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
    status: str = "draft"
    sam_minutes: float = 0


class ModelPaidOperationsIn(BaseModel):
    paid_operations: list[dict] = Field(default_factory=list)
    sewing_factory: Literal["milana", "besttex", "eco_cotton"] | None = None


class ModelVariantCreateIn(BaseModel):
    variant_no: Optional[str] = Field(default=None, min_length=1, max_length=64)
    fabric_item_id: Optional[int] = Field(default=None, gt=0)
    color: Optional[str] = Field(default=None, max_length=128)
    picture_url: Optional[str] = None
    print_picture_url: Optional[str] = None
    # Accepted temporarily so older clients can be normalized to the batch's
    # master fabric item without retaining the physical batch on the model.
    stock_batch_id: Optional[int] = Field(default=None, gt=0)


class ModelVariantUpdateIn(ModelVariantCreateIn):
    variant_no: str = Field(min_length=1, max_length=64)
