"""Model size insertion on the caller's session; transaction stays in service."""

from sqlalchemy.orm import Session

from app.libs.types.catalog import ModelSizeCreateCommand
from app.schemas.catalog.catalog import ModelSize


def insert_model_size(db: Session, command: ModelSizeCreateCommand) -> ModelSize:
    row = ModelSize(model_id=command.model_id, size=command.size, measurement_json=command.measurement_json)
    db.add(row)
    db.flush()
    return row


def add_initial_model_sizes(db: Session, model_id: int, sizes: list[str]) -> None:
    """Stage the setup rows in order; the caller owns flush and transaction timing."""
    for size in sizes:
        db.add(ModelSize(model_id=model_id, size=size))


def delete_model_size(db: Session, row: ModelSize) -> None:
    """Schedule deletion within the caller-owned transaction."""
    db.delete(row)
