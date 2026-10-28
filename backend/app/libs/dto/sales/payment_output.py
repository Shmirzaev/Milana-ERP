from datetime import datetime
from typing import Optional

from app.libs.dto.common import ORMModel


class PaymentOut(ORMModel):
    id: int
    invoice_id: int
    amount: float
    payment_method: Optional[str] = None
    paid_at: Optional[datetime] = None
