"""Apply a decided model approval using the operation's supplied session."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.schemas.catalog.catalog import Model


def apply_model_approval(db: Session, row: Model, *, actor_id: int, approved_at: datetime) -> None:
    row.status = "approved"
    row.approved_by = actor_id
    row.approved_at = approved_at
