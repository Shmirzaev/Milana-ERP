from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.libs.dto.common import SchemaModel


class SalesOrderItemIn(SchemaModel):
    model_id: int
    brand_id: Optional[int] = None
    collection_id: Optional[int] = None
    color: str
    size: str
    quantity: Optional[int] = Field(default=None, ge=0, le=2_147_483_647)
    requested_pack_count: Optional[int] = Field(default=None, gt=0, le=2_147_483_647, strict=True)
    # When omitted, the backend uses the selected variant's current selling price.
    # An explicitly entered zero remains an intentional zero-price override.
    unit_price: Optional[float] = Field(default=None, ge=0, le=9_999_999_999.99, allow_inf_nan=False)
    printing_required: bool = False
    source_type: str = "produce_new"
    notes: Optional[str] = None


class SalesOrderPrintingAttachment(BaseModel):
    file_url: str
    file_name: Optional[str] = None
    content_type: Optional[str] = None


class SalesOrderIn(BaseModel):
    customer_id: Optional[int] = None
    order_type: str = "client_order"
    deadline: Optional[datetime] = None
    printing_instructions: Optional[str] = None
    printing_attachments: list[SalesOrderPrintingAttachment] = []
    notes: Optional[str] = None
    items: list[SalesOrderItemIn] = []
