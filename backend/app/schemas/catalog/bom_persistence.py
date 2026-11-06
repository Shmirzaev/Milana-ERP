"""Schema-owned persistence for the catalog BOM rows.

These helpers own mapped construction, add and flush for BOM creation,
mapped assignments for BOM updates, and mapped deletion. Update and delete
helpers do not flush, preserving the service's audit/commit ordering. Business
decisions, uniqueness checks, linked-cutting refusals, real audit and the outer
transaction stay in
`app/models/catalog/models_service.py`.
"""

from sqlalchemy.orm import Session

from app.libs.types.catalog import NormalizedBomCreate, NormalizedBomUpdate
from app.schemas.catalog.catalog import ModelBOM


def build_model_bom(model_id: int, create: NormalizedBomCreate) -> ModelBOM:
    """Build one BOM row. The role is serialized only at the mapped assignment."""
    return ModelBOM(
        model_id=model_id,
        item_id=create.item_id,
        material_name=create.material_name,
        material_role=create.material_role.value if create.material_role is not None else None,
        stock_batch_id=create.stock_batch_id,
        size=create.size,
        color=create.color,
        photo_url=create.photo_url,
        quantity_per_piece=create.quantity_per_piece,
        unit=create.unit,
        waste_percent=create.waste_percent,
    )


def insert_model_bom(db: Session, *, model_id: int, create: NormalizedBomCreate) -> ModelBOM:
    """Build and add one BOM row to the caller's session.

    The caller owns the transaction: this helper never commits, rolls back or
    begins one.
    """
    row = build_model_bom(model_id, create)
    db.add(row)
    db.flush()
    return row


def update_model_bom(
    db: Session,
    *,
    row: ModelBOM,
    values: NormalizedBomUpdate,
) -> ModelBOM:
    """Apply service-decided fields to a BOM row in the caller's transaction.

    No flush or transaction control belongs here. Missing keys stay untouched;
    present ``None`` values clear nullable columns. Enum values are serialized
    at the mapped string-column boundary.
    """
    for key, value in values.items():
        if key == "material_role" and value is not None:
            value = value.value
        setattr(row, key, value)
    return row


def delete_model_bom(db: Session, row: ModelBOM) -> None:
    """Mark one already-checked BOM row for deletion in the caller's session.

    The catalog service owns lookup, refusal policy, audit and commit. This
    helper performs no query, flush, commit or rollback.
    """
    db.delete(row)
