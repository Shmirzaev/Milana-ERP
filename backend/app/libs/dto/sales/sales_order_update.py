from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.libs.dto.sales.sales_order_input import SalesOrderPrintingAttachment


class SalesOrderUpdate(BaseModel):
    customer_id: Optional[int] = None
    deadline: Optional[datetime] = None
    printing_instructions: Optional[str] = None
    printing_attachments: Optional[list[SalesOrderPrintingAttachment]] = None
    notes: Optional[str] = None
    status: Optional[str] = None
