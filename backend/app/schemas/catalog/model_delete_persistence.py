"""Persistence mechanics for a model whose service guards have passed."""

from sqlalchemy.orm import Session

from app.schemas.catalog.catalog import CollectionModel, Model


def delete_checked_model(db: Session, model: Model) -> None:
    """Delete collection links and mark the model for ORM cascade deletion.

    Preserve the bulk-delete synchronization mode and leave audit, flush timing,
    commit and rollback to the calling operation.
    """
    db.query(CollectionModel).filter(CollectionModel.model_id == model.id).delete(
        synchronize_session=False
    )
    db.delete(model)
