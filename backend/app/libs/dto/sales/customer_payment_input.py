from datetime import datetime

from pydantic import BaseModel, Field


class CustomerPaymentIn(BaseModel):
    sales_order_id: int | None = None
    amount: float = Field(ge=0.01, multiple_of=0.01, allow_inf_nan=False)
    paid_at: datetime | None = None
    payment_method: str | None = None
    notes: str | None = None
