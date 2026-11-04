"""Model creation mechanics on the service's supplied transaction."""

from sqlalchemy.orm import Session

from app.schemas.catalog.catalog import Model


def build_model(*, values: dict, catalog_scope: str, factory_code: str | None, created_by: int) -> Model:
    return Model(**values, catalog_scope=catalog_scope, factory_code=factory_code, created_by=created_by)


def insert_model(db: Session, model: Model, *, approval: Model | None) -> Model:
    if approval:
        model.status = "approved"
        model.approved_by = approval.approved_by
        model.approved_at = approval.approved_at
    db.add(model)
    db.flush()
    return model
