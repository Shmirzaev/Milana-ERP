from decimal import Decimal
from pydantic import BaseModel, Field, model_validator


class EcoAccessoryRequirementIn(BaseModel):
    item_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=4, allow_inf_nan=False)


class EcoAccessoryPlanIn(BaseModel):
    revision: int = Field(ge=0)
    lines: list[EcoAccessoryRequirementIn] = Field(max_length=100)
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def distinct_items(self):
        if len({line.item_id for line in self.lines}) != len(self.lines):
            raise ValueError("An accessory may appear only once")
        return self


class EcoAccessoryDecisionIn(BaseModel):
    revision: int = Field(gt=0)
    notes: str = Field(default="", max_length=2000)


class EcoAccessoryIssueLineIn(BaseModel):
    allocation_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=4, allow_inf_nan=False)


class EcoAccessoryIssueIn(BaseModel):
    revision: int = Field(gt=0)
    lines: list[EcoAccessoryIssueLineIn] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def distinct_allocations(self):
        if len({line.allocation_id for line in self.lines}) != len(self.lines):
            raise ValueError("An allocation may appear only once")
        return self
