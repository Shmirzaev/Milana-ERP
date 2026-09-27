from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class OneCInvoiceIn(BaseModel):
    external_id: str = Field(min_length=1)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    sales_order_id: Optional[int] = None
    sales_order_no: Optional[str] = None
    invoice_no: Optional[str] = None
    # Keep nonfinite JSON numbers available to the row validator so one bad
    # 1C record does not reject the full batch during request parsing.
    amount: Decimal | float
    status: str = "unpaid"
    issued_at: Optional[datetime] = None
    due_date: Optional[datetime] = None


class OneCPaymentIn(BaseModel):
    external_id: str = Field(min_length=1)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    invoice_id: Optional[int] = None
    invoice_no: Optional[str] = None
    invoice_external_id: Optional[str] = None
    amount: Decimal | float
    payment_method: Optional[str] = None
    paid_at: Optional[datetime] = None
    notes: Optional[str] = None


class OneCSyncIn(BaseModel):
    invoices: list[OneCInvoiceIn] = Field(default_factory=list, max_length=500)
    payments: list[OneCPaymentIn] = Field(default_factory=list, max_length=500)

