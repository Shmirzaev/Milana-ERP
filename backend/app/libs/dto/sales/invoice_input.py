from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.libs.dto.sales.common import swap_nonfinite_amount


class InvoiceIn(BaseModel):
    sales_order_id: int
    # `invoices.amount` is NUMERIC(14, 2) with `amount >= 0`; max_digits/decimal_places
    # mirror that column so nonfinite, sub-cent and out-of-range values never reach a write.
    amount: Optional[Decimal] = Field(
        default=None, ge=0, max_digits=14, decimal_places=2, allow_inf_nan=False
    )

    @field_validator("amount", mode="before")
    @classmethod
    def _swap_nonfinite_invoice_amount(cls, value: object) -> object:
        return swap_nonfinite_amount(value)
