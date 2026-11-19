from decimal import Decimal
from datetime import datetime
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.libs.enums.eco_inventory import EcoMaterialKind, EcoReceiptSource
from app.libs.enums.inventory import StockBatchQcStatus
from app.libs.dto.common import StoredUnitCost

PositiveQuantity = Annotated[Decimal, Field(gt=0, lt=Decimal("10000000000"), max_digits=14, decimal_places=4)]


class EcoReceiptDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source: EcoReceiptSource = EcoReceiptSource.PURCHASE
    supplier_id: int | None = Field(default=None, gt=0)
    warehouse_id: int | None = Field(default=None, gt=0)
    production_order_id: int | None = Field(default=None, gt=0)
    document_no: str | None = Field(default=None, max_length=100)
    received_date: datetime | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    cost_per_unit: StoredUnitCost = Decimal("0")
    qc_status: StockBatchQcStatus = StockBatchQcStatus.PASSED
    old_code: str | None = Field(default=None, max_length=64)
    color_code: str | None = Field(default=None, max_length=32)
    color_status: str | None = Field(default=None, max_length=64)
    width: Decimal | None = Field(default=None, gt=0, le=99999999)
    gsm: Decimal | None = Field(default=None, gt=0, le=99999999)
    length_m: Decimal | None = Field(default=None, gt=0, le=9999999999)
    piece_count: int | None = Field(default=None, ge=1, le=1000)
    roll_weights_kg: list[PositiveQuantity] = Field(default_factory=list, max_length=1000)
    roll_lengths_m: list[PositiveQuantity | None] = Field(default_factory=list, max_length=1000)
    processes: str | None = Field(default=None, max_length=255)
    image_url: str | None = Field(default=None, max_length=512)


class EcoMaterialReceiveLineIn(EcoReceiptDetails):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    item_id: int = Field(gt=0)
    kind: EcoMaterialKind
    batch_no: str = Field(min_length=1, max_length=64)
    color: str | None = Field(default=None, max_length=64)
    quantity: PositiveQuantity
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_rolls(self):
        if self.roll_weights_kg:
            if self.unit and self.unit != "kg":
                raise ValueError("Individual roll weights require kg")
            if self.piece_count != len(self.roll_weights_kg) or sum(self.roll_weights_kg) != self.quantity:
                raise ValueError("Roll count and total weight must match the received quantity")
        if self.roll_lengths_m and len(self.roll_lengths_m) != len(self.roll_weights_kg):
            raise ValueError("Provide one optional length per weighed roll")
        if self.kind == EcoMaterialKind.ACCESSORY and (self.roll_weights_kg or self.roll_lengths_m):
            raise ValueError("Individual fabric rolls are not accessory receipts")
        return self


class EcoMaterialReceiveIn(EcoMaterialReceiveLineIn):
    request_key: str = Field(min_length=1, max_length=128)


class EcoMaterialBulkReceiveIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_key: str = Field(min_length=1, max_length=128)
    lines: list[EcoMaterialReceiveLineIn] = Field(min_length=1, max_length=100)


class EcoWarehouseIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=128)
    kind: EcoMaterialKind


class EcoQualityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    qc_status: StockBatchQcStatus


class EcoMaterialConsumeIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_key: str = Field(min_length=1, max_length=128)
    batch_id: int = Field(gt=0)
    quantity: PositiveQuantity
    production_order_id: int | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=2000)


class FactoryFabricDispatchLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_batch_id: int = Field(gt=0)
    quantity: PositiveQuantity


class FactoryFabricDispatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_key: str = Field(min_length=1, max_length=128)
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[FactoryFabricDispatchLineIn] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_batches(self):
        if len({line.source_batch_id for line in self.lines}) != len(self.lines):
            raise ValueError("Select each source batch only once")
        return self


class FactoryFabricReceiptLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_id: int = Field(gt=0)
    quantity: PositiveQuantity


class FactoryFabricReceiptIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_key: str = Field(min_length=1, max_length=128)
    lines: list[FactoryFabricReceiptLineIn] = Field(min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def unique_lines(self):
        if len({line.line_id for line in self.lines}) != len(self.lines):
            raise ValueError("Select each transfer line only once")
        return self
