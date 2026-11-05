from __future__ import annotations


from fastapi import APIRouter, Depends, File, UploadFile

from app.core.config import settings as app_settings
from app.core.deps import CurrentUser, DbSession, require_permissions
from app.schemas import SystemSetting, User
from app.models.audit_service import log_action
from app.models.support import settings_service
from app.libs.dto.support.settings import CompanyInfo, FinancialSettings as FinancialSettings, SystemPreferences as SystemPreferences, _SCHEMAS

router = APIRouter(prefix="/settings", tags=["settings"])


_setting_for_update = SystemSetting.for_section_update


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
    return settings_service.save_settings_section(section, payload, db, current, audit=log_action)


@router.post("/company-logo/upload", status_code=201)
async def upload_company_logo(
    db: DbSession,
    file: UploadFile = File(...),
    current: User = Depends(require_permissions("*")),
):
    from app.models.image_storage_service import discard_replaced_managed_image, store_uploaded_image

    stored = await store_uploaded_image(
        file,
        target_dir=app_settings.MODEL_FILES_DIR,
        file_url_base="/storage/model-files",
        name_prefix="company_logo",
        max_bytes=5 * 1024 * 1024,
        prebuild_thumbnails=True,
    )
    logo_url = stored.file_url

    row = _setting_for_update(db, "company_info")
    company = CompanyInfo(**(row.value_json if row and isinstance(row.value_json, dict) else {})).model_dump()
    previous_logo_url = str(company.get("logo_url") or "").strip() or None
    company["logo_url"] = logo_url
    if row:
        row.value_json = CompanyInfo(**company).model_dump()
    else:
        row = SystemSetting(key="company_info", value_json=CompanyInfo(**company).model_dump())
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
