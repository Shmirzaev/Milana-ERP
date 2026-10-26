"""Internal contracts for the purchasing operations.

`PurchaseRequestCreateCommand` is the one shape both create callers produce:
the HTTP payload and the sales-order shortage path. It describes the data a
create operation needs; it does not validate it.
"""

from typing import NotRequired, TypedDict

from app.libs.enums.purchasing import PurchaseRequestStatus


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
