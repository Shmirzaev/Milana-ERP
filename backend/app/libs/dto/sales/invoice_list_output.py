from pydantic import BaseModel

from app.libs.enums.finance import InvoiceStatus


class InvoiceListRowOut(BaseModel):
    id: int
    invoice_no: str
    sales_order_id: int
    order_no: str
    customer: str | None
    amount: float
    balance_due: float
    status: InvoiceStatus
    date: str | None


class InvoiceListPageOut(BaseModel):
    items: list[InvoiceListRowOut]
    total: int
    limit: int
    offset: int
