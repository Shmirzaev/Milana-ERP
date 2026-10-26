"""Output contracts for the branded planning order feature.

`branded_order_payload` is the output of both the create and the list
operation, so its shape is part of this operation's contract rather than a
later one. The fixed vocabularies are carried as canonical enum members
here; every other field keeps the value the service already produced.

The derived cutting progress has its own canonical vocabulary
(`BrandedCuttingProgress`), because it is a computed projection with exactly
three states and not a stored work-order status.

The nested `ProductionOrder.status` stays a plain string on purpose. There is
no status CHECK on `production_orders`, so its vocabulary belongs to the
Production owner and is queued for reconciliation instead of being copied into
Planning.
"""
from datetime import datetime

from pydantic import Field

from app.libs.dto.common import SchemaModel
from app.libs.enums.planning import (
    BrandedCuttingProgress,
    BrandedPlanningOrderStatus,
    BrandedPlanningOrderType,
)


class BrandedModelOut(SchemaModel):
    id: int | None = None
    code: str
    name: str
    # Both image helpers return None for a model without a matching image, so
    # these stay nullable: the wire payload carries the null through.
    primary_image_url: str | None = None
    variant_fabric: str | None = None
    fabric_image_url: str | None = None


class BrandedCuttingDepartmentOut(SchemaModel):
    code: str
    name: str


class BrandedProductionOut(SchemaModel):
    id: int
    order_no: str
    production_no: str
    model_id: int
    model: BrandedModelOut | None = None
    planned_quantity: int
    status: str
    cutting_status: BrandedCuttingProgress
    cutting_quantity: int = 0
    cutting_departments: list[BrandedCuttingDepartmentOut] = Field(default_factory=list)


class BrandedPlanningOrderOut(SchemaModel):
    id: int
    order_no: str
    ordered_for_type: BrandedPlanningOrderType
    customer_id: int | None = None
    ordered_for_name: str
    status: BrandedPlanningOrderStatus
    notes: str | None = None
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    production_count: int
    total_quantity: int
    cutting_status: BrandedCuttingProgress
    productions: list[BrandedProductionOut] = Field(default_factory=list)
