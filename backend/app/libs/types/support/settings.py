"""Typed internal values passed from Support service to section persistence."""

from dataclasses import dataclass
from typing import TypeAlias

from app.libs.enums.settings import SettingsLanguage, SettingsSection


@dataclass(frozen=True)
class CompanyInfoSettingsValue:
    section: SettingsSection
    name: str
    logo_url: str | None
    address: str | None
    phone: str | None
    email: str | None

    def to_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "logo_url": self.logo_url,
            "address": self.address,
            "phone": self.phone,
            "email": self.email,
        }


@dataclass(frozen=True)
class FinancialSettingsValue:
    section: SettingsSection
    default_currency: str
    fiscal_year_start_month: int

    def to_json(self) -> dict[str, object]:
        return {
            "default_currency": self.default_currency,
            "fiscal_year_start_month": self.fiscal_year_start_month,
        }


@dataclass(frozen=True)
class SystemPreferencesValue:
    section: SettingsSection
    default_language: SettingsLanguage
    timezone: str
    model_types: list[str]
    require_material_reservation_before_cutting: bool

    def to_json(self) -> dict[str, object]:
        return {
            "default_language": self.default_language.value,
            "timezone": self.timezone,
            "model_types": list(self.model_types),
            "require_material_reservation_before_cutting": self.require_material_reservation_before_cutting,
        }


SettingsSectionValue: TypeAlias = CompanyInfoSettingsValue | FinancialSettingsValue | SystemPreferencesValue
