"""Request contracts for warehouse stocktakes."""

from uuid import UUID

from pydantic import BaseModel, Field, PositiveInt


class CreateCount(BaseModel):
    request_key: UUID
    title: str = Field(min_length=1, max_length=120)


class ScanCount(BaseModel):
    code: str = Field(min_length=1, max_length=512)


class DeleteCounts(BaseModel):
    count_ids: list[PositiveInt] = Field(min_length=1, max_length=50)


class DeleteScans(BaseModel):
    row_ids: list[PositiveInt] = Field(min_length=1, max_length=200)
