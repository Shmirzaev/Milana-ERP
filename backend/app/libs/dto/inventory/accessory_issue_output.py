"""Accessory issue response contracts."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class AccessoryIssuePlanRow(BaseModel):
    item_id: int
    item_sku: str
    item_name: str
    item_image_url: Optional[str] = None
    category: str
    unit: str
    required_quantity: float
    issued_quantity: float
    remaining_quantity: float
    available_quantity: float
    shortage: float
    status: str


class AccessoryIssuePlanOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    production_order_id: int
    production_no: str
    order_no: Optional[str] = None
    model_id: int
    model_code: Optional[str] = None
    model_name: Optional[str] = None
    planned_quantity: int
    status: str
    is_complete: bool
    warning: Optional[str] = None
    summary: dict
    rows: list[AccessoryIssuePlanRow]


class AccessoryIssueLineOut(BaseModel):
    item_id: int
    item_sku: str
    item_name: str
    item_image_url: Optional[str] = None
    quantity: float
    unit: str


class AccessoryIssueOut(BaseModel):
    production_order_id: int
    production_no: str
    order_no: Optional[str] = None
    issued: list[AccessoryIssueLineOut]


class AccessoryIssueSummaryRow(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    production_order_id: int
    production_no: str
    order_no: Optional[str] = None
    model_id: int
    model_code: Optional[str] = None
    model_name: Optional[str] = None
    item_id: int
    item_sku: str
    item_name: str
    item_image_url: Optional[str] = None
    category: str
    unit: str
    issued_quantity: float
    returned_quantity: float = 0
    returnable_quantity: float = 0
    movement_count: int
    first_issued_at: Optional[datetime] = None
    last_issued_at: Optional[datetime] = None


class AccessoryIssueRequestRow(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    production_order_id: int
    production_no: str
    order_no: Optional[str] = None
    model_id: int
    model_code: Optional[str] = None
    model_name: Optional[str] = None
    planned_quantity: int
    item_id: int
    item_sku: str
    item_name: str
    item_image_url: Optional[str] = None
    category: str
    unit: str
    required_quantity: float
    issued_quantity: float
    remaining_quantity: float
    available_quantity: float
    shortage: float
    status: str
