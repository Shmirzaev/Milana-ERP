from decimal import Decimal
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.libs.enums.eco_inventory import EcoMaterialKind

PositiveQuantity = Annotated[Decimal, Field(gt=0, lt=Decimal("10000000000"), max_digits=14, decimal_places=4)]


class EcoMaterialReceiveIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_key: str = Field(min_length=1, max_length=128)
    item_id: int = Field(gt=0)
    kind: EcoMaterialKind
    batch_no: str = Field(min_length=1, max_length=64)
    color: str | None = Field(default=None, max_length=64)
    quantity: PositiveQuantity
    notes: str | None = Field(default=None, max_length=2000)


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
