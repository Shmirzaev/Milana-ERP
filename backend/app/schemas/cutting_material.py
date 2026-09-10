from pydantic import BaseModel, ConfigDict, Field


class CuttingMaterialDetails(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    layer_material_kg: float = Field(default=0, ge=0)
    beika_kg: float = Field(default=0, ge=0)
    material_rolls_used: float = Field(default=0, ge=0)
    layup_operator_name: str = Field(default="", max_length=128)
    cut_pieces: int = Field(default=0, ge=0)
    waste_quantity: float = Field(default=0, ge=0)
    waste_unit: str = Field(default="kg", min_length=1, max_length=32)


class PassportMaterial(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    stock_batch_id: int = Field(gt=0)
    fabric_type: str | None = None
    lot_no: str | None = None
    operator_name_manual: str | None = Field(default=None, max_length=128)
    rolls_count: int | None = Field(default=None, ge=0)
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

