from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator

from app.libs.dto.common import StoredUnitCost
from app.libs.dto.purchasing.purchase_quantity import PurchaseQuantity, PurchaseReceiptQuantity
from app.libs.enums.inventory import StockBatchQcStatus


class PurchaseOrderLineIn(BaseModel):
    item_id: int
    ordered_quantity: PurchaseQuantity
    unit: Optional[str] = None
    unit_cost: StoredUnitCost = Decimal("0")
    warehouse_id: Optional[int] = None
    supplier_id: Optional[int] = None
    material_name: Optional[str] = None
    photo_url: Optional[str] = None
    notes: Optional[str] = None


class PurchaseOrderIn(BaseModel):
    purchase_request_id: Optional[int] = None
    supplier_id: Optional[int] = None
    expected_date: Optional[datetime] = None
    notes: Optional[str] = None
    lines: list[PurchaseOrderLineIn] = Field(max_length=1000)


class PurchaseOrderReceiveLineIn(BaseModel):
    purchase_order_line_id: int
    received_quantity: PurchaseReceiptQuantity
    batch_no: str
    warehouse_id: Optional[int] = None
    supplier_id: Optional[int] = None
    cost_per_unit: Optional[StoredUnitCost] = None
    color: Optional[str] = None
    old_code: Optional[str] = None
    color_code: Optional[str] = None
    color_status: Optional[str] = None
    order_no: Optional[str] = None
    width: Optional[float] = None
    gsm: Optional[float] = None
    piece_count: Optional[int] = None
    roll_weights_kg: list[float] = Field(default_factory=list, max_length=1000)
    processes: Optional[str] = None
    qc_status: StockBatchQcStatus = StockBatchQcStatus.PASSED
    _raw_qc_status: str | None = PrivateAttr(default=None)

    @field_validator("qc_status", mode="before")
    @classmethod
    def _empty_qc_means_passed(cls, value):
        # The old receipt path stored an empty string as "passed".
        return StockBatchQcStatus.PASSED if value == "" else value

    @model_validator(mode="wrap")
    @classmethod
    def _keep_receipt_qc_for_replay(cls, data, handler):
        raw = data.get("qc_status") if isinstance(data, dict) else None
        model = handler(data)
        if isinstance(raw, StockBatchQcStatus):
            model._raw_qc_status = raw.value
        elif isinstance(raw, str):
            model._raw_qc_status = raw
        return model

    @property
    def raw_qc_status(self) -> str | None:
        return self._raw_qc_status


class PurchaseOrderReceiveIn(BaseModel):
    supplier_id: Optional[int] = None
    close_order: bool = False
    lines: list[PurchaseOrderReceiveLineIn] = Field(max_length=1000)
