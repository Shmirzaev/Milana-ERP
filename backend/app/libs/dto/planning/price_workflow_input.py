from pydantic import BaseModel, ConfigDict, Field

from app.libs.enums.planning import PriceContributionTeam


class PriceWorkflowActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(gt=0)


class PriceApprovalIn(PriceWorkflowActionIn):
    selling_price: float = Field(gt=0, le=9_999_999_999.9999, allow_inf_nan=False, multiple_of=0.0001)


class PriceCorrectionIn(PriceWorkflowActionIn):
    team: PriceContributionTeam
    reason: str = Field(min_length=3, max_length=1000)


class PriceCancelIn(PriceWorkflowActionIn):
    reason: str = Field(min_length=3, max_length=1000)


class PriceRepriceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=1000)


class PriceMaterialRateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=100)
    rate: float | None = Field(default=None, ge=0, le=9_999_999_999.9999, allow_inf_nan=False)


class PriceRetirementTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    request_id: int = Field(gt=0)
    model_id: int = Field(gt=0)
    expected_revision: int = Field(gt=0)
