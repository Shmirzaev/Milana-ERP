from datetime import datetime
from typing import Optional

from app.libs.dto.common import ORMModel
from app.libs.enums.finance import InvoiceStatus


class InvoiceOut(ORMModel):
    id: int
    sales_order_id: int
    invoice_no: str
    amount: float
    status: InvoiceStatus
    issued_at: Optional[datetime] = None
    due_date: Optional[datetime] = None
