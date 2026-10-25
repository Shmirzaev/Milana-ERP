"""Stock batch receipt request contract."""

from decimal import Decimal
from typing import Annotated, Optional

from pydantic import BaseModel, Field, field_serializer

from app.libs.dto.common import StoredUnitCost


class StockBatchIn(BaseModel):
    roll_lengths_m: list[Annotated[float, Field(ge=0.001, lt=100000000000, allow_inf_nan=False)] | None] = Field(default_factory=list, max_length=1000)
    length_m: Optional[float] = Field(default=None, gt=0, lt=100000000000, allow_inf_nan=False)
    item_id: int
    batch_no: str
    supplier_id: Optional[int] = None
    color: Optional[str] = None
    old_code: Optional[str] = None
    color_code: Optional[str] = None
    color_status: Optional[str] = None
    order_no: Optional[str] = None
    width: Optional[float] = None
    gsm: Optional[float] = None
    quantity: float = Field(
        gt=0, le=9_999_999_999.9999, allow_inf_nan=False,
    )
    piece_count: Optional[int] = None
    roll_weights_kg: list[float] = Field(default_factory=list)
    processes: Optional[str] = None
    unit: str
    cost_per_unit: StoredUnitCost = Decimal("0")
    image_url: Optional[str] = None
    warehouse_id: int
    qc_status: str = "pending"

    @field_serializer("cost_per_unit", when_used="json")
    def serialize_cost_per_unit(self, value: Decimal) -> float | int:
        # Existing receipt idempotency records fingerprint float request costs,
        # including integer zero when the original float default was omitted.
        return float(value) if "cost_per_unit" in self.model_fields_set else 0
