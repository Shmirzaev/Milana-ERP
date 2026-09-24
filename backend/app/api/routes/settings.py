from __future__ import annotations

from functools import partial

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session, load_only

from app.core.config import settings as app_settings
from app.core.deps import CurrentUser, DbSession, require_permissions
from app.core.uploads import UploadCommitState, run_upload_db_work, upload_session_factory
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
SYSTEM_LANGUAGES = frozenset({"en", "ru", "uz"})


def _validate_settings_types(section: str, payload: dict) -> None:
    if section == "preferences" and payload.get("default_language") not in SYSTEM_LANGUAGES:
        raise HTTPException(400, "Invalid default_language")


def _setting_for_update(db: DbSession, section: str) -> SystemSetting | None:
    # A row lock alone cannot serialize the first two writes to an absent row.
    # Both PATCH and logo updates use this section-scoped transaction lock.
    if db.bind and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:namespace, :section)"),
                   {"namespace": 1_297_047_635, "section": _SETTING_LOCK_KEYS[section]})
    return (
        db.query(SystemSetting)
        .options(load_only(SystemSetting.id, SystemSetting.key, SystemSetting.value_json))
        .filter(SystemSetting.key == section)
        .with_for_update()
        .populate_existing()
        .first()
    )


def _default_payload() -> dict:
    return {key: schema().model_dump() for key, schema in _SCHEMAS.items()}


def _payload_or_default(key: str, value: object) -> dict:
    if isinstance(value, dict):
        return _SCHEMAS[key](**value).model_dump()
    return _SCHEMAS[key]().model_dump()


@router.get("")
def get_settings(db: DbSession, _: CurrentUser):
    rows = db.query(SystemSetting.key, SystemSetting.value_json).filter(
        SystemSetting.key.in_(_SCHEMAS)
    ).all()
    values = {key: value for key, value in rows}
    return {key: _payload_or_default(key, values.get(key)) for key in _SCHEMAS}


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
    _validate_settings_types(section, validated)
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

    actor_id = int(current.id)
    worker_sessions = upload_session_factory(db)
    stored = await store_uploaded_image(
        file,
        target_dir=app_settings.MODEL_FILES_DIR,
        file_url_base="/storage/model-files",
        name_prefix="company_logo",
        max_bytes=5 * 1024 * 1024,
        prebuild_thumbnails=True,
    )
    logo_url = stored.file_url
    commit_state = UploadCommitState()

    try:
        await run_upload_db_work(
            worker_sessions,
            partial(_save_uploaded_company_logo, actor_id=actor_id, logo_url=logo_url),
            commit=True,
            commit_state=commit_state,
        )
    except BaseException:
        if not commit_state.committed:
            await discard_stored_image(stored)
        raise
    return {"logo_url": logo_url}


def _save_uploaded_company_logo(
    db: Session,
    *,
    actor_id: int,
    logo_url: str,
) -> None:
    actor = db.get(User, actor_id)
    if not actor:
        raise HTTPException(401, "Inactive or unknown user")
    row = _setting_for_update(db, "company_info")
    company = CompanyInfo(
        **(row.value_json if row and isinstance(row.value_json, dict) else {})
    ).model_dump()
    company["logo_url"] = logo_url
    if row:
        row.value_json = CompanyInfo(**company).model_dump()
    else:
        row = SystemSetting(
            key="company_info",
            value_json=CompanyInfo(**company).model_dump(),
        )
        db.add(row)
        db.flush()
    log_action(
        db,
        actor,
        "upload_logo",
        "SystemSetting",
        row.id,
        new_value={"logo_url": logo_url},
    )
