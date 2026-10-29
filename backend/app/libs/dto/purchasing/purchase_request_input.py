from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.libs.dto.purchasing.purchase_quantity import PurchaseQuantity
from app.libs.enums.purchasing import PurchaseRequestStatus


class PurchaseRequestLineIn(BaseModel):
    item_id: int
    required_quantity: float = 0
    requested_quantity: Optional[float] = None
    unit: Optional[str] = None
    available_quantity: float = 0
    shortage_quantity: Optional[float] = None
    preferred_supplier_id: Optional[int] = None
    material_name: Optional[str] = None
    photo_url: Optional[str] = None
    notes: Optional[str] = None


class PurchaseRequestIn(BaseModel):
    sales_order_id: Optional[int] = None
    production_order_id: Optional[int] = None
    status: PurchaseRequestStatus = PurchaseRequestStatus.PENDING_APPROVAL
    notes: Optional[str] = None
    lines: list[PurchaseRequestLineIn] = Field(max_length=1000)

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: object) -> object:
        """Normalize the raw status before the enum parses it.

        A blank status means pending_approval and surrounding whitespace is
        removed, exactly as the create operation did before the field became
        enum-typed. Anything that is not text is left untouched so the enum
        contract refuses it.
        """
        if not isinstance(value, str):
            return value
        return value.strip() or PurchaseRequestStatus.PENDING_APPROVAL.value


class PurchaseRequestApprovalLineIn(BaseModel):
    purchase_request_line_id: int
    material_name: str
    preferred_supplier_id: int
    photo_url: str


class PurchaseRequestApprovalIn(BaseModel):
    lines: list[PurchaseRequestApprovalLineIn] = Field(max_length=1000)


class PurchaseRequestOrderLineIn(BaseModel):
    purchase_request_line_id: int
    ordered_quantity: PurchaseQuantity


class PurchaseRequestOrderIn(BaseModel):
    expected_date: datetime
    lines: list[PurchaseRequestOrderLineIn] = Field(max_length=1000)
