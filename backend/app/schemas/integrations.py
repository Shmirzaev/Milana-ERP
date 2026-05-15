from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class OneCInvoiceIn(BaseModel):
    external_id: str = Field(min_length=1)
    sales_order_id: Optional[int] = None
    sales_order_no: Optional[str] = None
    invoice_no: Optional[str] = None
    amount: float
    status: str = "unpaid"
    issued_at: Optional[datetime] = None
    due_date: Optional[datetime] = None


class OneCPaymentIn(BaseModel):
    external_id: str = Field(min_length=1)
    invoice_id: Optional[int] = None
    invoice_no: Optional[str] = None
    invoice_external_id: Optional[str] = None
    amount: float
    payment_method: Optional[str] = None
    paid_at: Optional[datetime] = None
    notes: Optional[str] = None


class OneCSyncIn(BaseModel):
    invoices: list[OneCInvoiceIn] = []
    payments: list[OneCPaymentIn] = []

