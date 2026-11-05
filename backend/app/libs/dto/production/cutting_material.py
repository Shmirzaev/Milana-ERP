from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PassportBatchAllocation(BaseModel):
    stock_batch_id: int = Field(strict=True, gt=0)
    quantity: float = Field(gt=0, le=9_999_999_999.999, allow_inf_nan=False)
    # Display-only on input; canonical labels are always resolved by the service.
    batch_no: str | None = Field(default=None, max_length=128)

    @field_validator("quantity")
    @classmethod
    def quantity_precision(cls, value):
        amount = Decimal(str(value))
        if amount != amount.quantize(Decimal(".001")):
            raise ValueError("Batch allocation quantities support at most three decimal places")
        return value


class CuttingMaterialDetails(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    layer_material_kg: float = Field(default=0, ge=0, le=9_999_999_999.9999)
    beika_kg: float = Field(default=0, ge=0, le=9_999_999_999.9999)
    material_rolls_used: float = Field(default=0, ge=0, le=9_999_999_999.9999)
    layup_operator_name: str = Field(default="", max_length=128)
    cut_pieces: int = Field(default=0, ge=0)
    waste_quantity: float = Field(default=0, ge=0, le=9_999_999_999.9999)
    waste_unit: str = Field(default="kg", min_length=1, max_length=32)


class PassportMaterial(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    stock_batch_id: int = Field(gt=0)
    batch_allocations: list[PassportBatchAllocation] = Field(default_factory=list, max_length=1000)
    size_range: str | None = Field(default=None, max_length=512)
    fabric_type: str | None = None
    lot_no: str | None = None
    operator_name_manual: str | None = Field(default=None, max_length=128)
    rolls_count: int | None = Field(default=None, ge=0)
    meter_mode: bool = False
    layer_weight_kg: float | None = Field(default=None, ge=0)
    total_layers: int | None = Field(default=None, ge=0)
    planned_kg: float | None = Field(default=None, ge=0)
    pieces: int | None = Field(default=None, ge=0)
    fabric_width_m: float | None = Field(default=None, ge=0)
    lay_length_m: float | None = Field(default=None, ge=0)
    gramage: float | None = Field(default=None, ge=0)
    waste_pct: float | None = Field(default=None, ge=0, le=100)
    beka_per_piece_kg: float | None = Field(default=None, ge=0)
    other_beka_per_piece_kg: float | None = Field(default=None, ge=0)
    scrap_kg: float | None = Field(default=None, ge=0)
    ribana_per_piece_kg: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def grouped_sources(self):
        if self.batch_allocations:
            ids = [row.stock_batch_id for row in self.batch_allocations]
            if len(ids) < 2 or len(set(ids)) != len(ids) or self.stock_batch_id not in ids:
                raise ValueError("Grouped materials require at least two distinct batches including the primary batch")
        return self

