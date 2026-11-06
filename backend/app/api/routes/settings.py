from __future__ import annotations


from fastapi import APIRouter, Depends, File, UploadFile

from app.core.deps import CurrentUser, DbSession, require_permissions
from app.schemas import SystemSetting, User
from app.models.audit_service import log_action
from app.models.support import settings_service
from app.libs.dto.support.settings import CompanyInfo as CompanyInfo, FinancialSettings as FinancialSettings, SystemPreferences as SystemPreferences, _SCHEMAS as _SCHEMAS

router = APIRouter(prefix="/settings", tags=["settings"])


app_settings = settings_service.app_settings
_setting_for_update = SystemSetting.for_section_update


_default_payload = settings_service._default_payload
_get_or_default = settings_service._get_or_default


@router.get("")
def get_settings(db: DbSession, _: CurrentUser):
    return settings_service.get_settings(db)


@router.patch("/{section}")
def save_settings_section(
    section: str,
    payload: dict,
    db: DbSession,
    current: User = Depends(require_permissions("*")),
):
    return settings_service.save_settings_section(section, payload, db, current, audit=log_action)


@router.post("/company-logo/upload", status_code=201)
async def upload_company_logo(
    db: DbSession,
    file: UploadFile = File(...),
    current: User = Depends(require_permissions("*")),
):
    return await settings_service.upload_company_logo(db, file, current, audit=log_action)
