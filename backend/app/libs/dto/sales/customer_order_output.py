from datetime import datetime

from pydantic import BaseModel, field_serializer

from app.libs.dto.common import ORMModel
from app.libs.enums.finance import CustomerOrderPaymentStatus, InvoiceStatus
from app.libs.enums.sales import SalesOrderStatus


def _legacy_datetime_json(value: datetime | None) -> str | None:
    """Keep the prior dict/jsonable_encoder datetime spelling on this endpoint."""
    return value.isoformat() if value is not None else None


class CustomerOrderPaymentRowOut(BaseModel):
    id: int
    amount: float
    payment_method: str | None = None
    paid_at: datetime | None = None
    notes: str | None = None

    @field_serializer("paid_at", when_used="json")
    def serialize_paid_at(self, value: datetime | None) -> str | None:
        return _legacy_datetime_json(value)


class CustomerOrderInvoiceOut(BaseModel):
    id: int
    invoice_no: str
    amount: float
    status: InvoiceStatus
    issued_at: datetime | None = None
    due_date: datetime | None = None
    paid_amount: float
    raw_paid_amount: float
    advance_amount: float
    balance_due: float
    payments: list[CustomerOrderPaymentRowOut]

    @field_serializer("issued_at", "due_date", when_used="json")
    def serialize_invoice_dates(self, value: datetime | None) -> str | None:
        return _legacy_datetime_json(value)


class CustomerOrderLedgerOut(ORMModel):
    """Customer ledger row with typed fixed statuses.

    Response validation follows the persisted ``ck_sales_orders_status`` and
    ``ck_invoices_status`` vocabularies; JSON status values remain unchanged.
    """

    id: int
    order_no: str
    date: datetime
    total: float
    status: SalesOrderStatus
    invoice_total: float
    paid_total: float
    balance_due: float
    payment_status: CustomerOrderPaymentStatus
    last_payment_at: datetime | None = None
    invoices: list[CustomerOrderInvoiceOut]

    @field_serializer("date", "last_payment_at", when_used="json")
    def serialize_order_dates(self, value: datetime | None) -> str | None:
        return _legacy_datetime_json(value)
