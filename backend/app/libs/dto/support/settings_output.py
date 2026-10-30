"""Global settings response envelope."""

from pydantic import BaseModel, ConfigDict

from app.libs.dto.support.company_info_output import CompanyInfoOut
from app.libs.dto.support.financial_settings_output import FinancialSettingsOut
from app.libs.dto.support.system_preferences_output import SystemPreferencesOut


class SettingsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_info: CompanyInfoOut
    financial: FinancialSettingsOut
    preferences: SystemPreferencesOut
