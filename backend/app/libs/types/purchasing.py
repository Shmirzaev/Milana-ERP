"""Internal contracts for the purchasing operations.

`PurchaseRequestCreateCommand` is the one shape both create callers produce:
the HTTP payload and the sales-order shortage path. It describes the data a
create operation needs; it does not validate it.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import NotRequired, TypedDict

from app.libs.enums.purchasing import PurchaseOrderStatus, PurchaseRequestStatus


class PurchaseRequestLineCommand(TypedDict):
    item_id: int
    required_quantity: float
    requested_quantity: float | None
    unit: str | None
    available_quantity: float
    shortage_quantity: float | None
    preferred_supplier_id: NotRequired[int | None]
    material_name: NotRequired[str | None]
    photo_url: NotRequired[str | None]
    notes: NotRequired[str | None]


class PurchaseRequestCreateCommand(TypedDict):
    status: PurchaseRequestStatus
    sales_order_id: int | None
    production_order_id: NotRequired[int | None]
    notes: str | None
    lines: list[PurchaseRequestLineCommand]


class PurchaseRequestApprovalLineCommand(TypedDict):
    purchase_request_line_id: int
    material_name: str
    preferred_supplier_id: int
    photo_url: str


class PurchaseRequestApprovalCommand(TypedDict):
    # HTTP requires lines; the existing direct approved-retry caller passes {}.
    # The core checks locked status before inspecting the optional line payload.
    lines: NotRequired[list[PurchaseRequestApprovalLineCommand]]


@dataclass(frozen=True)
class PurchaseRequestApprovalTransition:
    """Validated service decision consumed by header persistence and audit.

    String storage remains a persistence boundary, not an internal status type.
    The outer public operation still returns the existing mapped request.
    """

    previous_status: PurchaseRequestStatus
    status: PurchaseRequestStatus
    approved_by: int
    approved_at: datetime


class PurchaseOrderLineCommand(TypedDict):
    item_id: int
    ordered_quantity: float
    unit: str | None
    unit_cost: Decimal | float
    warehouse_id: int | None
    supplier_id: int | None
    material_name: str | None
    photo_url: str | None
    notes: str | None


class PurchaseOrderCreateCommand(TypedDict):
    """The internal shape order creation consumes.

    `status` is the canonical member. Callers that cannot choose a status send
    `PurchaseOrderStatus.DRAFT`; the conversion operation sends `SENT`.
    """

    purchase_request_id: int | None
    supplier_id: int | None
    status: PurchaseOrderStatus
    expected_date: datetime | None
    notes: str | None
    lines: list[PurchaseOrderLineCommand]


class PurchaseRequestConversionLineCommand(TypedDict):
    purchase_request_line_id: int
    ordered_quantity: float


class PurchaseRequestConversionCommand(TypedDict):
    """What one request-to-order conversion needs from its caller.

    The request lines themselves are read by the operation; a caller only
    names the quantity it orders for each of them.
    """

    expected_date: datetime
    lines: list[PurchaseRequestConversionLineCommand]
