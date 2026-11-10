"""Reviewed, immutable row mappings for a one-time catalogue price import."""

from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class PriceImportBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    price: Decimal | None
    currency: str | None
    source: str | None
    request_id: int | None
    updated_at: datetime | None


class PriceImportRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: int = Field(gt=0)
    erp_code: str = Field(min_length=1, max_length=128)
    source_rows: list[int] = Field(min_length=1)
    source_codes: list[str] = Field(min_length=1)
    base_price: Decimal = Field(gt=0, max_digits=14, decimal_places=4)
    selling_price: Decimal = Field(gt=0, max_digits=14, decimal_places=4)
    expected: PriceImportBaseline

    @model_validator(mode="after")
    def add_adjustment_once(self):
        if self.selling_price != self.base_price + Decimal("0.30"):
            raise ValueError("Selling price must equal the Excel base price plus USD0.30 exactly once")
        if any(row < 2 for row in self.source_rows):
            raise ValueError("Source rows must reference data below the header")
        return self


class PriceImportManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_name: str
    source_workbook_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prices: list[PriceImportRow] = Field(min_length=1, max_length=20000)

    @model_validator(mode="after")
    def unique_targets(self):
        ids = [row.model_id for row in self.prices]
        if len(ids) != len(set(ids)):
            raise ValueError("Each ERP record must have one reviewed source price")
        return self
