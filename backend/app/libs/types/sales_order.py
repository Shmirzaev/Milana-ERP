"""Internal contracts for the sales-order header edit.

The HTTP request stays in `libs/dto/sales/`. This module carries the internal
shape between the Sales service and the Sales schema persistence operation, so
neither side passes an unstructured dictionary around.

Key presence is the supplied/not-supplied signal. An absent key leaves the
stored column untouched; a present key holding null clears it.
"""
from datetime import datetime
from typing import TypedDict

from app.libs.enums.sales import SalesOrderItemSourceType, SalesOrderStatus, SalesOrderType


class StoredSalesAttachment(TypedDict):
    """One stored sales-order attachment.

    The stored path never carries a signature; the signed URL is produced on
    the way out.
    """
    file_url: str
    file_name: str | None
    content_type: str | None


class SalesOrderHeaderChanges(TypedDict, total=False):
    """The header fields one sales-order edit supplies.

    `status` is deliberately absent: workflow status is never written by a
    general edit, so it has no key here.
    """
    customer_id: int | None
    deadline: datetime | None
    printing_instructions: str | None
    printing_attachments: list[StoredSalesAttachment] | None
    notes: str | None


class SalesOrderCustomerPayload(TypedDict):
    id: int
    name: str | None


class SalesOrderModelPayload(TypedDict):
    id: int
    code: str
    name: str
    # Source JSON metadata is not restricted to a mapping on this direct path.
    translations: object
    composition: object


class SalesOrderAttachmentPayload(TypedDict):
    file_url: str
    file_name: str | None
    content_type: str | None


class SalesOrderItemPayload(TypedDict):
    id: int
    sales_order_id: int
    model_id: int
    model_code: str | None
    model_name: str | None
    brand_id: int | None
    collection_id: int | None
    color: str
    size: str
    quantity: int
    requested_pack_count: int | None
    unit_price: float
    printing_required: bool
    source_type: SalesOrderItemSourceType
    notes: str | None
    model: SalesOrderModelPayload | None


class SalesOrderSummaryPayload(TypedDict):
    id: int
    order_no: str
    customer_id: int | None
    customer_name: str | None
    customer: SalesOrderCustomerPayload | None
    order_type: SalesOrderType
    status: SalesOrderStatus
    deadline: datetime | None
    total_amount: float
    planning_estimated_material_cost: float | None
    planning_estimated_labor_cost: float | None
    planning_estimated_electricity_cost: float | None
    planning_estimated_other_cost: float | None
    planning_estimated_net_cost: float | None
    planning_suggested_price_15: float | None
    planning_suggested_price_20: float | None
    planning_estimated_lead_time_minutes: int | None
    planning_estimate_comment: str | None
    planning_estimate_submitted_at: datetime | None
    planning_estimate_submitted_by: int | None
    printing_instructions: str | None
    printing_attachments: list[SalesOrderAttachmentPayload] | None
    notes: str | None
    created_at: datetime


class SalesOrderDetailPayload(SalesOrderSummaryPayload):
    items: list[SalesOrderItemPayload]


class SalesOrderListPayload(SalesOrderSummaryPayload):
    total_quantity: int


class SalesOrderListEnvelope(TypedDict):
    rows: list[SalesOrderListPayload]
    total: int
    page: int
    page_size: int
