"""Model color persistence on the caller's session; transaction stays in service."""

from sqlalchemy.orm import Session

from app.libs.types.catalog import ModelColorCreateCommand
from app.schemas.catalog.catalog import ModelColor


def insert_model_color(db: Session, command: ModelColorCreateCommand) -> ModelColor:
    row = ModelColor(model_id=command.model_id, color_name=command.color_name, color_code=command.color_code)
    db.add(row)
    return row
