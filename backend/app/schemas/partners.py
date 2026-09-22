from datetime import datetime

from app.schemas.catalog import PartyOut
from app.schemas.common import SchemaModel


class CustomerOrderPaymentOut(SchemaModel):
    id: int
    amount: float
    payment_method: str | None = None
    paid_at: datetime | None = None
    notes: str | None = None


class CustomerOrderInvoiceOut(SchemaModel):
    id: int
    invoice_no: str
    amount: float
    status: str
    issued_at: datetime | None = None
    due_date: datetime | None = None
    paid_amount: float
    raw_paid_amount: float
    advance_amount: float
    balance_due: float
    payments: list[CustomerOrderPaymentOut]


class CustomerOrderHistoryOut(SchemaModel):
    id: int
    order_no: str
    date: datetime
    total: float
    status: str
    invoice_total: float
    paid_total: float
    balance_due: float
    payment_status: str
    last_payment_at: datetime | None = None
    invoices: list[CustomerOrderInvoiceOut]


class CustomerOrderHistoryPageOut(SchemaModel):
    rows: list[CustomerOrderHistoryOut]
    total: int
    page: int
    page_size: int
    has_more: bool


class CustomerPaymentHistoryOut(SchemaModel):
    id: int
    row_key: str
    amount: float
    payment_method: str | None = None
    paid_at: datetime | None = None
    notes: str | None = None
    order_id: int | None = None
    order_no: str | None = None
    invoice_id: int | None = None
    invoice_no: str | None = None
    invoice_amount: float | None = None
    is_advance: bool


class CustomerPaymentHistoryPageOut(SchemaModel):
    rows: list[CustomerPaymentHistoryOut]
    total: int
    page: int
    page_size: int
    has_more: bool


class SupplierPageOut(SchemaModel):
    rows: list[PartyOut]
    total: int
    page: int
    page_size: int
    has_more: bool
