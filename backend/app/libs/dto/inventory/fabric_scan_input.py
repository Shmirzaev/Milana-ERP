"""Request contract for the daily fabric scan register."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ScanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=2048)
    direction: Literal["received", "returned"]
