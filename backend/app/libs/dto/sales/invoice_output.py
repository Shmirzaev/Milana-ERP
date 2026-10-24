from datetime import datetime
from typing import Optional

from app.libs.dto.common import ORMModel


class InvoiceOut(ORMModel):
    id: int
    sales_order_id: int
    invoice_no: str
    amount: float
    status: str
    issued_at: Optional[datetime] = None
    due_date: Optional[datetime] = None
