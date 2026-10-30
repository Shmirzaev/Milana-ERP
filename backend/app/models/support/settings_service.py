"""Business operations for the global company/financial/preferences sections."""

from __future__ import annotations

from typing import TypeAlias

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.libs.dto.support.company_info_input import CompanyInfoUpdate
from app.libs.dto.support.company_info_output import CompanyInfoOut
from app.libs.dto.support.financial_settings_input import FinancialSettingsUpdate
from app.libs.dto.support.financial_settings_output import FinancialSettingsOut
from app.libs.dto.support.settings_output import SettingsOut
from app.libs.dto.support.system_preferences_input import SystemPreferencesUpdate
from app.libs.dto.support.system_preferences_output import SystemPreferencesOut
from app.libs.enums.settings import SettingsLanguage, SettingsSection
from app.libs.types.support.settings import (
    CompanyInfoSettingsValue,
    FinancialSettingsValue,
    SettingsSectionValue,
    SystemPreferencesValue,
)
from app.schemas import SystemSetting, User
from app.schemas.support.settings_persistence import write_settings_section
from app.models.audit_service import log_action


SettingsPatch: TypeAlias = CompanyInfoUpdate | FinancialSettingsUpdate | SystemPreferencesUpdate
SettingsSectionOut: TypeAlias = CompanyInfoOut | FinancialSettingsOut | SystemPreferencesOut


class InvalidStoredSettings(ValueError):
    """A persisted section cannot satisfy its current typed read contract."""

_LOCK_KEYS = {
    SettingsSection.COMPANY_INFO: 1,
    SettingsSection.FINANCIAL: 2,
    SettingsSection.PREFERENCES: 3,
}
def _load_section_for_update(db: Session, section: SettingsSection) -> SystemSetting | None:
    # Preserve the existing transaction advisory lock then row-lock order.
    if db.bind and db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :section)"),
            {"namespace": 1_297_047_635, "section": _LOCK_KEYS[section]},
        )
    return (
        db.query(SystemSetting)
        .filter(SystemSetting.key == section.value)
        .with_for_update()
        .populate_existing()
        .first()
    )


def _output_model(section: SettingsSection, data: dict) -> SettingsSectionOut:
    if section is SettingsSection.COMPANY_INFO:
        return CompanyInfoOut(**data)
    if section is SettingsSection.FINANCIAL:
        return FinancialSettingsOut(**data)
    if section is SettingsSection.PREFERENCES:
        return SystemPreferencesOut(**data)
    raise ValueError(f"Unsupported settings section: {section!r}")


def _typed_value(section: SettingsSection, output: SettingsSectionOut) -> SettingsSectionValue:
    if section is SettingsSection.COMPANY_INFO and isinstance(output, CompanyInfoOut):
        return CompanyInfoSettingsValue(section=section, **output.model_dump())
    if section is SettingsSection.FINANCIAL and isinstance(output, FinancialSettingsOut):
        return FinancialSettingsValue(section=section, **output.model_dump())
    if section is SettingsSection.PREFERENCES and isinstance(output, SystemPreferencesOut):
        values = output.model_dump()
        values["default_language"] = SettingsLanguage(values["default_language"])
        return SystemPreferencesValue(section=section, **values)
    raise TypeError("Settings section and typed output do not match")


def _validate_patch_pair(section: SettingsSection, patch: SettingsPatch) -> None:
    if section is SettingsSection.COMPANY_INFO:
        if not isinstance(patch, CompanyInfoUpdate):
            raise TypeError("company_info requires CompanyInfoUpdate")
        return
    if section is SettingsSection.FINANCIAL:
        if not isinstance(patch, FinancialSettingsUpdate):
            raise TypeError("financial requires FinancialSettingsUpdate")
        return
    if section is SettingsSection.PREFERENCES:
        if not isinstance(patch, SystemPreferencesUpdate):
            raise TypeError("preferences requires SystemPreferencesUpdate")
        return
    raise ValueError(f"Unsupported settings section: {section!r}")


def _section_output(db: Session, section: SettingsSection) -> SettingsSectionOut:
    row = db.query(SystemSetting).filter(SystemSetting.key == section.value).first()
    data = row.value_json if row and isinstance(row.value_json, dict) else {}
    try:
        return _output_model(section, data)
    except ValidationError as exc:
        # Stored values are not silently normalized; unknown historical
        # languages remain visible as an explicit stored-data failure.
        raise InvalidStoredSettings(section.value) from exc


def get_settings(db: Session) -> SettingsOut:
    return SettingsOut(
        company_info=_section_output(db, SettingsSection.COMPANY_INFO),
        financial=_section_output(db, SettingsSection.FINANCIAL),
        preferences=_section_output(db, SettingsSection.PREFERENCES),
    )


def update_settings_section(
    db: Session,
    *,
    actor: User,
    section: SettingsSection,
    patch: SettingsPatch,
) -> SettingsSectionOut:
    """Merge and persist one section, audit it, and commit once on the same Session."""
    _validate_patch_pair(section, patch)
    row = _load_section_for_update(db, section)
    old_value = row.value_json if row else None
    previous = old_value if isinstance(old_value, dict) else {}
    merged = {**previous, **patch.model_dump(exclude_unset=True, mode="python")}
    output = _output_model(section, merged)
    value = _typed_value(section, output)
    row = write_settings_section(db, setting=row, value=value)
    new_value = {section.value: output.model_dump(mode="json")}
    log_action(
        db,
        actor,
        "update",
        "SystemSetting",
        row.id,
        old_value=old_value,
        new_value=new_value,
    )
    db.commit()
    return output


def load_company_info_for_logo(db: Session) -> tuple[SystemSetting | None, dict]:
    """Return the legacy validated company payload under the shared section lock."""
    row = _load_section_for_update(db, SettingsSection.COMPANY_INFO)
    data = row.value_json if row and isinstance(row.value_json, dict) else {}
    try:
        company = CompanyInfoOut(**data).model_dump()
    except ValidationError as exc:
        raise InvalidStoredSettings(SettingsSection.COMPANY_INFO.value) from exc
    return row, company
