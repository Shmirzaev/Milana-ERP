"""Schema-owned persistence for paid-operation details on catalog Models.

The caller owns permissions, family selection/locking, validation, audit and the
outer transaction. This helper only assigns the prepared JSON document on the
caller-supplied Session and never flushes or commits.
"""

from sqlalchemy.orm import Session

from app.schemas.catalog.catalog import Model


def persist_model_paid_operations(db: Session, model: Model, details: dict | None) -> None:
    db.add(model)
    model.details_json = details
