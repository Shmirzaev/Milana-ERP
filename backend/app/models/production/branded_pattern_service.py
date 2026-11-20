"""Require persisted catalog pattern evidence for new branded production."""
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.schemas import Model, ModelImage


def require_branded_pattern(db: Session, model: Model) -> None:
    details = model.details_json if isinstance(model.details_json, dict) else {}
    general = details.get("general")
    general = general if isinstance(general, dict) else {}
    keys = ("qolip_no", "qolipNo", "mold_no", "moldNo", "pattern_no", "patternNo")
    number = any(isinstance(value, (str, int, float)) and not isinstance(value, bool) and str(value).strip()
                 for value in (general.get(key) for key in keys))
    attachment = db.scalar(select(select(ModelImage.id).where(
        ModelImage.model_id == model.id, ModelImage.image_type == "pattern",
        func.length(func.trim(ModelImage.file_url)) > 0,
    ).exists()))
    if not number or not attachment:
        if not number and not attachment:
            detail = "Enter the Qolip number and attach the Qolip file to this model before creating a BSO."
        elif not number:
            detail = "Enter the Qolip number on this model before creating a BSO."
        else:
            detail = "Attach the Qolip file to this model before creating a BSO."
        raise HTTPException(409, detail)
