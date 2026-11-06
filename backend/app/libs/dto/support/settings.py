from pydantic import BaseModel, ConfigDict, EmailStr, Field


class CompanyInfo(BaseModel):
    name: str = "Milana Ecosystem"
    logo_url: str | None = None
    address: str | None = None
    phone: str | None = None
    email: EmailStr | None = None


class FinancialSettings(BaseModel):
    default_currency: str = "USD"
    fiscal_year_start_month: int = Field(default=1, ge=1, le=12)


class SystemPreferences(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    default_language: str = "en"
    timezone: str = "UTC"
    model_types: list[str] = ["Dress", "Top", "Skirt", "Pants", "Outerwear"]
    require_material_reservation_before_cutting: bool = False


_SCHEMAS = {
    "company_info": CompanyInfo,
    "financial": FinancialSettings,
    "preferences": SystemPreferences,
}
