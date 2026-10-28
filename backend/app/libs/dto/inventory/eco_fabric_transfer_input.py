"""Request contracts for the Eco Cotton fabric transfer register."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ScanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=2048)


class SendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    codes: list[str] = Field(min_length=1, max_length=500)


class ReturnIn(ScanIn):
    request_key: UUID
    dispatch_id: int = Field(gt=0)
