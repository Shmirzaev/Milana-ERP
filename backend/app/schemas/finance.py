from pydantic import BaseModel


class FinanceInvoiceOut(BaseModel):
    id: int
    invoice_no: str
    sales_order_id: int
    order_no: str
    customer: str | None = None
    amount: float
    status: str
    date: str | None = None


class FinanceInvoicePageOut(BaseModel):
    rows: list[FinanceInvoiceOut]
    total: int
    page: int
    page_size: int
    has_more: bool
