"""Persistence for an already-authorized variant deletion."""

from sqlalchemy.orm import Session

from app.schemas.catalog.catalog import CollectionModel, Model


def delete_variant_rows(db: Session, *, target: Model, variant_id: int) -> None:
    """Remove collection links and mark the model (and its ORM children) deleted.

    The caller owns policy, audit and transaction control. Keep the bulk delete's
    synchronization mode and defer flushing to the existing audit boundary.
    """
    db.query(CollectionModel).filter(CollectionModel.model_id == variant_id).delete(synchronize_session=False)
    db.delete(target)
