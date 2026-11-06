from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.libs.dto.sales.common import swap_nonfinite_amount


class PaymentIn(BaseModel):
    invoice_id: int
    # `payments.amount` is NUMERIC(14, 2) with `amount > 0`, so the smallest
    # representable payment is one cent and nothing wider than the column is accepted.
    amount: Decimal = Field(ge=0.01, max_digits=14, decimal_places=2, allow_inf_nan=False)

    @field_validator("amount", mode="before")
    @classmethod
    def _swap_nonfinite_payment_amount(cls, value: object) -> object:
        return swap_nonfinite_amount(value)
    paid_at: Optional[datetime] = None
    payment_method: Optional[str] = None
    notes: Optional[str] = None
