"""Read contract for global financial settings."""

from pydantic import BaseModel, ConfigDict, Field


class FinancialSettingsOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default_currency: str = "USD"
    fiscal_year_start_month: int = Field(default=1, ge=1, le=12)
