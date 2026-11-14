"""Explicit physical contents attributed to one production source batch."""
from pydantic import BaseModel, ConfigDict, Field, field_validator


class PackageAllocationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: int = Field(gt=0, le=2_147_483_647, strict=True)
    color: str = Field(min_length=1, max_length=64)
    size: str = Field(min_length=1, max_length=32)
    quantity: int = Field(gt=0, le=2_147_483_647, strict=True)

    @field_validator("color", "size")
    @classmethod
    def strip_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Package item identity is required")
        return value.strip()
