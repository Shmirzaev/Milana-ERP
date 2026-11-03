"""Model size insertion on the caller's session; transaction stays in service."""

from sqlalchemy.orm import Session

from app.libs.types.catalog import ModelSizeCreateCommand
from app.schemas.catalog.catalog import ModelSize


def insert_model_size(db: Session, command: ModelSizeCreateCommand) -> ModelSize:
    row = ModelSize(model_id=command.model_id, size=command.size, measurement_json=command.measurement_json)
    db.add(row)
    db.flush()
    return row
