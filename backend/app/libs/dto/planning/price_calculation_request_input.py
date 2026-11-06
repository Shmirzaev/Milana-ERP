from pydantic import BaseModel, ConfigDict, Field


class PriceCalculationCreateIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=(), extra="forbid")
    model_id: int = Field(gt=0)
