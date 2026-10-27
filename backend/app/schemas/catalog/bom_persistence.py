"""Schema-owned persistence for the catalog BOM rows.

These helpers own the mapped construction, the add and the flush of the row the
catalog BOM create operation writes. The business decisions, the main-material
uniqueness check, the real audit and the outer commit stay in
`app/models/catalog/models_service.py`.
"""

from sqlalchemy.orm import Session

from app.libs.types.catalog import NormalizedBomCreate
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
