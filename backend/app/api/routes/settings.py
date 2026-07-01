from __future__ import annotations

import os
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, EmailStr, Field

from app.core.config import settings as app_settings
from app.core.deps import CurrentUser, DbSession, require_permissions
from app.core.uploads import SAFE_IMAGE_EXTENSIONS, extension_for_upload, read_validated_upload_content
from app.models import SystemSetting, User
from app.services.audit import log_action

router = APIRouter(prefix="/settings", tags=["settings"])


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
    default_language: str = "en"
    timezone: str = "UTC"
    model_types: list[str] = ["Dress", "Top", "Skirt", "Pants", "Outerwear"]


_SCHEMAS = {
    "company_info": CompanyInfo,
    "financial": FinancialSettings,
    "preferences": SystemPreferences,
}


def _default_payload() -> dict:
    return {key: schema().model_dump() for key, schema in _SCHEMAS.items()}


def _get_or_default(db: DbSession, key: str) -> dict:
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if row and isinstance(row.value_json, dict):
        return _SCHEMAS[key](**row.value_json).model_dump()
    return _SCHEMAS[key]().model_dump()


@router.get("")
def get_settings(db: DbSession, _: CurrentUser):
    return {key: _get_or_default(db, key) for key in _SCHEMAS}


@router.patch("/{section}")
def save_settings_section(
    section: str,
    payload: dict,
    db: DbSession,
    current: User = Depends(require_permissions("*")),
):
    if section not in _SCHEMAS:
        raise HTTPException(404, "Settings section not found")
    schema = _SCHEMAS[section]
    validated = schema(**payload).model_dump()
    row = db.query(SystemSetting).filter(SystemSetting.key == section).first()
    old_value = row.value_json if row else None
    if row:
        row.value_json = validated
    else:
        row = SystemSetting(key=section, value_json=validated)
        db.add(row)
        db.flush()
    log_action(db, current, "update", "SystemSetting", row.id, old_value=old_value, new_value={section: validated})
    db.commit()
    return validated


@router.post("/company-logo/upload", status_code=201)
async def upload_company_logo(
    db: DbSession,
    file: UploadFile = File(...),
    current: User = Depends(require_permissions("*")),
):
    ext = extension_for_upload(file, SAFE_IMAGE_EXTENSIONS)
    os.makedirs(app_settings.MODEL_FILES_DIR, exist_ok=True)
    safe_name = f"company_logo_{uuid4().hex}{ext}"
    abs_path = os.path.join(app_settings.MODEL_FILES_DIR, safe_name)
    content = await read_validated_upload_content(file, ext, 5 * 1024 * 1024)
    with open(abs_path, "wb") as f:
        f.write(content)
    logo_url = f"/storage/model-files/{safe_name}"

    company = _get_or_default(db, "company_info")
    company["logo_url"] = logo_url
    row = db.query(SystemSetting).filter(SystemSetting.key == "company_info").first()
    if row:
        row.value_json = CompanyInfo(**company).model_dump()
    else:
        row = SystemSetting(key="company_info", value_json=CompanyInfo(**company).model_dump())
        db.add(row)
        db.flush()
    log_action(db, current, "upload_logo", "SystemSetting", row.id, new_value={"logo_url": logo_url})
    db.commit()
    return {"logo_url": logo_url}
