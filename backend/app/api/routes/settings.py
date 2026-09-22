from __future__ import annotations


from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationError
from sqlalchemy import text

from app.core.config import settings as app_settings
from app.core.deps import CurrentUser, DbSession, require_permissions
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
_SETTING_LOCK_KEYS = {"company_info": 1, "financial": 2, "preferences": 3}


def _setting_for_update(db: DbSession, section: str) -> SystemSetting | None:
    # A row lock alone cannot serialize the first two writes to an absent row.
    # Both PATCH and logo updates use this section-scoped transaction lock.
    if db.bind and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:namespace, :section)"),
                   {"namespace": 1_297_047_635, "section": _SETTING_LOCK_KEYS[section]})
    return db.query(SystemSetting).filter(SystemSetting.key == section).with_for_update().populate_existing().first()


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
    unknown = sorted(set(payload) - schema.model_fields.keys())
    if unknown:
        raise RequestValidationError([
            {"type": "extra_forbidden", "loc": ("body", field), "msg": "Extra inputs are not permitted", "input": payload[field]}
            for field in unknown
        ])
    row = _setting_for_update(db, section)
    old_value = row.value_json if row else None
    previous = old_value if isinstance(old_value, dict) else {}
    try:
        validated = schema(**{**previous, **payload}).model_dump()
    except ValidationError as exc:
        raise RequestValidationError([
            {**error, "loc": ("body", *error["loc"])} for error in exc.errors()
        ]) from exc
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
    from app.services.image_storage import discard_stored_image, store_uploaded_image

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
        row = _setting_for_update(db, "company_info")
        company = CompanyInfo(**(row.value_json if row and isinstance(row.value_json, dict) else {})).model_dump()
        company["logo_url"] = logo_url
        if row:
            row.value_json = CompanyInfo(**company).model_dump()
        else:
            row = SystemSetting(key="company_info", value_json=CompanyInfo(**company).model_dump())
            db.add(row)
            db.flush()
        log_action(db, current, "upload_logo", "SystemSetting", row.id, new_value={"logo_url": logo_url})
        db.commit()
    except BaseException:
        try:
            db.rollback()
        finally:
            await discard_stored_image(stored)
        raise
    return {"logo_url": logo_url}
