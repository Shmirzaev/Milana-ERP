from collections.abc import Callable

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.libs.dto.support.settings import _SCHEMAS
from app.schemas import SystemSetting, User


def save_settings_section(
    section: str, payload: dict, db: Session, current: User, *, audit: Callable,
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
    row = SystemSetting.for_section_update(db, section)
    old_value = row.value_json if row else None
    previous = old_value if isinstance(old_value, dict) else {}
    try:
        validated = schema(**{**previous, **payload}).model_dump()
    except ValidationError as exc:
        raise RequestValidationError([
            {**error, "loc": ("body", *error["loc"])} for error in exc.errors()
        ]) from exc
    row = SystemSetting.write_section(db, section=section, setting=row, value_json=validated)
    audit(db, current, "update", "SystemSetting", row.id, old_value=old_value, new_value={section: validated})
    db.commit()
    return validated


def _default_payload() -> dict:
    return {key: schema().model_dump() for key, schema in _SCHEMAS.items()}


def _get_or_default(db: Session, key: str) -> dict:
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if row and isinstance(row.value_json, dict):
        return _SCHEMAS[key](**row.value_json).model_dump()
    return _SCHEMAS[key]().model_dump()


def get_settings(db: Session) -> dict:
    return {key: _get_or_default(db, key) for key in _SCHEMAS}
