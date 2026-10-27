from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class SplitAllocationPartUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label_id: int = Field(gt=0)
    employee_id: int = Field(gt=0)
    quantity: int = Field(gt=0, strict=True, le=9999999999)
    operation_name: str = Field(min_length=1, max_length=255)
    rate_per_piece: Decimal = Field(ge=0, max_digits=14, decimal_places=4)


class SplitAllocationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=3, max_length=255)
    parts: list[SplitAllocationPartUpdate] = Field(min_length=2, max_length=50)


class SplitAllocationPartOut(BaseModel):
    label_id: int
    label_uid: str
    employee_id: int
    quantity: int
    operation_name: str
    rate_per_piece: Decimal
    employee_name: str
    total_amount: Decimal
    currency: str


class SplitAllocationOut(BaseModel):
    parent_label_id: int
    original_record_id: int
    revision: str
    total_quantity: int
    parts: list[SplitAllocationPartOut]
