from uuid import UUID
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.libs.dto.common import ORMModel
from app.libs.dto.fulfillment.shipment_review import ShipmentTransportDetails

# RF-012: the invoice and payment contracts now live in entity-prefixed modules.
# These aliases keep existing `from app.libs.dto.sales.sales import InvoiceIn`
# callers working; they are the same class objects, not second definitions.
# Remove them once every remaining caller imports the explicit module.
from app.libs.dto.sales.invoice_input import InvoiceIn  # noqa: F401
from app.libs.dto.sales.invoice_output import InvoiceOut  # noqa: F401
from app.libs.dto.sales.payment_input import PaymentIn  # noqa: F401
from app.libs.dto.sales.payment_output import PaymentOut  # noqa: F401

# The sales-order contracts live in `sales_order_input.py`, `sales_order_update.py`
# and `sales_order_output.py`. The shipment contracts below stay here because
# shipments are Fulfillment's entity, not Sales'.


class ShipmentIn(BaseModel):
    manual: bool = False
    request_key: UUID | None = None
    sales_order_id: Optional[int] = None
    customer_id: Optional[int] = None
    notes: Optional[str] = None
    transport_details: ShipmentTransportDetails | None = None


class ShipmentOut(ORMModel):
    id: int
    sales_order_id: Optional[int] = None
    customer_id: Optional[int] = None
    shipment_no: str
    status: str
    shipped_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    notes: Optional[str] = None
    transport_details: ShipmentTransportDetails | None = None
    sales_order_no: Optional[str] = None
    customer_name: Optional[str] = None
    shipment_type: str = "sales_order"
    packages_count: int = 0
    total_qty: int = 0
    required_count: int = 0
    scanned_count: int = 0
    remaining_count: int = 0
    is_complete: bool = False
    created_at: datetime


class ShipmentScanIn(BaseModel):
    code: str


class ShipmentPreviousScan(BaseModel):
    shipment_no: str
    customer_name: str | None = None
    scanned_by_name: str | None = None
    scanned_at: datetime


class ShipmentScanOut(BaseModel):
    ok: bool
    sign: str
    code: str
    message: str
    package_id: Optional[int] = None
    package_no: Optional[str] = None
    package_quantity: Optional[int] = None
    package_model_code: Optional[str] = None
    previous_scan: ShipmentPreviousScan | None = None
    required_count: int = 0
    scanned_count: int = 0
    remaining_count: int = 0
    is_complete: bool = False
