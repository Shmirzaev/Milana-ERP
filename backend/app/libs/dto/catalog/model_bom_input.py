from typing import Optional

from pydantic import BaseModel, Field, field_validator
from pydantic_core import PydanticCustomError

from app.libs.enums.catalog import BomMaterialRole


class ModelBOMIn(BaseModel):
    item_id: Optional[int] = None
    material_name: Optional[str] = Field(None, max_length=255)
    material_role: Optional[BomMaterialRole] = Field(None, max_length=16)
    stock_batch_id: Optional[int] = None
    size: Optional[str] = None
    color: Optional[str] = None
    photo_url: Optional[str] = None
    quantity_per_piece: float
    unit: str
    waste_percent: float = 0

    @field_validator("material_role", mode="before")
    @classmethod
    def normalize_material_role(cls, value, info):
        """Carry the canonical role, and keep the accepted request set unchanged.

        The original request validation runs first, so a role that is not a
        string or is longer than 16 characters is still refused with the same
        error it always was, before anything is discarded.

        An inventory-linked material ignores the role entirely: the service
        drops it, so a supplied role must still pass the request validation
        above before it is dropped.

        A manual material keeps its role as the canonical member. A role that
        is not canonical cannot be represented, so it is carried as absent and
        the service refuses the material with its existing rule.
        """
        if value is None:
            return None
        if not isinstance(value, str):
            raise PydanticCustomError("string_type", "Input should be a valid string")
        if len(value) > 16:
            raise PydanticCustomError(
                "string_too_long", "String should have at most 16 characters", {"max_length": 16}
            )
        if not str(info.data.get("material_name") or "").strip():
            return None
        try:
            return BomMaterialRole(value.strip().lower())
        except ValueError:
            return None
