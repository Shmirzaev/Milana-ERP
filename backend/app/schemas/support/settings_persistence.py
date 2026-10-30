"""Persistence adapter for the three global settings sections owned by Support."""

from sqlalchemy.orm import Session

from app.libs.enums.settings import SettingsSection
from app.libs.types.support.settings import (
    CompanyInfoSettingsValue,
    FinancialSettingsValue,
    SettingsSectionValue,
    SystemPreferencesValue,
)
from app.schemas import SystemSetting


_SECTION_KEYS = {
    SettingsSection.COMPANY_INFO,
    SettingsSection.FINANCIAL,
    SettingsSection.PREFERENCES,
}


def write_settings_section(
    db: Session,
    *,
    setting: SystemSetting | None,
    value: SettingsSectionValue,
) -> SystemSetting:
    """Write one validated section to the supplied transaction; never commit."""
    matches = (
        isinstance(value, CompanyInfoSettingsValue)
        and value.section is SettingsSection.COMPANY_INFO
    ) or (
        isinstance(value, FinancialSettingsValue)
        and value.section is SettingsSection.FINANCIAL
    ) or (
        isinstance(value, SystemPreferencesValue)
        and value.section is SettingsSection.PREFERENCES
    )
    if not matches or value.section not in _SECTION_KEYS:
        raise ValueError(f"Settings section and typed value do not match: {value.section!r}")

    if setting is None:
        setting = SystemSetting(key=value.section.value, value_json=value.to_json())
        db.add(setting)
        db.flush()
    else:
        if setting.key != value.section.value:
            raise ValueError("Settings row key does not match the typed section value")
        setting.value_json = value.to_json()
    return setting
