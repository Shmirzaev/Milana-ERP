"""Material reservation request contracts."""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.libs.enums.inventory import MaterialReservationType


class MaterialReservationIn(BaseModel):
    production_order_id: int
    item_id: int
    stock_batch_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    reserved_quantity: float = Field(
        gt=0, le=9_999_999_999.9999, allow_inf_nan=False,
    )
    unit: str
    reservation_type: MaterialReservationType = MaterialReservationType.MATERIAL
    notes: Optional[str] = None


class MaterialReservationAutoIn(BaseModel):
    production_order_id: int
    mode: Literal["shortage_only", "full_remaining"] = "full_remaining"
    reserve_accessories: bool = True
    reserve_materials: bool = True
    reserve_packaging: bool = True


class MaterialReservationConsumeIn(BaseModel):
    quantity: float = Field(
        gt=0, le=9_999_999_999.9999, allow_inf_nan=False,
    )
