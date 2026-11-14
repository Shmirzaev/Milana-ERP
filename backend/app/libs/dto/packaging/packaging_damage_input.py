"""Damage-only Packaging consumes passed garments without creating labels."""
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PackagingDamageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    work_order_id: int = Field(gt=0, le=2_147_483_647)
    production_batch_id: int | None = Field(default=None, gt=0, le=2_147_483_647)
    damaged_qty: int = Field(gt=0, le=2_147_483_647, strict=True)
