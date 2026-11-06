from typing import Optional

from pydantic import BaseModel, Field, field_validator
from pydantic_core import PydanticCustomError

from app.libs.enums.catalog import BomMaterialRole


class ModelBOMUpdate(BaseModel):
    item_id: Optional[int] = None
    material_name: Optional[str] = Field(None, max_length=255)
    material_role: Optional[BomMaterialRole] = None
    stock_batch_id: Optional[int] = None
    size: Optional[str] = None
    color: Optional[str] = None
    photo_url: Optional[str] = None
    quantity_per_piece: Optional[float] = None
    unit: Optional[str] = None
    waste_percent: Optional[float] = None

    @field_validator("material_role", mode="before")
    @classmethod
    def normalize_material_role(cls, value):
        """Preserve the legacy case/whitespace normalization and raw bound."""
        if value is None:
            return None
        if not isinstance(value, str):
            raise PydanticCustomError("string_type", "Input should be a valid string")
        if len(value) > 16:
            raise PydanticCustomError(
                "string_too_long", "String should have at most 16 characters", {"max_length": 16}
            )
        try:
            return BomMaterialRole(value.strip().lower())
        except ValueError:
            # The fixed enum contract intentionally rejects values that the old
            # service ignored or rejected later with HTTP 400.
            raise PydanticCustomError("enum", "Input should be a valid material role") from None
