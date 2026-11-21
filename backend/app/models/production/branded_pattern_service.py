"""Require persisted catalog pattern evidence for new branded production."""
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.model_family_images_service import model_family_identity_members
from app.schemas import Model, ModelImage


def require_branded_pattern(db: Session, model: Model) -> None:
    details = model.details_json if isinstance(model.details_json, dict) else {}
    general = details.get("general")
    general = general if isinstance(general, dict) else {}
    keys = ("qolip_no", "qolipNo", "mold_no", "moldNo", "pattern_no", "patternNo")
    number = any(isinstance(value, (str, int, float)) and not isinstance(value, bool) and str(value).strip()
                 for value in (general.get(key) for key in keys))
    patterns = select(ModelImage.id).where(
        ModelImage.image_type == "pattern",
        func.length(func.trim(ModelImage.file_url)) > 0,
    )
    attachment = db.scalar(select(patterns.where(ModelImage.model_id == model.id).exists()))
    if not attachment:
        family_ids = [member.id for member in model_family_identity_members(model) if member.id != model.id]
        if family_ids:
            attachment = db.scalar(select(patterns.where(ModelImage.model_id.in_(family_ids)).exists()))
    if not number or not attachment:
        if not number and not attachment:
            detail = "Enter the Qolip number and attach the Qolip file to this model before creating a BSO."
        elif not number:
            detail = "Enter the Qolip number on this model before creating a BSO."
        else:
            detail = "Attach the Qolip file to this model before creating a BSO."
        raise HTTPException(409, detail)
