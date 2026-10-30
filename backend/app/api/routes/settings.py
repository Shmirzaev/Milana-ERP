from __future__ import annotations


from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from typing import Literal, overload

from app.core.config import settings as app_settings
from app.core.deps import CurrentUser, DbSession, require_permissions
from app.schemas import SystemSetting, User
from app.libs.dto.support.company_info_input import CompanyInfoUpdate
from app.libs.dto.support.company_info_output import CompanyInfoOut
from app.libs.dto.support.financial_settings_input import FinancialSettingsUpdate
from app.libs.dto.support.financial_settings_output import FinancialSettingsOut
from app.libs.dto.support.settings_output import SettingsOut
from app.libs.dto.support.system_preferences_input import SystemPreferencesUpdate
from app.libs.dto.support.system_preferences_output import SystemPreferencesOut
from app.libs.enums.settings import SettingsSection
from app.models.support.settings_service import get_settings as get_settings_service
from app.models.support.settings_service import (
    SettingsPatch,
    SettingsSectionOut,
    update_settings_section,
)
from app.models.support.settings_service import InvalidStoredSettings
from app.models.audit_service import log_action

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
def get_settings(db: DbSession, _: CurrentUser) -> SettingsOut:
    try:
        return get_settings_service(db)
    except InvalidStoredSettings as exc:
        raise HTTPException(500, f"Stored settings for {exc} are invalid") from exc


@overload
def _save_section(
    section: Literal[SettingsSection.COMPANY_INFO], payload: CompanyInfoUpdate,
    db: DbSession, current: User,
) -> CompanyInfoOut: ...


@overload
def _save_section(
    section: Literal[SettingsSection.FINANCIAL], payload: FinancialSettingsUpdate,
    db: DbSession, current: User,
) -> FinancialSettingsOut: ...


@overload
def _save_section(
    section: Literal[SettingsSection.PREFERENCES], payload: SystemPreferencesUpdate,
    db: DbSession, current: User,
) -> SystemPreferencesOut: ...


def _save_section(
    section: SettingsSection,
    payload: SettingsPatch,
    db: DbSession,
    current: User,
) -> SettingsSectionOut:
    try:
        return update_settings_section(db, actor=current, section=section, patch=payload)
    except ValidationError as exc:
        raise RequestValidationError([
            {**error, "loc": ("body", *error["loc"])} for error in exc.errors()
        ]) from exc


@router.patch("/company_info", response_model=CompanyInfoOut)
def save_company_info(
    payload: CompanyInfoUpdate,
    db: DbSession,
    current: User = Depends(require_permissions("*")),
) -> CompanyInfoOut:
    return _save_section(SettingsSection.COMPANY_INFO, payload, db, current)


@router.patch("/financial", response_model=FinancialSettingsOut)
def save_financial_settings(
    payload: FinancialSettingsUpdate,
    db: DbSession,
    current: User = Depends(require_permissions("*")),
) -> FinancialSettingsOut:
    return _save_section(SettingsSection.FINANCIAL, payload, db, current)


@router.patch("/preferences", response_model=SystemPreferencesOut)
def save_system_preferences(
    payload: SystemPreferencesUpdate,
    db: DbSession,
    current: User = Depends(require_permissions("*")),
) -> SystemPreferencesOut:
    return _save_section(SettingsSection.PREFERENCES, payload, db, current)


@router.patch("/{section}")
def unknown_settings_section(
    section: str,
    payload: dict,
    db: DbSession,
    current: User = Depends(require_permissions("*")),
):
    raise HTTPException(404, "Settings section not found")


@router.post("/company-logo/upload", status_code=201)
async def upload_company_logo(
    db: DbSession,
    file: UploadFile = File(...),
    current: User = Depends(require_permissions("*")),
):
    from app.models.image_storage_service import discard_replaced_managed_image, store_uploaded_image
    from app.models.support.settings_service import load_company_info_for_logo

    stored = await store_uploaded_image(
        file,
        target_dir=app_settings.MODEL_FILES_DIR,
        file_url_base="/storage/model-files",
        name_prefix="company_logo",
        max_bytes=5 * 1024 * 1024,
        prebuild_thumbnails=True,
    )
    logo_url = stored.file_url

    try:
        row, company = load_company_info_for_logo(db)
    except InvalidStoredSettings as exc:
        raise HTTPException(500, f"Stored settings for {exc} are invalid") from exc
    previous_logo_url = str(company.get("logo_url") or "").strip() or None
    company["logo_url"] = logo_url
    if row:
        row.value_json = CompanyInfoOut(**company).model_dump()
    else:
        row = SystemSetting(key="company_info", value_json=CompanyInfoOut(**company).model_dump())
        db.add(row)
        db.flush()
    log_action(db, current, "upload_logo", "SystemSetting", row.id, new_value={"logo_url": logo_url})
    db.commit()
    # Only after the commit, and only once the new URL is the referenced one, is
    # the old managed file unreachable. Re-uploading the identical file, or a
    # failed commit, must leave the previous logo in place.
    if previous_logo_url and previous_logo_url != logo_url:
        discard_replaced_managed_image(previous_logo_url, storage_root=app_settings.MODEL_FILES_DIR)
    return {"logo_url": logo_url}
