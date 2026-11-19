from pydantic import BaseModel, ConfigDict, Field


class PriceCalculationCreateIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=(), extra="forbid")
    model_id: int = Field(gt=0)
    reprice_reason: str | None = Field(default=None, min_length=3, max_length=1000)
